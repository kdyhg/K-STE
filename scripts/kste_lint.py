#!/usr/bin/env python3
"""K-STE: Korean instruction text linter with explicit, selective scope."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCOPES = ("requirements", "constraints", "output", "process", "explanation")
TITLES = {
    "requirements": ("작업 요구사항", "요구사항", "기능 요구사항", "필수 기능", "구현할 기능"),
    "constraints": ("제약 조건", "제약조건", "변경 금지", "변경금지", "주의 사항", "주의사항"),
    "output": ("결과물 형식", "출력 형식", "제출 형식", "결과물", "출력형식"),
    "process": ("작업 순서", "진행 순서", "작업 절차", "진행순서", "단계"),
    "explanation": ("배경 설명", "참고 사항", "설명", "배경", "참고"),
}
HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
START = re.compile(r"^\s*<!--\s*kste:start\s+scope=([a-z]+)\s*-->\s*$")
END = re.compile(r"^\s*<!--\s*kste:end\s*-->\s*$")
FENCE = re.compile(r"^\s*(?:```|~~~)")
VAGUE = re.compile(r"이거|저거|그거|대충|알아서|적당히|알맞게|깔끔하게|예쁘게")
ACTION_CHAIN = re.compile(r"(?:하고|한 뒤|한 다음|하고 나서).*(?:하고|한 뒤|한 다음|하고 나서)")
BARE_EDIT = re.compile(r"^(?:[-*]\s*)?(?:그냥\s*)?(?:수정|변경|고쳐|처리|정리)해\s*(?:줘|주세요|주십시오)[.!?\s]*$")


def classify_heading(title: str) -> str | None:
    name = re.sub(r"[\s\-*:`]", "", title)
    for scope, choices in TITLES.items():
        if name in {re.sub(r"\s", "", x) for x in choices}:
            return scope
    return None


def selected_lines(source: str, wanted: set[str], all_text: bool = False):
    lines = source.splitlines()
    stack: list[tuple[int, str | None]] = []
    explicit: str | None = None
    in_fence = False
    found: list[tuple[int, str]] = []

    for number, line in enumerate(lines, 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        start = START.match(line)
        if start:
            if explicit is not None:
                raise ValueError(f"{number}행: 구간 시작 표식이 중첩되었습니다.")
            if start.group(1) not in SCOPES:
                raise ValueError(f"{number}행: 알 수 없는 영역 '{start.group(1)}'")
            explicit = start.group(1)
            continue
        if END.match(line):
            if explicit is None:
                raise ValueError(f"{number}행: 대응하는 시작 표식이 없습니다.")
            explicit = None
            continue

        heading = HEAD.match(line)
        if heading and explicit is None:
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, classify_heading(heading.group(2))))
            continue

        if not line.strip():
            continue

        active = explicit if explicit is not None else next(
            (scope for _, scope in reversed(stack) if scope is not None), None
        )
        if all_text or active in wanted:
            found.append((number, line))

    if explicit is not None:
        raise ValueError("구간 종료 표식이 없습니다.")
    return found


def lint(source: str, scopes: set[str], all_text: bool = False, strict: bool = False):
    lines = selected_lines(source, scopes, all_text)
    findings = []
    for number, line in lines:
        body = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", line).strip()
        signals = (
            ("vague_expression", VAGUE.search(body),
             "지시 대상 또는 완료 기준이 모호할 수 있습니다."),
            ("multiple_actions", ACTION_CHAIN.search(body),
             "한 문장에 여러 작업이 연결되어 있습니다. 순서를 유지해 분리를 검토하세요."),
            ("missing_target", BARE_EDIT.search(body),
             "수정 대상이 문장에 없습니다. 주변 문맥에서 확인하세요."),
            ("long_sentence", len(body) > (90 if strict else 130),
             "문장이 길어 조건과 작업을 구분하기 어려울 수 있습니다."),
        )
        for rule, match, message in signals:
            if match:
                findings.append({
                    "line": number,
                    "rule": rule,
                    "level": "advisory",
                    "message": message,
                    "text": body,
                })
    return {"selected_lines": len(lines), "findings": findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description="선택한 한국어 작업 지시 영역만 점검합니다.")
    parser.add_argument("file", nargs="?", help="UTF-8 텍스트 또는 Markdown 파일. 생략하면 표준 입력")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scope", help="쉼표로 구분한 영역 코드")
    group.add_argument("--all", action="store_true", help="문서 전체 검사(명시적 선택)")
    parser.add_argument("--strict", action="store_true", help="긴 문장 경고 임계값 낮추기")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--fail-on-warnings", action="store_true")
    args = parser.parse_args(argv)

    scopes = set()
    if args.scope:
        scopes = {part.strip() for part in args.scope.split(",") if part.strip()}
        invalid = scopes - set(SCOPES)
        if not scopes or invalid:
            parser.error(f"유효하지 않은 영역: {', '.join(sorted(invalid)) or '(없음)'}")
    try:
        source = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
        result = lint(source, scopes, all_text=args.all, strict=args.strict)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"K-STE 오류: {exc}", file=sys.stderr)
        return 2

    if result["selected_lines"] == 0:
        print("K-STE 오류: 선택한 영역을 찾지 못했습니다. 전체 검사는 --all로 명시하세요.", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"검사한 줄: {result['selected_lines']} / 검토 신호: {len(result['findings'])}")
        for item in result["findings"]:
            print(f"{item['line']}행 [{item['rule']}] {item['message']} {item['text']}")
    return 1 if args.fail_on_warnings and result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
