import csv
import hashlib
import io
import json
import re
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import certifi

from config import DRIVE_ROOT_FOLDER_ID
from services.drive_write import DRIVE_API, _token
from importers import MANIFEST, SOURCE_ROOT, import_all


STATE_PATH = Path("data/public_sync_state.json")
_started = False
_lock = threading.Lock()
_status = {"running": False, "last_sync": None, "changed": 0, "errors": [], "source": "", "total": 0}
_ssl_context = ssl.create_default_context(cafile=certifi.where())
FOLDER_MIME = "application/vnd.google-apps.folder"
DOC_MIME = "application/vnd.google-apps.document"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
EXTENSIONS = {
    DOC_MIME: ".txt",
    SHEET_MIME: ".csv",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "text/csv": ".csv",
}
SUPPORTED_MIMES = set(EXTENSIONS) | {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def _download_url(url):
    sheets = re.search(r"docs\.google\.com/spreadsheets/d/([^/]+)", url)
    if sheets:
        return f"https://docs.google.com/spreadsheets/d/{sheets.group(1)}/export?format=csv"
    docs = re.search(r"docs\.google\.com/document/d/([^/]+)", url)
    if docs:
        return f"https://docs.google.com/document/d/{docs.group(1)}/export?format=txt"
    drive = re.search(r"drive\.google\.com/file/d/([^/]+)", url)
    if drive:
        return f"https://drive.usercontent.google.com/download?id={drive.group(1)}&export=download&confirm=t"
    raise ValueError("지원하지 않는 공개 Google Drive 링크입니다.")


def _read_state():
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _target(file_name, bucket=""):
    existing = next(SOURCE_ROOT.glob(f"U-*/{file_name}"), None)
    if existing:
        return existing
    project = re.match(r"(U-\d{2})", file_name)
    if "문서관리대장" in file_name:
        return SOURCE_ROOT / "_registry" / file_name
    if not project:
        return SOURCE_ROOT / (bucket or "_other") / file_name
    return SOURCE_ROOT / project.group(1) / file_name


def _valid_content(file_name, content):
    if file_name.lower().endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                return "word/document.xml" in archive.namelist()
        except zipfile.BadZipFile:
            return False
    try:
        return bool(content.decode("utf-8-sig").strip())
    except UnicodeDecodeError:
        return False


def _list_drive_folder(folder_id, token):
    """Return all immediate Drive children; pagination is hidden from callers."""
    items = []
    page_token = ""
    while True:
        query = urllib.parse.urlencode({
            "q": f"'{folder_id}' in parents and trashed=false",
            "fields": "nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime,md5Checksum)",
            "pageSize": 1000,
            "pageToken": page_token,
        })
        request = urllib.request.Request(
            f"{DRIVE_API}/files?{query}",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "MomentLab/1.0"},
        )
        with urllib.request.urlopen(request, timeout=25, context=_ssl_context) as response:
            payload = json.load(response)
        items.extend(payload.get("files", []))
        page_token = payload.get("nextPageToken", "")
        if not page_token:
            return items


def _bucket(name, parent_bucket):
    if parent_bucket:
        return parent_bucket
    if name == "표준 업무 매뉴얼":
        return "_manuals"
    if name == "양식":
        return "_templates"
    if name == "프로젝트":
        return "프로젝트"
    return "_other"


def _local_name(item):
    name = item["name"]
    extension = EXTENSIONS.get(item["mimeType"], "")
    if item["mimeType"] in {DOC_MIME, SHEET_MIME}:
        return str(Path(name).with_suffix(extension))
    return name if not extension or name.lower().endswith(extension) else name + extension


def _discover_drive_files(root_folder_id, token):
    """Recursively list supported files below the configured Drive root."""
    discovered = []
    pending = [(root_folder_id, "")]
    while pending:
        folder_id, parent_bucket = pending.pop()
        for item in _list_drive_folder(folder_id, token):
            if item["mimeType"] == FOLDER_MIME:
                pending.append((item["id"], _bucket(item["name"], parent_bucket)))
                continue
            if item["mimeType"] not in SUPPORTED_MIMES:
                continue
            bucket = "_registry" if "문서관리대장" in item["name"] else (parent_bucket or "_other")
            discovered.append({
                "file_id": item["id"],
                "file_name": _local_name(item),
                "bucket": bucket,
                "mime_type": item["mimeType"],
                "source_drive_url": item.get("webViewLink", f"https://drive.google.com/open?id={item['id']}"),
                "modified_time": item.get("modifiedTime", ""),
            })
    return discovered


