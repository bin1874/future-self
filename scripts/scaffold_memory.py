#!/usr/bin/env python3
"""Create a .future-self memory directory.

Usage:
  python3 scripts/scaffold_memory.py [root] \
    --target "..." --target-type "坏习惯|新习惯|其他" \
    --future-self "..." --tone "..." --dislike "..." [--moment "..."]

The script creates the standard storage files and can record the first scene if
the skill had to respond before initialization completed.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--target", default="", help="最想解决的具体事项")
    parser.add_argument("--target-type", default="", choices=["坏习惯", "新习惯", "其他", ""])
    parser.add_argument("--future-self", default="", help="未来自己画像；可为空或未记录")
    parser.add_argument("--moment", default="", help="可选：容易发生/后悔的时刻，没问到就留空")
    parser.add_argument("--tone", default="")
    parser.add_argument("--dislike", default="")
    parser.add_argument("--initial-scene", choices=["A", "B"], default=None)
    parser.add_argument("--initial-user-input", default="")
    parser.add_argument("--initial-response", default="")
    parser.add_argument("--initial-minimal-action", default="")
    parser.add_argument("--initial-related-record", default="无")
    parser.add_argument("--timestamp", default=None, help="YYYY-MM-DD HH:MM; defaults to local time")
    parser.add_argument("--force", action="store_true", help="overwrite profile.md and memory-summary.md, preserving raw logs")
    parser.add_argument("--force-profile", action="store_true", help="overwrite only profile.md, preserving memory-summary.md and raw logs")
    parser.add_argument("--force-summary", action="store_true", help="overwrite only memory-summary.md, preserving profile.md and raw logs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    memory_dir = root / ".future-self"
    raw_dir = memory_dir / "raw-conversations"
    raw_dir.mkdir(parents=True, exist_ok=True)
    set_private_permissions(memory_dir, raw_dir)
    ensure_self_ignored(root, memory_dir)

    timestamp = parse_timestamp(args.timestamp)
    month = timestamp.strftime("%Y-%m")
    anchor = timestamp.strftime("%Y-%m-%d-%H-%M")
    record_id = make_record_id(timestamp, args.initial_scene or "init", args.initial_user_input)

    force_profile = args.force or args.force_profile
    force_summary = args.force or args.force_summary
    write_file(memory_dir / "profile.md", profile_text(args), force=force_profile, backup=force_profile)
    write_file(memory_dir / "memory-summary.md", summary_text(args, timestamp, month, anchor, record_id), force=force_summary, backup=force_summary)

    if args.initial_scene and args.initial_user_input:
        append_raw_log(
            raw_dir / f"{month}.md",
            timestamp=timestamp,
            scene=f"场景{args.initial_scene}",
            writes_summary="是",
            related_record=args.initial_related_record,
            user_input=args.initial_user_input,
            response=args.initial_response,
        )

    warn_if_tracked(root)
    print(f"Created memory directory: {memory_dir}")
    return 0


def parse_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.now().replace(second=0, microsecond=0)
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("--timestamp must use format YYYY-MM-DD HH:MM") from exc


def set_private_permissions(memory_dir: Path, raw_dir: Path) -> None:
    for directory in (memory_dir, raw_dir):
        try:
            directory.chmod(0o700)
        except OSError:
            pass


def ensure_self_ignored(root: Path, memory_dir: Path) -> None:
    gitignore = memory_dir / ".gitignore"
    write_file(gitignore, "*\n", force=True)
    try:
        gitignore.chmod(0o600)
    except OSError:
        pass

    if not is_inside_git_worktree(root):
        return

    exclude = git_path(root, "info/exclude")
    if exclude is None:
        return
    try:
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if ".future-self/" not in existing.splitlines():
            exclude.parent.mkdir(parents=True, exist_ok=True)
            with exclude.open("a", encoding="utf-8") as handle:
                if existing and not existing.endswith("\n"):
                    handle.write("\n")
                handle.write(".future-self/\n")
    except OSError as exc:
        print(f"WARNING: 无法写入 .git/info/exclude: {exc}", file=sys.stderr)


def warn_if_tracked(root: Path) -> None:
    if not is_inside_git_worktree(root):
        return
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", ".future-self"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        print(f"WARNING: 无法检查 .future-self 是否已被 git 跟踪: {exc}", file=sys.stderr)
        return
    tracked = [line for line in result.stdout.splitlines() if line.strip()]
    if tracked:
        print(
            "WARNING: .future-self/ 中已有文件被 git 跟踪；脚本不会自动移出索引。"
            "请确认是否需要手动处理这些私密记录。",
            file=sys.stderr,
        )


def is_inside_git_worktree(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_path(root: Path, pathspec: str) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--git-path", pathspec],
            check=False,
            text=True,
            capture_output=True,
        )
    except OSError as exc:
        print(f"WARNING: 无法定位 git 路径 {pathspec}: {exc}", file=sys.stderr)
        return None
    if result.returncode != 0:
        return None
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = root / path
    return path


def write_file(path: Path, content: str, *, force: bool, backup: bool = False) -> None:
    if path.exists() and not force:
        return
    if path.exists() and force and backup:
        backup_path = unique_backup_path(path)
        backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            backup_path.chmod(0o600)
        except OSError:
            pass
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def unique_backup_path(path: Path) -> Path:
    base = path.with_name(f"{path.name}.bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    if not base.exists():
        return base
    index = 1
    while True:
        candidate = path.with_name(f"{base.name}-{index}")
        if not candidate.exists():
            return candidate
        index += 1


def neutralize_field(value: str, *, default: str = "未记录") -> str:
    value = value.strip() or default
    lines = []
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line.startswith(("#", "-", ">", "`")) or line == "---":
            line = "\\" + line
        lines.append(line)
    return " / ".join(lines) if lines else default


def profile_text(args: argparse.Namespace) -> str:
    target_line = neutralize_field(args.target)
    if args.target_type:
        target_line = f"{target_line}（类型: {args.target_type}；容易发生的时刻: {neutralize_field(args.moment)}）"
    future_self = neutralize_field(args.future_self)
    return f"""# 未来自己 - Profile

