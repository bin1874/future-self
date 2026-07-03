#!/usr/bin/env python3
"""Append one future-self conversation to memory storage.

The model supplies semantic summaries. This script owns deterministic storage:
record ids, raw log append, recent index insertion, A/B completion backfill,
window checks, and structural validation hooks.

If recent entries need folding and --long-term-summary is not supplied, the
script prints fold candidates as JSON and exits with code 2 without writing.
Run it again with --long-term-summary to apply the write.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path


ENTRY_RE = re.compile(r"(?=^### \d{4}-\d{2}-\d{2} \d{2}:\d{2} \| 场景[AB])", re.M)
ENTRY_HEADER_RE = re.compile(r"^### (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) \| (场景A 行动前|场景B 行动后)$", re.M)
LONG_TERM_RE = re.compile(r"(## 长期摘要\n)(.*?)(\n---\n\n## 近期行动索引)", re.S)


@dataclass
class Entry:
    text: str
    timestamp: datetime
    record_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--scene", choices=["A", "B"], required=True)
    parser.add_argument("--user-input", required=True)
    parser.add_argument("--response", required=True)
    parser.add_argument("--user-summary", required=True)
    parser.add_argument("--response-summary", default="")
    parser.add_argument("--minimal-action", default="")
    parser.add_argument("--related-id", default="")
    parser.add_argument("--related-record", default="无")
    parser.add_argument("--long-term-summary", default="")
    parser.add_argument("--timestamp", default=None, help="YYYY-MM-DD HH:MM; defaults to local time")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    memory_dir = root / ".future-self"
    summary_path = memory_dir / "memory-summary.md"
    raw_dir = memory_dir / "raw-conversations"
    if not summary_path.exists():
        raise FileNotFoundError(f"missing {summary_path}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    set_private_directory(raw_dir)

    timestamp = parse_timestamp(args.timestamp)
    record_id = make_record_id(timestamp, args.scene, args.user_input, args.response)
    anchor = timestamp.strftime("%Y-%m-%d-%H-%M")
    month = timestamp.strftime("%Y-%m")

    summary_text = normalize_entry_ids(summary_path.read_text(encoding="utf-8"))
    new_entry = build_entry(args, timestamp, record_id, month, anchor)
    planned_summary = insert_entry(summary_text, new_entry)
    planned_summary = backfill_related_completion(planned_summary, args.related_id, args.related_record, record_id, timestamp)

    kept, folded = partition_entries(planned_summary, today=timestamp.date())
    if folded and not args.long_term_summary:
        print(json.dumps({"needs_fold": True, "fold_candidates": [entry_to_json(item) for item in folded]}, ensure_ascii=False, indent=2))
        return 2
    if folded:
        planned_summary = replace_entries(planned_summary, kept)
        planned_summary = replace_long_term_summary(planned_summary, args.long_term_summary)

    append_raw_log(
        raw_dir / f"{month}.md",
        timestamp=timestamp,
        scene=f"场景{args.scene}",
        writes_summary="是",
        related_record=args.related_id or args.related_record,
        user_input=args.user_input,
        response=args.response,
    )
    write_private(summary_path, planned_summary)
    print(json.dumps({"record_id": record_id, "raw_location": f"raw-conversations/{month}.md#{anchor}"}, ensure_ascii=False))
    return 0


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now().replace(second=0, microsecond=0)
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("--timestamp must use format YYYY-MM-DD HH:MM") from exc


def make_record_id(timestamp: datetime, scene: str, user_input: str, response: str) -> str:
    digest = hashlib.sha1(f"{timestamp.isoformat()}|{scene}|{user_input}|{response}".encode("utf-8")).hexdigest()[:6]
    return f"fs-{timestamp.strftime('%Y%m%d-%H%M')}-{digest}"


def make_existing_entry_record_id(timestamp: datetime, entry_text: str) -> str:
    digest = hashlib.sha1(f"{timestamp.isoformat()}|existing|{entry_text}".encode("utf-8")).hexdigest()[:6]
    return f"fs-{timestamp.strftime('%Y%m%d-%H%M')}-{digest}"


def neutralize_field(value: str, *, default: str = "未记录") -> str:
    value = value.strip() or default
    lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line.startswith(("#", "-", ">", "`")) or line == "---":
            line = "\\" + line
        lines.append(line)
    return " / ".join(lines) if lines else default


def build_entry(args: argparse.Namespace, timestamp: datetime, record_id: str, month: str, anchor: str) -> str:
    display_time = timestamp.strftime("%Y-%m-%d %H:%M")
    if args.scene == "A":
        return f"""### {display_time} | 场景A 行动前
- 记录ID: {record_id}
- 用户输入摘要: {neutralize_field(args.user_summary)}
- 原始会话位置: raw-conversations/{month}.md#{anchor}
- 回应给出的最小动作: {neutralize_field(args.minimal_action)}
- 后续是否被确认完成: 待确认
"""
    return f"""### {display_time} | 场景B 行动后