def _drive_download_url(item):
    if item["mime_type"] == DOC_MIME:
        return f"{DRIVE_API}/files/{item['file_id']}/export?mimeType=text%2Fplain"
    if item["mime_type"] == SHEET_MIME:
        return f"{DRIVE_API}/files/{item['file_id']}/export?mimeType=text%2Fcsv"
    return f"{DRIVE_API}/files/{item['file_id']}?alt=media"


def _manifest_rows():
    with MANIFEST.open(encoding="utf-8") as handle:
        return [
            {"file_name": row["file_name"], "source_drive_url": row["source_drive_url"], "state_key": row["file_name"]}
            for row in csv.DictReader(handle)
        ]


def _remove_deleted_drive_files(state, current_keys):
    changed = 0
    for key in list(state):
        if not key.startswith("drive:") or key in current_keys:
            continue
        target = Path(state[key].get("path", ""))
        if SOURCE_ROOT in target.parents and target.exists():
            target.unlink()
            changed += 1
        del state[key]
    return changed


def sync_once(timeout=25):
    """Sync the configured Drive tree, with the manifest as an offline fallback."""
    if not _lock.acquire(blocking=False):
        return dict(_status)
    try:
        _status.update(running=True, errors=[])
        state = _read_state()
        changed = 0
        token = ""
        source = "매니페스트"
        try:
            token = _token()
            rows = [
                {**item, "state_key": f"drive:{item['file_id']}", "download_url": _drive_download_url(item)}
                for item in _discover_drive_files(DRIVE_ROOT_FOLDER_ID, token)
            ]
            changed += _remove_deleted_drive_files(state, {row["state_key"] for row in rows})
            source = "Drive 폴더"
        except (OSError, RuntimeError, urllib.error.URLError, urllib.error.HTTPError, ValueError) as exc:
            _status["errors"].append(f"Drive 전체 동기화: {exc}")
            rows = _manifest_rows()
        for row in rows:
            name = row["file_name"]
            state_key = row["state_key"]
            previous = state.get(state_key, {})
            headers = {"User-Agent": "MomentLab/1.0"}
            if token and row.get("download_url"):
                headers["Authorization"] = f"Bearer {token}"
            if previous.get("etag"):
                headers["If-None-Match"] = previous["etag"]
            if previous.get("last_modified"):
                headers["If-Modified-Since"] = previous["last_modified"]
            request = urllib.request.Request(row.get("download_url") or _download_url(row["source_drive_url"]), headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context) as response:
                    content = response.read()
                    metadata = {
                        "etag": response.headers.get("ETag", ""),
                        "last_modified": response.headers.get("Last-Modified", ""),
                    }
            except urllib.error.HTTPError as exc:
                if exc.code == 304:
                    continue
                _status["errors"].append(f"{name}: HTTP {exc.code}")
                continue
            except (OSError, urllib.error.URLError) as exc:
                _status["errors"].append(f"{name}: {exc}")
                continue

            digest = hashlib.sha256(content).hexdigest()
            if digest == previous.get("sha256"):
                state[state_key] = {**previous, **metadata, "sha256": digest}
                continue
            if not _valid_content(name, content):
                _status["errors"].append(f"{name}: 공개 링크 응답이 문서 형식과 다릅니다.")
                continue
            target = _target(name, row.get("bucket", ""))
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".sync")
            temporary.write_bytes(content)
            temporary.replace(target)
            state[state_key] = {**metadata, "sha256": digest, "path": str(target)}
            changed += 1

        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        if changed:
            import_all()
        _status.update(running=False, last_sync=time.time(), changed=changed, source=source, total=len(rows))
        return dict(_status)
    finally:
        _status["running"] = False
        _lock.release()


def start_background_sync(interval=60):
    global _started
    if _started:
        return
    _started = True

    def loop():
        while True:
            sync_once()
            time.sleep(interval)

    threading.Thread(target=loop, name="public-drive-sync", daemon=True).start()


def status():
    return dict(_status)
