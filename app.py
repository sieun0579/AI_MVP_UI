from pathlib import Path
import re
import time
import uuid

import streamlit as st

from config import ACTIVE_PROJECT_SEARCH_THRESHOLD, SEARCH_CONFIDENCE_THRESHOLD
from db import init_db
from importers import import_all
from services.ollama_client import expand_query, generate, predict_search_terms
from services.conversation_store import (
    backfill_legacy_sessions, create_session, delete_session, list_sessions,
    load_session, rename_session, save_exchange, session_exists,
)
from services.memory_flow import (
    assess_candidate, assess_statement, close_project_memories, discard_candidate, is_fact_statement, pending_candidates,
    failed_retrospective_exports, project_is_complete, publish_candidate, publish_retrospective,
    save_candidate, update_candidate,
)
from services.public_drive_sync import start_background_sync, sync_once
from services.project_context import (
    active_project_answer, explicit_project, is_active_project_list_question,
    in_progress_project_id, in_progress_result_answer, is_current_project_question,
    is_followup_question, is_manual_question, is_result_question, load_active_projects,
    new_session_context, project_ids, select_entity_from_results,
)
from services.retrieval import find_documents_by_title, highlight_html, search_documents
from services.retrospective_draft import (
    INPUT_NEEDED, completion, create_draft as create_retrospective_draft,
    grouped_candidates, load_draft, render_docx, save_draft,
)


st.set_page_config(page_title="MomentLab 조직 기억", page_icon="🧠", layout="wide")


