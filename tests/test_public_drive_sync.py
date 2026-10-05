import unittest
from unittest.mock import patch

from services.public_drive_sync import _discover_drive_files


class PublicDriveSyncTests(unittest.TestCase):
    def test_discovers_registry_manuals_and_project_files_recursively(self):
        pages = {
            "ROOT": [
                {"id": "registry", "name": "ML_문서관리대장", "mimeType": "application/vnd.google-apps.spreadsheet", "webViewLink": "https://docs.google.com/spreadsheets/d/registry/edit"},
                {"id": "manuals", "name": "표준 업무 매뉴얼", "mimeType": "application/vnd.google-apps.folder"},
                {"id": "projects", "name": "프로젝트", "mimeType": "application/vnd.google-apps.folder"},
            ],
            "manuals": [
                {"id": "manual", "name": "01 전사 공통 업무 매뉴얼", "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://docs.google.com/document/d/manual/edit"},
                {"id": "renamed-doc", "name": "U-01_회의록.docx", "mimeType": "application/vnd.google-apps.document", "webViewLink": "https://docs.google.com/document/d/renamed-doc/edit"},
            ],
            "projects": [
                {"id": "project", "name": "U-01 행사", "mimeType": "application/vnd.google-apps.folder"},
            ],
            "project": [
                {"id": "plan", "name": "U-01_기획안.docx", "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "webViewLink": "https://drive.google.com/file/d/plan/view"},
            ],
        }

        with patch("services.public_drive_sync._list_drive_folder", side_effect=lambda folder_id, _: pages[folder_id]):
            files = _discover_drive_files("ROOT", "token")

        self.assertEqual(
            {
                ("ML_문서관리대장.csv", "_registry", "registry"),
                ("01 전사 공통 업무 매뉴얼.txt", "_manuals", "manual"),
                ("U-01_회의록.txt", "_manuals", "renamed-doc"),
                ("U-01_기획안.docx", "프로젝트", "plan"),
            },
            {(item["file_name"], item["bucket"], item["file_id"]) for item in files},
        )


if __name__ == "__main__":
    unittest.main()
