"""Regression tests for selective Korean instruction linting."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from kste_lint import lint, selected_lines  # noqa: E402


class ScopeTests(unittest.TestCase):
    def test_only_selected_heading(self):
        source = (
            "# 요청\n이거 수정해 줘\n"
            "## 작업 요구사항\n이거 적당히 고쳐 줘\n"
            "## 배경 설명\n대충 정리해 줘\n"
        )
        result = lint(source, {"requirements"})
        self.assertEqual(result["selected_lines"], 1)
        self.assertEqual({x["line"] for x in result["findings"]}, {4})

    def test_two_selected_sections(self):
        source = (
            "## 작업 요구사항\n이거 수정해 줘\n"
            "## 제약 조건\n기존 데이터는 삭제하지 않는다.\n"
            "## 설명\n그거는 배경이다.\n"
        )
        lines = selected_lines(source, {"requirements", "constraints"})
        self.assertEqual([n for n, _ in lines], [2, 4])

    def test_explicit_markers(self):
        source = (
            "이거는 건드리지 마.\n"
            "<!-- kste:start scope=constraints -->\n"
            "그거는 변경하지 않는다.\n"
            "<!-- kste:end -->\n"
            "대충 해 줘.\n"
        )
        result = lint(source, {"constraints"})
        self.assertEqual(result["selected_lines"], 1)
        self.assertEqual(result["findings"][0]["line"], 3)

    def test_fenced_code_is_not_linted(self):
        source = (
            "## 작업 요구사항\n"
            "```text\n이거 수정해 줘\n```\n"
            "정확한 파일을 수정한다.\n"
        )
        self.assertEqual(lint(source, {"requirements"})["selected_lines"], 1)

    def test_nested_heading_inherits_scope(self):
        source = "## 작업 요구사항\n### 화면\n이거 수정해 줘\n## 설명\n그거는 그대로.\n"
        self.assertEqual([n for n, _ in selected_lines(source, {"requirements"})], [3])

    def test_unknown_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, "알 수 없는 영역"):
            selected_lines("<!-- kste:start scope=other -->\n내용\n<!-- kste:end -->", {"requirements"})

    def test_unmatched_marker_rejected(self):
        with self.assertRaises(ValueError):
            selected_lines("<!-- kste:start scope=requirements -->\n내용", {"requirements"})

    def test_multiple_actions_advisory(self):
        source = "## 작업 요구사항\n파일을 확인하고 수정한 뒤 배포한다.\n"
        self.assertIn("multiple_actions", [x["rule"] for x in lint(source, {"requirements"})["findings"]])

    def test_unselected_scope_yields_empty(self):
        source = "## 설명\n이거 수정해 줘.\n"
        self.assertEqual(lint(source, {"requirements"})["selected_lines"], 0)

    def test_all_opt_in(self):
        source = "## 설명\n이거 수정해 줘.\n"
        self.assertEqual(lint(source, set(), all_text=True)["selected_lines"], 1)

    def test_cli_json(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kste_lint.py"),
             "--scope", "requirements", "--format", "json"],
            input="## 작업 요구사항\n이거 수정해 줘\n",
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"vague_expression"', proc.stdout)

    def test_cli_missing_scope_returns_two(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kste_lint.py"),
             "--scope", "requirements"],
            input="## 설명\n그거 수정해 줘\n",
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()
