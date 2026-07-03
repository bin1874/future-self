#!/usr/bin/env python3
"""Health check for .future-self memory storage.

Usage:
  python3 scripts/lint_memory.py [root] [--today YYYY-MM-DD]

Exit codes:
  0 = no issues
  1 = issues found
"""

from __future__ import annotations

import argparse
import re
from datetime import date, datetime
from pathlib import Path


ENTRY_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) \| (场景A 行动前|场景B 行动后)$", re.M)
RAW_LOCATION_RE = re.compile(r"^- 原始会话位置: raw-conversations/(\d{4}-\d{2})\.md#(\d{4}-\d{2}-\d{2}-\d{2}-\d{2})$", re.M)
RAW_LOCATION_LINE_RE = re.compile(r"^- 原始会话位置: .+$", re.M)
MALFORMED_ENTRY_HEAD_RE = re.compile(r"^### .*(场景A|场景B|行动前|行动后).*$", re.M)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--today", default=None, help="YYYY-MM-DD; defaults to local date")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    try:
        today = date.fromisoformat(args.today) if args.today else date.today()
    except ValueError as exc:
        raise ValueError("--today must use format YYYY-MM-DD") from exc
    issues = lint(root, today)
    if issues:
        print(f"\n{issues} issue(s) found")
        return 1
    print("Memory storage OK")
    return 0


def lint(root: Path, today: date) -> int:
    issues = 0
    memory_dir = root / ".future-self"
    profile = memory_dir / "profile.md"
    summary = memory_dir / "memory-summary.md"
    raw_dir = memory_dir / "raw-conversations"

    if not memory_dir.is_dir():
        print(f"ERROR: missing {memory_dir}")
        return 1
    if not raw_dir.is_dir():
        print(f"ERROR: missing {raw_dir}")
        issues += 1

    issues += check_file(profile, ["## 初始立场", "## 维护说明"])
    issues += check_file(summary, ["## 长期摘要", "## 近期行动索引"])
    if not summary.exists():
        return issues

    text = summary.read_text(encoding="utf-8")
    entries = list(ENTRY_RE.finditer(text))
    if len(entries) > 15:
        print(f"ERROR: 近期行动索引 has {len(entries)} entries; maximum is 15")
        issues += 1

    for match in entries:
        entry_date = date.fromisoformat(match.group(1))
        age_days = (today - entry_date).days
        if age_days > 14:
            print(f"ERROR: entry {match.group(1)} {match.group(2)} is {age_days} days old; should be folded into 长期摘要")
            issues += 1
        if age_days < 0:
            print(f"ERROR: entry {match.group(1)} {match.group(2)} is in the future relative to {today.isoformat()}")
            issues += 1

    issues += check_malformed_entry_heads(text)
    issues += check_raw_locations(memory_dir, text)
    issues += check_entry_fields(text)
    return issues


def check_file(path: Path, required_markers: list[str]) -> int:
    if not path.exists():
        print(f"ERROR: missing {path}")
        return 1
    text = path.read_text(encoding="utf-8")
    issues = 0
    for marker in required_markers:
        if marker not in text:
            print(f"ERROR: {path} missing marker: {marker}")
            issues += 1
    return issues


def check_raw_locations(memory_dir: Path, summary_text: str) -> int:
    issues = 0
    valid_lines = set(match.group(0) for match in RAW_LOCATION_RE.finditer(summary_text))
    for match in RAW_LOCATION_LINE_RE.finditer(summary_text):
        if match.group(0) not in valid_lines:
            print(f"ERROR: invalid raw log pointer format: {match.group(0)}")
            issues += 1
    for month, anchor in RAW_LOCATION_RE.findall(summary_text):
        if month != anchor[:7]:
            print(f"ERROR: raw log month {month} does not match anchor month {anchor[:7]}: {anchor}")
            issues += 1
        raw_file = memory_dir / "raw-conversations" / f"{month}.md"
        if not raw_file.exists():
            print(f"ERROR: summary points to missing raw log: {raw_file}")
            issues += 1
            continue
        raw_text = raw_file.read_text(encoding="utf-8")
        timestamp = anchor_to_timestamp(anchor)
        if f"## {timestamp}" not in raw_text:
            print(f"ERROR: raw log {raw_file} missing entry heading for {timestamp}")
            issues += 1
    return issues


def check_malformed_entry_heads(summary_text: str) -> int:
    issues = 0
    valid_heads = set(match.group(0) for match in ENTRY_RE.finditer(summary_text))
    for match in MALFORMED_ENTRY_HEAD_RE.finditer(summary_text):
        line = match.group(0)
        if line not in valid_heads:
            print(f"ERROR: malformed recent entry heading: {line}")
            issues += 1
    return issues


def check_entry_fields(summary_text: str) -> int:
    issues = 0
    chunks = re.split(r"(?=^### \d{4}-\d{2}-\d{2} \d{2}:\d{2} \| 场景[AB])", summary_text, flags=re.M)
    for chunk in chunks:
        if not chunk.startswith("### "):
            continue
        header = chunk.splitlines()[0]
        required = ["- 记录ID:", "- 用户输入摘要:", "- 原始会话位置:"]
        if "场景A" in header:
            required.extend(["- 回应给出的最小动作:", "- 后续是否被确认完成:"])
        elif "场景B" in header:
            required.extend(["- 呼应的历史记录:", "- 回应摘要:"])
        for marker in required:
            if marker not in chunk:
                print(f"ERROR: entry {header} missing field: {marker}")
                issues += 1
    return issues


def anchor_to_timestamp(anchor: str) -> str:
    anchor = anchor.strip().strip("[]")
    try:
        dt = datetime.strptime(anchor, "%Y-%m-%d-%H-%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        pass
    try:
        dt = datetime.strptime(anchor, "%Y-%m-%d %H:%M")
        return dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return anchor


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PermissionError, ValueError) as exc:
        print(f"错误: {exc}")
        raise SystemExit(1)