- 记录ID: {record_id}
- 用户输入摘要: {neutralize_field(args.user_summary)}
- 原始会话位置: raw-conversations/{month}.md#{anchor}
- 呼应的历史记录: {neutralize_field(args.related_id or args.related_record, default="无")}
- 回应摘要: {neutralize_field(args.response_summary or args.response)}
"""


def insert_entry(summary_text: str, entry: str) -> str:
    marker = "## 近期行动索引"
    marker_pos = summary_text.find(marker)
    if marker_pos == -1:
        raise ValueError("memory-summary.md missing ## 近期行动索引")
    insert_pos = summary_text.find("\n### ", marker_pos)
    if insert_pos == -1:
        return summary_text.rstrip() + "\n" + entry
    return summary_text[: insert_pos + 1] + entry + "\n" + summary_text[insert_pos + 1 :]


def backfill_related_completion(summary_text: str, related_id: str, related_record: str, record_id: str, timestamp: datetime) -> str:
    targets = [item for item in (related_id.strip(), related_record.strip()) if item and item != "无"]
    if not targets:
        return summary_text
    chunks = ENTRY_RE.split(summary_text)
    changed = False
    for index, chunk in enumerate(chunks):
        if "场景A" not in chunk or not any(target in chunk for target in targets):
            continue
        chunks[index] = re.sub(
            r"- 后续是否被确认完成: .+",
            f"- 后续是否被确认完成: 已确认,见 {record_id} ({timestamp.strftime('%Y-%m-%d %H:%M')})",
            chunk,
            count=1,
        )
        changed = True
        break
    return "".join(chunks) if changed else summary_text


def normalize_entry_ids(summary_text: str) -> str:
    prefix, entries = parse_entries(summary_text)
    if not entries:
        return summary_text
    normalized = []
    changed = False
    for entry in entries:
        if entry.record_id:
            normalized.append(entry.text.rstrip())
            continue
        generated_id = make_existing_entry_record_id(entry.timestamp, entry.text)
        lines = entry.text.rstrip().splitlines()
        lines.insert(1, f"- 记录ID: {generated_id}")
        normalized.append("\n".join(lines))
        changed = True
    if not changed:
        return summary_text
    return prefix.rstrip() + "\n" + "\n\n".join(normalized) + "\n"


def parse_entries(summary_text: str) -> tuple[str, list[Entry]]:
    parts = ENTRY_RE.split(summary_text)
    prefix = parts[0]
    entries = []
    for chunk in parts[1:]:
        match = ENTRY_HEADER_RE.match(chunk)
        if not match:
            header = chunk.splitlines()[0] if chunk.splitlines() else "空条目"
            raise ValueError(f"malformed recent entry heading: {header}")
        timestamp = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M")
        record_match = re.search(r"^- 记录ID: (.+)$", chunk, re.M)
        record_id = record_match.group(1).strip() if record_match else ""
        entries.append(Entry(chunk.strip() + "\n", timestamp, record_id))
    return prefix, entries


def partition_entries(summary_text: str, *, today: date) -> tuple[list[Entry], list[Entry]]:
    _, entries = parse_entries(summary_text)
    kept = []
    folded = []
    for entry in entries:
        age_days = (today - entry.timestamp.date()).days
        if age_days > 14 or age_days < 0:
            folded.append(entry)
        else:
            kept.append(entry)
    if len(kept) > 15:
        folded.extend(kept[15:])
        kept = kept[:15]
    return kept, folded


def replace_entries(summary_text: str, entries: list[Entry]) -> str:
    prefix, _ = parse_entries(summary_text)
    return prefix.rstrip() + "\n" + "\n\n".join(entry.text.rstrip() for entry in entries) + ("\n" if entries else "")


def replace_long_term_summary(summary_text: str, long_term_summary: str) -> str:
    if not long_term_summary.strip():
        raise ValueError("--long-term-summary is required when folding entries")
    new_body = neutralize_long_term(long_term_summary)
    new_text, count = LONG_TERM_RE.subn(lambda match: match.group(1) + new_body + match.group(3), summary_text, count=1)
    if count != 1:
        raise ValueError("memory-summary.md missing replaceable 长期摘要 section")
    return new_text


def neutralize_long_term(text: str) -> str:
    lines = []
    for raw_line in text.strip().splitlines():
        line = raw_line.rstrip()
        if line.startswith("### "):
            line = "\\" + line
        lines.append(line)
    return "\n".join(lines) + "\n"


def entry_to_json(entry: Entry) -> dict[str, str]:
    return {
        "record_id": entry.record_id,
        "timestamp": entry.timestamp.strftime("%Y-%m-%d %H:%M"),
        "entry": entry.text,
    }


def fence_block(text: str) -> str:
    ticks = 3
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("`"):
            ticks = max(ticks, len(stripped) - len(stripped.lstrip("`")) + 1)
    fence = "`" * ticks
    return f"{fence}text\n{text}\n{fence}"


def append_raw_log(
    path: Path,
    *,
    timestamp: datetime,
    scene: str,
    writes_summary: str,
    related_record: str,
    user_input: str,
    response: str,
) -> None:
    if not path.exists():
        path.write_text(f"# 未来自己 - Raw Conversations - {path.stem}\n\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            f"""---

## {timestamp.strftime('%Y-%m-%d %H:%M')}
- 场景判断: {scene}
- 是否写入 summary: {writes_summary}
- 关联记录: {neutralize_field(related_record, default="无")}

### 用户原始输入
{fence_block(user_input)}

### 回应原文
{fence_block(response)}
"""
        )


def write_private(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def set_private_directory(path: Path) -> None:
    try:
        path.chmod(0o700)
    except OSError:
        pass


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PermissionError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
