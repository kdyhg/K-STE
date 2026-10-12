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


class OutputAndBidirectionalTests(unittest.TestCase):
    def test_input_default_ignores_ai_explanation(self):
        source = "## 기술 설명\n이것은 무조건 빠릅니다.\n## 작업 요구사항\n이거 수정해 줘.\n"
        result = lint(source, {"requirements"})
        self.assertEqual(result["selected_lines"], 1)
        self.assertEqual({f["direction"] for f in result["findings"]}, {"input"})

    def test_output_technical_section(self):
        source = "## 작업 요구사항\n이거 수정해 줘.\n## 기술 설명\n이것은 무조건 빠릅니다.\n"
        result = lint(source, {"technical"}, direction="output")
        self.assertEqual(result["selected_lines"], 1)
        self.assertEqual({f["rule"] for f in result["findings"]},
                         {"vague_reference", "unqualified_certainty"})
        self.assertEqual({f["line"] for f in result["findings"]}, {4})

    def test_output_learning_section(self):
        source = "## 학습 설명\n이것은 조건을 살펴봐야 합니다.\n## 오류 설명\n무조건 서버 탓입니다.\n"
        result = lint(source, {"learning"}, direction="output")
        self.assertEqual(result["selected_lines"], 1)
        self.assertEqual({f["line"] for f in result["findings"]}, {2})

    def test_output_error_section(self):
        source = "## 오류 원인\n서버가 무조건 원인입니다.\n"
        result = lint(source, {"error"}, direction="output")
        self.assertEqual(result["findings"][0]["rule"], "unqualified_certainty")

    def test_output_summary_section(self):
        source = "## 요약\n그것은 100% 해결됩니다.\n"
        result = lint(source, {"summary"}, direction="output")
        self.assertEqual(result["selected_lines"], 1)
        self.assertEqual(len(result["findings"]), 2)

    def test_output_marker_explicit_direction(self):
        source = (
            "이거는 범위 밖입니다.\n"
            "<!-- kste:start scope=technical direction=output -->\n"
            "이것은 항상 옳습니다.\n"
            "<!-- kste:end -->\n"
            "이것도 범위 밖입니다.\n"
        )
        result = lint(source, {"technical"}, direction="output")
        self.assertEqual(result["selected_lines"], 1)
        self.assertEqual({f["line"] for f in result["findings"]}, {3})

    def test_output_marker_without_direction_is_inferred(self):
        source = "<!-- kste:start scope=learning -->\n이것을 생각합니다.\n<!-- kste:end -->\n"
        self.assertEqual(lint(source, {"learning"}, direction="output")["selected_lines"], 1)

    def test_both_selects_only_requested_sides(self):
        source = (
            "## 작업 요구사항\n이거 수정해 줘.\n"
            "## 제약 조건\n그거는 그대로 두세요.\n"
            "## 기술 설명\n이것은 무조건 맞습니다.\n"
            "## 오류 설명\n원인을 확인했습니다.\n"
        )
        result = lint(source, {"input:constraints", "output:technical"}, direction="both")
        self.assertEqual(result["selected_lines"], 2)
        self.assertEqual({f["line"] for f in result["findings"]}, {4, 6})
        self.assertEqual({f["direction"] for f in result["findings"]}, {"input", "output"})

    def test_both_rejects_unqualified_scopes(self):
        with self.assertRaisesRegex(ValueError, "양방향 검사"):
            lint("## 작업 요구사항\n이거 수정해 줘.\n", {"requirements"}, direction="both")

    def test_both_rejects_all(self):
        with self.assertRaisesRegex(ValueError, "양방향 전체 검사"):
            lint("## 요약\n이것입니다.\n", set(), all_text=True, direction="both")

    def test_output_rejects_input_scope(self):
        with self.assertRaises(ValueError):
            lint("## 작업 요구사항\n이거 수정해 줘.\n",
                 {"requirements"}, direction="output")

    def test_output_ignores_code_fences(self):
        source = "## 기술 설명\n\x60\x60\x60python\n이것은 무조건입니다.\n\x60\x60\x60\n이것은 맞습니다.\n"
        self.assertEqual(lint(source, {"technical"}, direction="output")["selected_lines"], 1)

    def test_cli_output_mode(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kste_lint.py"),
             "--direction", "output", "--scope", "technical", "--format", "json"],
            input="## 기술 설명\n이것은 항상 정답입니다.\n",
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"unqualified_certainty"', proc.stdout)
        self.assertIn('"direction": "output"', proc.stdout)

    def test_cli_both_scope(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kste_lint.py"),
             "--direction", "both",
             "--scope", "input:constraints,output:error", "--format", "json"],
            input="## 제약 조건\n그거 유지해 줘.\n## 오류 설명\n무조건 서버 문제입니다.\n",
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('"selected_lines": 2', proc.stdout)

    def test_cli_both_without_qualified_scope_returns_two(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kste_lint.py"),
             "--direction", "both", "--scope", "requirements"],
            input="## 작업 요구사항\n이거 수정해 줘.\n",
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 2)

    def test_cli_both_all_returns_two(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "kste_lint.py"),
             "--direction", "both", "--all"],
            input="## 요약\n그것을 확인합니다.\n",
            text=True, capture_output=True,
        )
        self.assertEqual(proc.returncode, 2)



if __name__ == "__main__":
    unittest.main()