## 初始立场
（首次生成，之后基本不变，除非用户明确要求修改）

- 最想解决的具体事项: {target_line}
- 希望被提醒的语气: {neutralize_field(args.tone)}
- 讨厌的提醒方式: {neutralize_field(args.dislike)}

---

## 未来自己画像
（初始化第一轮轻量采集；这是"未来自己"的身份锚点，不进近期行动索引，也不随窗口压缩折叠。
回应时只有在自然贴合[点破]或[代价转化]时引用，不硬凑）

- 具体画面: {future_self}
- 与现在最大的不同: 未单独拆分；见具体画面

---

## 场景B例外/奖励边界
（不在初始化时询问，只在实际使用中用户明确纠正场景B判断时才追加/更新。
这是稳定偏好，不受"近期行动索引"的压缩窗口约束）

- 暂无

---

## 维护说明
这个文件只保存稳定立场、提醒偏好、未来自己画像和场景B边界。不要把原始会话或行动流水写进这里。
"""


def summary_text(args: argparse.Namespace, timestamp: datetime, month: str, anchor: str, record_id: str) -> str:
    display_time = timestamp.strftime("%Y-%m-%d %H:%M")
    recent = ""
    if args.initial_scene == "A" and args.initial_user_input:
        recent = f"""
### {display_time} | 场景A 行动前
- 记录ID: {record_id}
- 用户输入摘要: {neutralize_field(args.initial_user_input)}
- 原始会话位置: raw-conversations/{month}.md#{anchor}
- 回应给出的最小动作: {neutralize_field(args.initial_minimal_action)}
- 后续是否被确认完成: 待确认
"""
    elif args.initial_scene == "B" and args.initial_user_input:
        recent = f"""
### {display_time} | 场景B 行动后
- 记录ID: {record_id}
- 用户输入摘要: {neutralize_field(args.initial_user_input)}
- 原始会话位置: raw-conversations/{month}.md#{anchor}
- 呼应的历史记录: {neutralize_field(args.initial_related_record, default="无")}
- 回应摘要: {neutralize_field(args.initial_response)}
"""

    return f"""# 未来自己 - Memory Summary

## 长期摘要
（滚动更新，记录"模式"而不是"事件"。当近期行动索引超过窗口阈值时，
把窗口外记录折叠进这里。这部分整体控制在约 200-300 字以内）

- 反复出现的场景: 初始样本不足，暂无法判断
- 最小动作完成率: 初始样本不足，暂无法判断
- 语气/提醒方式的反馈: {neutralize_field(args.dislike, default="暂无")}
- 其他值得记住的模式: 暂无

---

## 近期行动索引
（只保留最近 15 条，且所有记录都在最近 14 天内，时间使用本地时间，新记录写在最上面。
超出窗口的记录会被折叠进"长期摘要"并从这里删除；原始会话仍保留在 raw-conversations/）
{recent}"""


def make_record_id(timestamp: datetime, scene: str, seed: str) -> str:
    digest = hashlib.sha1(f"{timestamp.isoformat()}|{scene}|{seed}".encode("utf-8")).hexdigest()[:6]
    return f"fs-{timestamp.strftime('%Y%m%d-%H%M')}-{digest}"


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
    display_time = timestamp.strftime("%Y-%m-%d %H:%M")
    with path.open("a", encoding="utf-8") as f:
        f.write(
            f"""---

## {display_time}
- 场景判断: {scene}
- 是否写入 summary: {writes_summary}
- 关联记录: {neutralize_field(related_record, default="无")}

### 用户原始输入
{fence_block(user_input)}

### 回应原文
{fence_block(response)}
"""
        )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PermissionError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        raise SystemExit(1)