def apply_figma_theme():
    st.markdown(
        """
        <style>
        :root {
          --moment-ink: #302827;
          --moment-muted: #8b807e;
          --moment-rose: #bd6271;
          --moment-soft-rose: #f9e8e8;
          --moment-paper: #fffdfb;
          --moment-line: #efe7e4;
        }
        .stApp { background: #fcf9f7; color: var(--moment-ink); }
        [data-testid="stHeader"] { background: transparent; }
        [data-testid="stToolbar"] { right: 1rem; }
        [data-testid="stSidebar"] {
          background: var(--moment-paper);
          border-right: 1px solid var(--moment-line);
        }
        [data-testid="stSidebar"] > div:first-child { padding: 2rem 0.85rem; }
        [data-testid="stSidebar"] .sidebar-brand {
          align-items: center; display: flex; gap: 0.65rem; margin: 0.15rem 0 1.35rem; padding: 0 0.15rem;
        }
        [data-testid="stSidebar"] .sidebar-brand strong { color: var(--moment-ink); display: block; font-size: 0.91rem; letter-spacing: -0.03em; }
        [data-testid="stSidebar"] .sidebar-brand small { color: var(--moment-muted); display: block; font-size: 0.62rem; margin-top: 0.1rem; }
        [data-testid="stSidebar"] .brand-mark {
          background: var(--moment-soft-rose); border-radius: 50%; display: inline-block; height: 1.75rem; position: relative; width: 1.75rem;
        }
        [data-testid="stSidebar"] .brand-mark::before {
          border: 1.8px solid var(--moment-rose); border-radius: 50%; content: ""; height: 0.7rem; left: 0.48rem; position: absolute; top: 0.42rem; width: 0.78rem;
        }
        [data-testid="stSidebar"] .brand-mark::after {
          border-bottom: 1.8px solid var(--moment-rose); content: ""; left: 0.51rem; position: absolute; top: 1.17rem; transform: rotate(-33deg); width: 0.28rem;
        }
        [data-testid="stSidebar"] h3 {
          color: var(--moment-muted); font-size: 0.73rem; font-weight: 700;
          letter-spacing: 0.02em; margin: 1.8rem 0 0.55rem;
        }
        [data-testid="stSidebar"] .stButton > button {
          border: 0; background: transparent; color: #625957; border-radius: 8px;
          font-size: 0.8rem; font-weight: 500; min-height: 2.45rem; padding: 0.45rem 0.65rem;
          text-align: left;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
          background: var(--moment-rose); color: white; text-align: center; box-shadow: none;
        }
        [data-testid="stSidebar"] button[kind="secondary"] {
          border: 0; background: transparent; color: #625957; border-radius: 8px;
        }
        [data-testid="stSidebar"] button[kind="primary"] {
          border: 0; background: var(--moment-rose); color: white; box-shadow: none;
        }
        [data-testid="stSidebar"] [class*="st-key-chat-"] button[kind="primary"] {
          background: var(--moment-soft-rose); color: #71504f; text-align: left;
        }
        [data-testid="stSidebar"] [class*="st-key-menu-"] button {
          background: transparent; color: #766c6a; font-size: 1.35rem; font-weight: 700; line-height: 1; min-height: 2.2rem; padding: 0; width: 2rem;
        }
        [data-testid="stSidebar"] [class*="st-key-menu-"] button p { line-height: 1; margin: 0; transform: translateY(-0.08rem); }
        [data-testid="stSidebar"] .stButton > button:hover { background: var(--moment-soft-rose); color: var(--moment-rose); }
        [data-testid="stSidebar"] button[kind="secondary"]:hover { background: var(--moment-soft-rose); color: var(--moment-rose); }
        [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover { background: #aa5363; color: white; }
        [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] { gap: 0.2rem; }
        .block-container { max-width: 1040px; padding: 3.2rem 2.6rem 8rem; }
        h1 { color: var(--moment-ink); font-size: 1.7rem !important; font-weight: 750; letter-spacing: -0.045em; margin-bottom: 0.2rem; }
        [data-testid="stCaptionContainer"] { color: var(--moment-muted); }
        [data-testid="stChatMessage"] {
          background: transparent; border: 0; box-shadow: none; margin: 0.75rem 0; padding: 0;
        }
        [data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] { color: var(--moment-ink); font-size: 0.93rem; line-height: 1.7; }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
          justify-content: flex-end; margin-left: 0; width: 100%; max-width: none;
        }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageAvatarUser"] { display: none; }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
          background: var(--moment-soft-rose); border-radius: 14px 14px 3px 14px; flex: 0 1 68%; margin: 0 0 0 auto; padding: 0.75rem 1rem;
        }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageAvatarAssistant"] {
          background: var(--moment-soft-rose); color: var(--moment-rose);
        }
        [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarAssistant"]) [data-testid="stChatMessageContent"] {
          background: var(--moment-paper); border: 1px solid var(--moment-line); border-radius: 3px 18px 18px; box-shadow: 0 3px 14px rgba(78, 48, 45, 0.035); padding: 1rem 1.15rem;
        }
        [data-testid="stExpander"] {
          border: 1px solid var(--moment-line); border-radius: 10px; background: #fff; overflow: hidden;
          box-shadow: none;
        }
        [data-testid="stExpander"] summary { background: var(--moment-soft-rose); color: #514747; font-size: 0.82rem; }
        [data-testid="stChatInput"] { border: 1px solid #eadedd; border-radius: 12px; background: white; box-shadow: 0 6px 20px rgba(75, 40, 40, 0.07); }
        [data-testid="stChatInput"] textarea { color: var(--moment-ink); font-size: 0.9rem; }
        [data-testid="stChatInput"] button { background: var(--moment-rose); color: white; border-radius: 8px; }
        [data-testid="stAlert"] { border-radius: 10px; }
        [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea {
          background: #fffdfa; border-color: #ead3d5; border-radius: 10px;
        }
        [data-testid="stCheckbox"] input { accent-color: var(--moment-rose); }
        section.main .stButton > button[kind="secondary"] {
          background: #fffdfa; border-color: #dfbfc4; color: #6e4c51;
        }
        section.main .stButton > button[kind="primary"] { background: var(--moment-rose); border-color: var(--moment-rose); }
        [data-testid="stProgress"] > div > div { background: var(--moment-rose); }
        @media (min-width: 900px) {
          [data-testid="stSidebar"] { min-width: 255px; max-width: 255px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


apply_figma_theme()
con = init_db()
if not con.execute("SELECT 1 FROM documents LIMIT 1").fetchone() and Path("data/drive_manifest.csv").exists():
    import_all()
    con = init_db()
if "initial_drive_sync" not in st.session_state:
    sync_once()
    st.session_state.initial_drive_sync = True
start_background_sync()
backfill_legacy_sessions(con)


def start_new_chat():
    st.session_state.history = []
    st.session_state.session_id = uuid.uuid4().hex
    st.session_state.project_context = new_session_context()
    st.session_state.view = "chat"
    st.query_params.clear()


def restore_chat(session_id):
    restored = load_session(con, session_id)
    if not restored:
        return False
    st.session_state.history = restored["history"]
    st.session_state.session_id = restored["session_id"]
    st.session_state.project_context = restored["context"]
    st.session_state.view = "chat"
    st.query_params["chat"] = session_id
    return True


if "chat_initialized" not in st.session_state:
    requested_chat = st.query_params.get("chat", "")
    if not restore_chat(requested_chat):
        start_new_chat()
    requested_view = st.query_params.get("view", "chat")
    if requested_view in {"memory", "draft"}:
        st.session_state.view = requested_view
    if st.query_params.get("draft"):
        st.session_state.draft_id = st.query_params.get("draft")
    st.session_state.chat_initialized = True
if "view" not in st.session_state:
    st.session_state.view = "chat"

with st.sidebar:
    st.markdown(
        '''<div class="sidebar-brand"><span class="brand-mark" aria-hidden="true"></span><div><strong>조직 기억</strong><small>모먼트랩 업무 공간</small></div></div>''',
        unsafe_allow_html=True,
    )
    if st.button(
        "＋ 새 질문", use_container_width=True, type="primary",
        help="현재 대화는 보존하고 빈 대화를 시작합니다.",
    ):
        start_new_chat()
        st.rerun()
    st.markdown("### 최근 대화")
    sessions = list_sessions(con)
    if not sessions:
        st.caption("저장된 대화가 없습니다.")
    for item in sessions:
        selected = item["session_id"] == st.session_state.session_id
        label = ("▸ " if selected else "") + item["title"]
        session_id = item["session_id"]
        if st.session_state.get("renaming_session") == session_id:
            edited_title = st.text_input("대화 이름", value=item["title"], key=f"rename-input-{session_id}")
            save_col, cancel_col = st.columns(2)
            if save_col.button("저장", key=f"rename-save-{session_id}"):
                rename_session(con, session_id, edited_title)
                st.session_state.pop("renaming_session", None)
                st.rerun()
            if cancel_col.button("취소", key=f"rename-cancel-{session_id}"):
                st.session_state.pop("renaming_session", None)
                st.rerun()
            continue
        chat_col, menu_col = st.columns([9, 1])
        if chat_col.button(
            label, key=f"chat-{session_id}", use_container_width=True,
            type="primary" if selected else "secondary",
        ):
            restore_chat(session_id)
            st.rerun()
        if menu_col.button("⋮", key=f"menu-{session_id}", help="대화 메뉴"):
            st.session_state.chat_menu_session = (
                "" if st.session_state.get("chat_menu_session") == session_id else session_id
            )
            st.rerun()
        if st.session_state.get("chat_menu_session") == session_id:
            rename_col, delete_col = st.columns(2)
            if rename_col.button("이름 수정", key=f"rename-{session_id}"):
                st.session_state.renaming_session = session_id
                st.session_state.pop("chat_menu_session", None)
                st.rerun()
            if delete_col.button("삭제", key=f"delete-{session_id}"):
                st.session_state.deleting_session = session_id
                st.session_state.pop("chat_menu_session", None)
                st.rerun()
        if st.session_state.get("deleting_session") == session_id:
            st.caption("이 대화를 삭제할까요?")
            confirm_col, cancel_col = st.columns(2)
            if confirm_col.button("삭제", key=f"delete-confirm-{session_id}", type="primary"):
                delete_session(con, session_id)
                st.session_state.pop("deleting_session", None)
                if selected:
                    start_new_chat()
                st.rerun()
            if cancel_col.button("취소", key=f"delete-cancel-{session_id}"):
                st.session_state.pop("deleting_session", None)
                st.rerun()
    st.markdown("### 조직기억")
    pending_count = len(pending_candidates(con))
    if st.button(
        f"조직기억 검토함  {pending_count}", use_container_width=True,
        type="primary" if st.session_state.view in {"memory", "draft"} else "secondary",
    ):
        st.session_state.view = "memory"
        st.query_params["view"] = "memory"
        st.rerun()

if st.session_state.view == "chat":
    st.title("MomentLab 조직 기억")
    st.caption("연결된 Google Drive 문서를 바탕으로 답합니다.")
elif st.session_state.view == "memory":
    st.title("조직기억 검토함")
    st.caption("검토한 기억을 선택해 프로젝트 초안 회고록을 작성합니다.")
else:
    st.title("초안 회고록")
    st.caption("근거가 없는 항목은 입력 필요 상태로 유지됩니다.")


def save_from_chat(exchange, candidate, summary, edited=False):
    source = next((item for item in exchange.get("documents", []) if item.get("document_id")), {})
    drive_match = re.search(r"/(?:d|file/d)/([^/?]+)", source.get("source_drive_url", ""))
    candidate_id = save_candidate(
        con, candidate["project_id"], candidate["original_text"], summary,
        candidate["candidate_type"], exchange.get("conversation_ids", ()),
        edited_text=summary if edited else "", conflict_note=candidate.get("conflict_note", ""),
        title=candidate["title"], source_document_id=source.get("document_id", ""),
        source_drive_file_id=drive_match.group(1) if drive_match else "",
    )
    exchange["candidate_action"] = "saved"
    exchange["drive_result"] = None


def persist_rendered_exchange(index, exchange):
    if not session_exists(con, st.session_state.session_id):
        return
    save_exchange(
        con, st.session_state.session_id, index, exchange,
        st.session_state.project_context,
    )


def render_memory_inbox():
    groups = grouped_candidates(con)
    failed_exports = failed_retrospective_exports(con)
    if not groups and not failed_exports:
        st.info("검토하거나 초안에 반영할 조직기억 후보가 없습니다.")
        return
    for group in groups:
        project_id = group["project_id"]
        project_items = group["items"]
        complete = project_is_complete(con, project_id)
        label = f"{project_id} · {'종료 문서 확인됨' if complete else '진행중'} · {group['title']} · {len(project_items)}건"
        with st.expander(label, expanded=True):
            st.caption(
                f"검토 대기 {len(project_items)}건 · 최종 수정 {group['updated_at'] or '확인 필요'}"
            )
            selected_ids = []
            for item in project_items:
                checked = st.checkbox(
                    item["title"], value=item.get("draft_status") in {"selected_for_draft", "included_in_draft"},
                    key=f"draft-select-{item['candidate_id']}",
                    disabled=bool(item.get("draft_id")),
                )
                if checked:
                    selected_ids.append(item["candidate_id"])
                next_status = "selected_for_draft" if checked else "pending"
                if not item.get("draft_id") and item.get("draft_status") != next_status:
                    con.execute(
                        "UPDATE memory_candidates SET draft_status=? WHERE candidate_id=?",
                        (next_status, item["candidate_id"]),
                    )
                    con.commit()
                title = st.text_input("제목", item["title"], key=f"inbox-title-{item['candidate_id']}")
                summary = st.text_area("내용", item["user_edited_text"] or item["summary"], key=f"inbox-summary-{item['candidate_id']}")
                if item["conflict_note"]:
                    st.warning("기존 기록과의 차이: " + item["conflict_note"])
                if item["drive_status"] == "error":
                    st.error("Drive 반영 실패: " + item["drive_error"])
                save_col, discard_col = st.columns(2)
                if save_col.button("수정 저장", key=f"inbox-save-{item['candidate_id']}"):
                    update_candidate(con, item["candidate_id"], title, summary)
                    st.rerun()
                if discard_col.button("저장하지 않음", key=f"inbox-discard-{item['candidate_id']}", disabled=bool(item["finalized_at"])):
                    discard_candidate(con, item["candidate_id"])
                    st.rerun()
            st.caption(f"{len(selected_ids)}개 선택됨")
            if st.button(
                "초안 회고록 작성", key=f"create-draft-{group['key']}", type="primary",
                disabled=not selected_ids,
            ):
                st.session_state.draft_id = create_retrospective_draft(con, project_id, selected_ids)
                st.session_state.view = "draft"
                st.query_params["view"] = "draft"
                st.query_params["draft"] = str(st.session_state.draft_id)
                st.rerun()
            if complete:
                st.caption("기존 최종 확인 및 Drive 반영 흐름도 계속 사용할 수 있습니다.")
                if st.button("기존 방식으로 최종 반영", key=f"publish-project-{group['key']}"):
                    close_project_memories(con, project_id)
                    st.rerun()
    for export in failed_exports:
        st.markdown(f"#### {export['project_id']} · 회고록 Drive 반영 실패")
        st.error(export["error"])
        if st.button("회고록 Drive 반영 재시도", key=f"retry-export-{export['export_id']}"):
            publish_retrospective(con, export["project_id"])
            st.rerun()


def render_draft_editor():
    draft_id = st.session_state.get("draft_id") or st.query_params.get("draft")
    record = load_draft(con, int(draft_id)) if draft_id else None
    if not record:
        st.error("초안 회고록을 찾을 수 없습니다.")
        if st.button("검토함으로 돌아가기"):
            st.session_state.view = "memory"
            st.rerun()
        return
    draft = record["draft_json"]
    percent, missing = completion(draft)
    st.subheader(f"{draft['project_id']} · {draft['project_name']}")
    st.progress(percent / 100, text=f"초안 회고록 자동 작성 완료 {percent}%")
    if missing:
        st.warning(f"사용자 입력이 필요한 항목이 {missing}개 있습니다.")
    with st.expander("근거 및 반영 위치 추적"):
        st.json({"field_sources": record["field_sources"], "candidate_placements": record["candidate_placements"]})
    for section_name, section in draft["sections"].items():
        with st.expander(section_name, expanded=section_name.startswith(("00", "05", "08", "09"))):
            if isinstance(section, dict):
                for field, value in list(section.items()):
                    if isinstance(value, (str, int, float)):
                        section[field] = st.text_area(
                            field, str(value), key=f"draft-{draft_id}-{section_name}-{field}",
                            height=70,
                        )
                    else:
                        st.json(value)
            elif isinstance(section, list):
                if not section:
                    st.caption("확인된 근거 없음")
                for item_index, item in enumerate(section):
                    if isinstance(item, dict):
                        st.markdown(f"**{item_index + 1}**")
                        for field, value in list(item.items()):
                            item[field] = st.text_area(
                                field, str(value),
                                key=f"draft-{draft_id}-{section_name}-{item_index}-{field}", height=68,
                            )
                    else:
                        st.write(item)
    save_col, back_col = st.columns(2)
    if save_col.button("초안 저장", type="primary", use_container_width=True):
        save_draft(con, int(draft_id), draft)
        st.success("초안을 저장했습니다.")
    if back_col.button("검토함으로 돌아가기", use_container_width=True):
        save_draft(con, int(draft_id), draft)
        st.session_state.view = "memory"
        st.query_params["view"] = "memory"
        st.query_params.pop("draft", None)
        st.rerun()
    allow_download = True
    if missing:
        allow_download = st.checkbox(
            f"아직 입력되지 않은 항목 {missing}개를 확인했습니다. 초안 상태로 계속 다운로드합니다.",
            key=f"confirm-download-{draft_id}",
        )
    file_name = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", f"{draft['project_id']}_{draft['project_name']}_초안회고록_{time.strftime('%Y%m%d')}.docx")
    st.download_button(
        "Word 다운로드", data=render_docx(draft), file_name=file_name,
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        disabled=not allow_download, use_container_width=True,
    )


if st.session_state.view == "memory":
    render_memory_inbox()
    st.stop()
if st.session_state.view == "draft":
    render_draft_editor()
    st.stop()


def render_candidate(exchange, index):
    candidate = exchange.get("candidate")
    if not candidate or exchange.get("candidate_action"):
        if exchange.get("candidate_action") == "saved":
            drive_result = exchange.get("drive_result")
            if drive_result and drive_result["drive_status"] == "uploaded":
                st.caption("완료 프로젝트의 공식 기억으로 확정하고 Google Drive에 반영했습니다.")
            elif drive_result:
                st.caption("공식 기억으로 확정했지만 Drive 반영에 실패했습니다. 조직 기억 검토함에서 오류를 확인하고 재시도할 수 있습니다.")
            else:
                st.caption("조직 기억 검토함에 pending_review 상태로 등록했습니다. 검토 승인 전에는 공식 답변 근거로 사용하지 않습니다.")
        elif exchange.get("candidate_action") == "discarded":
            st.caption("이 기억 후보는 저장하지 않았습니다.")
        return
    st.info(candidate["reason"] or "기존 Context에서 확인되지 않는 재사용 가능한 업무 정보가 포함되어 있습니다.")
    if candidate.get("classification") == "UPDATE_CANDIDATE":
        st.markdown("#### ✏️ 기존 정보와 다른 내용이 감지되었습니다")
        if candidate.get("existing_fact"):
            st.caption("기존 정보")
            st.write(candidate["existing_fact"])
        st.caption("새로운 정보")
    elif candidate.get("classification") == "NEW_INFORMATION":
        st.markdown("#### 💡 새로운 조직 정보가 감지되었습니다")
    st.markdown(f"**{candidate['title']}**")
    st.write(candidate["summary"])
    if candidate.get("conflict_note"):
        st.warning("기존 기록과의 차이: " + candidate["conflict_note"])
    if exchange.get("editing_candidate"):
        edited = st.text_area("기억 후보 내용", candidate["summary"], key=f"candidate-edit-{index}")
        save_col, cancel_col = st.columns(2)
        if save_col.button("수정 후 저장", key=f"candidate-edit-save-{index}", type="primary"):
            save_from_chat(exchange, candidate, edited.strip(), edited=True)
            persist_rendered_exchange(index, exchange)
            st.rerun()
        if cancel_col.button("수정 취소", key=f"candidate-edit-cancel-{index}"):
            exchange["editing_candidate"] = False
            persist_rendered_exchange(index, exchange)
            st.rerun()
        return
    save_col, edit_col, discard_col = st.columns(3)
    if save_col.button("저장", key=f"candidate-save-{index}", type="primary"):
        save_from_chat(exchange, candidate, candidate["summary"])
        persist_rendered_exchange(index, exchange)
        st.rerun()
    if edit_col.button("수정", key=f"candidate-edit-{index}"):
        exchange["editing_candidate"] = True
        persist_rendered_exchange(index, exchange)
        st.rerun()
    if discard_col.button("저장하지 않음", key=f"candidate-discard-{index}"):
        exchange["candidate_action"] = "discarded"
        persist_rendered_exchange(index, exchange)
        st.rerun()


def render_exchange(exchange, index):
    with st.chat_message("user"):
        st.write(exchange["question"])
    with st.chat_message("assistant"):
        cited = set(exchange["answer"].get("citations", []))
        sources = [item for item in exchange["documents"] if item["document_id"] in cited]
        st.markdown(exchange["answer"]["answer"])
        if sources:
            st.markdown("##### 관련 문서·근거")
            for item in sources:
                with st.expander(item["title"]):
                    st.markdown(highlight_html(item["excerpt"], exchange["terms"]), unsafe_allow_html=True)
                    if item["source_drive_url"]:
                        st.link_button("Google Drive에서 원문 보기", item["source_drive_url"])
        for caveat in exchange["answer"].get("caveats", []):
            st.caption(caveat)
        render_candidate(exchange, index)


for index, exchange in enumerate(st.session_state.history):
    render_exchange(exchange, index)

question = st.chat_input("궁금한 내용을 질문하세요")
if question and question.strip():
    total_started = time.perf_counter()
    question = question.strip()
    request_session_id = st.session_state.session_id
    create_session(con, request_session_id, question, st.session_state.project_context)
    st.query_params["chat"] = request_session_id
    print(f"[QUERY] {question}")
    preprocess_elapsed = time.perf_counter() - total_started
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        search_status = st.empty()
        search_status.info("관련 문서를 찾고 있습니다...")
        search_started = time.perf_counter()
        terms = expand_query(question)
        project_context = st.session_state.project_context
        direct_project_list = is_active_project_list_question(question)
        direct_statement = False
        statement_candidate = None
        registry_active_projects = load_active_projects(con)
        title_matches = [] if direct_project_list else find_documents_by_title(con, question)
        scope = project_context.get("active_project_scope") or []
        active_entity = project_context.get("active_entity")
        explicit = explicit_project(registry_active_projects, question)
        inferred_current = False
        scoped_search = False
        scoped_fell_back = False
        rewrite_elapsed = None

        if is_fact_statement(question):
            project_match = re.search(r"(?<![A-Z0-9])U-?\d{2}(?!\d)", question, re.I)
            statement_project_id = (
                project_match.group(0).upper().replace("U", "U-").replace("--", "-")
                if project_match else (active_entity or {}).get("project_id", "")
            )
            statement_contexts, cache_hit = search_documents(
                con, question, terms=terms, return_metadata=True,
                allowed_project_ids=[statement_project_id] if statement_project_id else None,
            )
            statement_result = assess_statement(question, statement_contexts, statement_project_id)
            direct_statement = statement_result["classification"] != "QUESTION"
            statement_candidate = statement_result.get("candidate")
            documents = [] if statement_candidate else statement_contexts
            rewrite_elapsed = None
            if statement_candidate:
                project_context["unverified_user_facts"].append({
                    "project_id": statement_candidate["project_id"],
                    "content": statement_candidate["summary"],
                    "verification": "unverified_user_statement",
                })
                heading = (
                    "기존 정보와 다른 내용이 감지되었습니다."
                    if statement_result["classification"] == "UPDATE_CANDIDATE"
                    else "새로운 조직 정보를 확인했어요."
                )
                answer = {
                    "answer": heading + "\n\n현재 연결된 문서를 기준으로 조직기억 후보 등록 여부를 선택해 주세요.",
                    "citations": [], "caveats": ["검토 승인 전까지 공식 조직기억으로 사용하지 않습니다."],
                }
            else:
                answer = {
                    "answer": "해당 내용은 기존 승인 문서에서 이미 확인되는 정보입니다.",
                    "citations": [item["document_id"] for item in documents[:2]], "caveats": [],
                }
            print(f"[MEMORY] statement classification={statement_result['classification']}")
        elif direct_project_list:
            print("[INTENT] type=active_project_list")
            print("[PROJECT_CONTEXT] active project intent detected")
            print("[PROJECT_CONTEXT] status filter: 진행중")
            scope = load_active_projects(con)
            project_context["active_project_scope"] = scope
            project_context["active_entity"] = None
            print(f"[PROJECT_CONTEXT] active projects: {len(scope)}")
            print("[PROJECT_CONTEXT] scope saved to session")
            documents = []
            cache_hit = False
            answer = {"answer": active_project_answer(scope), "citations": [], "caveats": []}
        else:
            if title_matches:
                matched = title_matches[0]
                print("[TITLE_MATCH] exact=true")
                print(f"[TITLE_MATCH] matched_title={matched['title']}")
                print(f"[TITLE_MATCH] document_id={matched['document_id']}")
                active_entity = {
                    "type": "project", "name": matched["title"],
                    "document_id": matched["document_id"],
                    "search_document_id": matched["document_id"],
                    "project_id": matched.get("project_id", ""), "status": "",
                }
                project_context["active_entity"] = active_entity
            if explicit:
                active_entity = explicit
                project_context["active_entity"] = explicit
                print(f"[PROJECT_CONTEXT] active entity changed: {explicit['name']}")
            elif active_entity:
                print(f"[PROJECT_CONTEXT] follow-up uses active_entity: {active_entity['name']}")
            elif scope and is_followup_question(question):
                print("[PROJECT_CONTEXT] follow-up uses active_project_scope")
                print(f"[PROJECT_CONTEXT] scope size: {len(scope)}")
                print(f"[PROJECT_CONTEXT] query: {question}")
            elif is_current_project_question(question):
                inferred_current = True
                print("[PROJECT_CONTEXT] no active session entity")
                print("[PROJECT_CONTEXT] inferred current-project question: true")
                print("[PROJECT_CONTEXT] loading active documents from registry")
                scope = load_active_projects(con)
                project_context["active_project_scope"] = scope
                print(f"[PROJECT_CONTEXT] active docs: {len(scope)}")

            selected_scope = [explicit or active_entity] if (explicit or active_entity) else (
                scope if (inferred_current or (scope and is_followup_question(question))) else []
            )
            allowed_projects = project_ids(selected_scope)
            title_document_ids = [item["document_id"] for item in title_matches]
            manual_only = (
                is_manual_question(question)
                and not selected_scope
                and not title_document_ids
                and not re.search(r"(?<![A-Z0-9])U-?\d{2}(?!\d)", question, re.I)
            )
            scoped_search = bool(allowed_projects or title_document_ids)
            documents, cache_hit = search_documents(
                con, question, terms=terms, return_metadata=True,
                allowed_document_ids=title_document_ids or None,
                allowed_project_ids=None if title_document_ids else (allowed_projects or None),
                force_document_scope=bool(title_document_ids),
                foundation_only=manual_only,
            )
            if scoped_search and not title_document_ids and (
                not documents or documents[0]["score"] < ACTIVE_PROJECT_SEARCH_THRESHOLD
            ):
                scoped_fell_back = True
                print("[PROJECT_CONTEXT] active-project confidence too low")
                print("[SEARCH] fallback to global hybrid search")
                documents, cache_hit = search_documents(
                    con, question, terms=terms, return_metadata=True
                )

            if selected_scope and not active_entity:
                entity, confidence, ambiguous = select_entity_from_results(selected_scope, documents)
                print(f"[PROJECT_CONTEXT] confidence: {confidence:.2f}")
                if entity:
                    project_context["active_entity"] = entity
                    print(f"[PROJECT_CONTEXT] best project: {entity['name']}")
                    print("[PROJECT_CONTEXT] active entity saved")
                elif ambiguous and len(selected_scope) > 1:
                    print("[PROJECT_CONTEXT] project selection ambiguous; keeping scope")

            rewrite_elapsed = None
            if not documents or documents[0]["score"] < SEARCH_CONFIDENCE_THRESHOLD:
                rewrite_started = time.perf_counter()
                terms = predict_search_terms(question, terms)
                rewrite_elapsed = time.perf_counter() - rewrite_started
                retry_started = time.perf_counter()
                current_entity = project_context.get("active_entity")
                retry_scope = project_ids([current_entity]) if current_entity else (
                    allowed_projects if scoped_search and not scoped_fell_back else []
                )
                documents, retry_cache_hit = search_documents(
                    con, question, terms=terms, return_metadata=True,
                    allowed_document_ids=title_document_ids or None,
                    allowed_project_ids=None if title_document_ids else (retry_scope or None),
                    force_document_scope=bool(title_document_ids),
                    foundation_only=manual_only,
                )
                search_elapsed = time.perf_counter() - search_started
                cache_hit = cache_hit or retry_cache_hit

            project_context["recent_document_ids"] = [
                item["document_id"] for item in documents[:5]
            ]
        search_elapsed = time.perf_counter() - search_started
        if documents:
            search_status.success("관련 문서를 찾았습니다.")
        elif direct_project_list and scope:
            search_status.success("문서관리대장에서 진행 중인 항목을 확인했습니다.")
        else:
            search_status.warning("관련 문서를 찾지 못했습니다.")
        if documents:
            print(f"[SEARCH] scope_documents={len(documents)}")
            print(f"[SEARCH] top_score={documents[0]['score']:.2f}")
            for item in documents:
                chunk_count = con.execute(
                    "SELECT count(*) FROM document_chunks WHERE document_id=?",
                    (item["document_id"],),
                ).fetchone()[0]
                print(f"[SEARCH] matched document_id: {item['document_id']}")
                print(f"[SEARCH] indexed chunk count for document: {chunk_count}")
                if chunk_count == 0:
                    print("[SEARCH] ERROR: document exists but has no indexed chunks")
        answer_status = st.empty()
        if direct_project_list or direct_statement:
            context_elapsed = 0.0
            generation_elapsed = 0.0
        else:
            context_started = time.perf_counter()
            recent = st.session_state.history[-2:]
            conversation_context = "\n".join(
                f"사용자: {item['question']}\nAI: {item['answer']['answer'][:500]}" for item in recent
            )
            unverified = project_context.get("unverified_user_facts", [])[-3:]
            if unverified:
                conversation_context += "\n\n사용자가 제공한 미검증 정보(공식 사실로 표현 금지):\n" + "\n".join(
                    f"- {item['content']}" for item in unverified
                )
            context_elapsed = time.perf_counter() - context_started
            answer_status.info("AI가 내용을 정리하고 있습니다...")
            generation_started = time.perf_counter()
            active_projects = load_active_projects(con)
            answer_project_id = in_progress_project_id(
                active_projects,
                (project_context.get("active_entity") or {}).get("project_id", ""),
                documents,
            )
            active_project = bool(answer_project_id)
            active_result = active_project and is_result_question(question)
            answer = (
                in_progress_result_answer(answer_project_id, documents)
                if active_result else generate(
                    question, documents, conversation_context=conversation_context,
                    project_status="진행중" if active_project else "",
                )
            )
            generation_elapsed = time.perf_counter() - generation_started
            print("[ANSWER] qwen_generation=true")
        answer_status.empty()
        st.markdown(answer["answer"])
        if documents:
            st.markdown("##### 관련 문서·근거")
            for item in documents[:3]:
                with st.expander(item["title"]):
                    st.markdown(highlight_html(item["excerpt"], terms), unsafe_allow_html=True)
                    if item["source_drive_url"]:
                        st.link_button("Google Drive에서 원문 보기", item["source_drive_url"])
        for caveat in answer.get("caveats", []):
            st.caption(caveat)

    with st.spinner("대화 기록을 정리하고 있습니다..."):
        project_id = (
            (statement_candidate or {}).get("project_id", "")
            or next((item.get("project_id") for item in documents if item.get("project_id")), "")
        )
        user_message = con.execute(
            "INSERT INTO conversations(project_id,role,speaker,message,session_id) VALUES(?,?,'user',?,?)",
            (project_id, "member", question, request_session_id),
        ).lastrowid
        assistant_message = con.execute(
            "INSERT INTO conversations(project_id,role,speaker,message,session_id) VALUES(?,?,'assistant',?,?)",
            (project_id, "assistant", answer["answer"], request_session_id),
        ).lastrowid
        con.commit()
        candidate = statement_candidate if direct_statement else (
            None if direct_project_list else assess_candidate(question, documents)
        )
        if candidate and not candidate["project_id"]:
            candidate = None
    exchange = {
        "question": question, "terms": terms, "documents": documents, "answer": answer,
        "candidate": candidate, "conversation_ids": (user_message, assistant_message),
    }
    position = len(st.session_state.history)
    save_exchange(con, request_session_id, position, exchange, project_context)
    if st.session_state.session_id == request_session_id:
        st.session_state.history.append(exchange)
    total_elapsed = time.perf_counter() - total_started
    print(f"[PERF] preprocess: {preprocess_elapsed:.3f}s")
    print(f"[PERF] search: {search_elapsed:.3f}s")
    print("[PERF] query_rewrite: skipped" if rewrite_elapsed is None else f"[PERF] query_rewrite: {rewrite_elapsed:.3f}s")
    print(f"[PERF] context_build: {context_elapsed:.3f}s")
    print(f"[PERF] qwen_generation: {generation_elapsed:.3f}s")
    print(f"[PERF] total: {total_elapsed:.3f}s")
    print(f"[CACHE] search cache {'HIT' if cache_hit else 'MISS'}")
    st.rerun()
