#!/usr/bin/env python3
"""K-STE: scope-aware Korean input and output clarity linter.

This linter only returns advisory signals. It never rewrites user text.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

INPUT_SCOPES = ("requirements", "constraints", "output", "process", "explanation")
OUTPUT_SCOPES = ("technical", "learning", "error", "summary")
SCOPES = INPUT_SCOPES  # Backward compatibility with the original input-only API.

INPUT_TITLES = {
    "requirements": ("작업 요구사항", "요구사항", "기능 요구사항", "필수 기능", "구현할 기능"),
    "constraints": ("제약 조건", "제약조건", "변경 금지", "변경금지", "주의 사항", "주의사항"),
    "output": ("결과물 형식", "출력 형식", "제출 형식", "결과물", "출력형식"),
    "process": ("작업 순서", "진행 순서", "작업 절차", "진행순서", "단계"),
    "explanation": ("배경 설명", "참고 사항", "설명", "배경", "참고"),
}
OUTPUT_TITLES = {
    "technical": ("기술 설명", "기술적 설명", "기술 답변", "개념 설명"),
    "learning": ("학습 설명", "교육 설명", "수업 설명", "학습 답변", "풀이 설명"),
    "error": ("오류 설명", "오류 원인", "오류 분석", "에러 설명", "문제 원인"),
    "summary": ("응답 요약", "결과 요약", "설명 요약", "핵심 정리", "요약"),
}
HEAD = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
START = re.compile(
    r"^\s*<!--\s*kste:start\s+scope=([a-z]+)(?:\s+direction=(input|output))?\s*-->\s*$"
)
END = re.compile(r"^\s*<!--\s*kste:end\s*-->\s*$")
FENCE = re.compile(r"^\s*(?:\x60{3,}|~{3,})")
BULLET = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
INPUT_VAGUE = re.compile(r"이거|저거|그거|대충|알아서|적당히|알맞게|깔끔하게|예쁘게")
ACTION_CHAIN = re.compile(r"(?:하고|한 뒤|한 다음|하고 나서).*(?:하고|한 뒤|한 다음|하고 나서)")
BARE_EDIT = re.compile(r"^(?:그냥\s*)?(?:수정|변경|고쳐|처리|정리)해\s*(?:줘|주세요|주십시오)[.!?\s]*$")
OUTPUT_VAGUE = re.compile(r"이거|그거|저거|이것|그것|저것|이 부분|그 부분|해당 내용|등등")
OVERCLAIM = re.compile(r"항상|무조건|절대로|틀림없이|100\s*%|확실하게")
HEDGE_STACK = re.compile(r"(?:아마도?|어쩌면).{0,60}(?:일 수도|가능성이|것 같|추정)")


def _normalized(title: str) -> str:
    return re.sub(r"[\s\-*:\x60]", "", title)


def classify_heading(title: str, direction: str = "input") -> str | None:
    """Return unqualified section key for one direction, as in the old API."""
    candidates = INPUT_TITLES if direction == "input" else OUTPUT_TITLES
    name = _normalized(title)
    for scope, choices in candidates.items():
        if name in {_normalized(x) for x in choices}:
            return scope
    return None


def _scope_key(scope: str, declared: str | None = None) -> str:
    """Resolve explicit markers; reject invalid or ambiguous names."""
    allowed = []
    if scope in INPUT_SCOPES:
        allowed.append("input")
    if scope in OUTPUT_SCOPES:
        allowed.append("output")
    if declared:
        if declared not in allowed:
            raise ValueError(f"'{declared}' 방향에 유효하지 않은 영역: {scope}")
        return f"{declared}:{scope}"
    if len(allowed) != 1:
        raise ValueError(f"알 수 없는 영역 '{scope}'" if not allowed else f"모호한 영역 '{scope}'")
    return f"{allowed[0]}:{scope}"


def _heading_key(title: str, direction: str) -> str | None:
    if direction in ("input", "both"):
        key = classify_heading(title, "input")
        if key:
            return f"input:{key}"
    if direction in ("output", "both"):
        key = classify_heading(title, "output")
        if key:
            return f"output:{key}"
    return None


def _wanted_keys(wanted: set[str], direction: str) -> set[str]:
    keys = set()
    for item in wanted:
        if ":" in item:
            explicit_direction, scope = item.split(":", 1)
            if explicit_direction not in ("input", "output"):
                raise ValueError(f"잘못된 방향: {explicit_direction}")
            key = _scope_key(scope, explicit_direction)
        else:
            if direction == "both":
                raise ValueError("양방향 검사에는 input:requirements,output:technical 형식이 필요합니다.")
            key = _scope_key(item, direction)
        if direction != "both" and not key.startswith(f"{direction}:"):
            raise ValueError(f"선택 방향({direction})과 범위({item})가 일치하지 않습니다.")
        keys.add(key)
    return keys


def _section_lines(source: str, wanted: set[str], all_text: bool, direction: str):
    if direction not in ("input", "output", "both"):
        raise ValueError(f"알 수 없는 방향: {direction}")
    keys = _wanted_keys(wanted, direction)
    if all_text and direction == "both":
        raise ValueError("양방향 전체 검사는 지원하지 않습니다. 각 방향에서 범위를 지정하세요.")

    stack: list[tuple[int, str | None]] = []
    explicit: str | None = None
    in_fence = False
    selected: list[tuple[int, str, str]] = []
    for number, line in enumerate(source.splitlines(), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        start = START.match(line)
        if start:
            if explicit is not None:
                raise ValueError(f"{number}행: 구간 시작 표식이 중첩되었습니다.")
            try:
                explicit = _scope_key(start.group(1), start.group(2))
            except ValueError as error:
                raise ValueError(f"{number}행: {error}") from error
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
            stack.append((level, _heading_key(heading.group(2), direction)))
            continue

        if not line.strip():
            continue
        active = explicit if explicit is not None else next(
            (scope for _, scope in reversed(stack) if scope is not None), None
        )
        if all_text:
            selected.append((number, line, direction))
        elif active in keys:
            selected.append((number, line, active.split(":", 1)[0]))

    if explicit is not None:
        raise ValueError("구간 종료 표식이 없습니다.")
    return selected


def selected_lines(source: str, wanted: set[str], all_text: bool = False,
                   direction: str = "input") -> list[tuple[int, str]]:
    """Return 1-based line numbers and content. Defaults retain the input-only API."""
    return [(n, text) for n, text, _ in _section_lines(source, wanted, all_text, direction)]


def lint(source: str, scopes: set[str], all_text: bool = False, strict: bool = False,
         direction: str = "input") -> dict:
    selected = _section_lines(source, scopes, all_text, direction)
    findings = []
    for number, line, current_direction in selected:
        body = BULLET.sub("", line).strip()
        long_limit = 90 if strict else 130
        if current_direction == "output":
            signals = (
                ("vague_reference", OUTPUT_VAGUE.search(body),
                 "설명에서 지칭 대상이 분명한지 확인하세요."),
                ("unqualified_certainty", OVERCLAIM.search(body),
                 "단정 표현을 뒷받침할 근거와 적용 범위가 있는지 확인하세요."),
                ("stacked_uncertainty", HEDGE_STACK.search(body),
                 "가능성 표현이 여러 번 나타납니다. 근거 수준을 보존하며 명확성을 검토하세요."),
                ("long_sentence", len(body) > long_limit,
                 "설명의 문장이 길어 핵심 개념이나 조건이 흐려질 수 있습니다."),
            )
        else:
            signals = (
                ("vague_expression", INPUT_VAGUE.search(body),
                 "지시 대상 또는 완료 기준이 모호할 수 있습니다."),
                ("multiple_actions", ACTION_CHAIN.search(body),
                 "한 문장에 여러 작업이 연결되어 있습니다. 순서를 유지해 분리를 검토하세요."),
                ("missing_target", BARE_EDIT.search(body),
                 "수정 대상이 문장에 없습니다. 주변 문맥에서 확인하세요."),
                ("long_sentence", len(body) > long_limit,
                 "문장이 길어 조건과 작업을 구분하기 어려울 수 있습니다."),
            )
        for rule, hit, message in signals:
            if hit:
                findings.append({
                    "line": number,
                    "direction": current_direction,
                    "rule": rule,
                    "level": "advisory",
                    "message": message,
                    "text": body,
                })
    return {"selected_lines": len(selected), "direction": direction, "findings": findings}


def main(argv=None):
    parser = argparse.ArgumentParser(description="지정한 한국어 입력·출력 영역만 점검합니다.")
    parser.add_argument("file", nargs="?", help="UTF-8 텍스트 또는 Markdown. 생략하면 표준 입력")
    parser.add_argument("--direction", choices=("input", "output", "both"), default="input",
                        help="입력 지시, AI 설명, 양방향 (기본: input)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--scope", help="범위 코드. 양방향이면 input:...,output:... 형태")
    group.add_argument("--all", action="store_true", help="선택한 한 방향의 문서 전체를 검사")
    parser.add_argument("--strict", action="store_true", help="긴 문장 경고 임계값 낮추기")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--fail-on-warnings", action="store_true")
    args = parser.parse_args(argv)

    try:
        scopes = {part.strip() for part in args.scope.split(",") if part.strip()} if args.scope else set()
        if not args.all and not scopes:
            parser.error("하나 이상의 영역을 지정하세요.")
        if args.all and args.direction == "both":
            parser.error("--direction both와 --all은 함께 사용할 수 없습니다.")
        source = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
        result = lint(source, scopes, all_text=args.all, strict=args.strict,
                      direction=args.direction)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"K-STE 오류: {exc}", file=sys.stderr)
        return 2

    if result["selected_lines"] == 0:
        print("K-STE 오류: 선택한 영역을 찾지 못했습니다. 전체 검사는 --all로 명시하세요.", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"검사 방향: {args.direction} / 검사한 줄: {result['selected_lines']} / 검토 신호: {len(result['findings'])}")
        for item in result["findings"]:
            print(f"{item['line']}행 [{item['direction']}:{item['rule']}] {item['message']} {item['text']}")
    return 1 if args.fail_on_warnings and result["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
