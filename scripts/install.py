#!/usr/bin/env python3
"""Install this skill for Codex and/or Claude Code.

Examples:
  python3 scripts/install.py --target both --mode symlink
  python3 scripts/install.py --target claude --mode copy
  python3 scripts/install.py --target codex-legacy --mode symlink
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


SKILL_NAME = "future-self"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        choices=["codex", "codex-legacy", "claude", "both"],
        default="both",
        help="codex installs to ~/.agents/skills; codex-legacy installs to ${CODEX_HOME:-~/.codex}/skills",
    )
    parser.add_argument("--mode", choices=["symlink", "copy"], default="symlink")
    parser.add_argument("--force", action="store_true", help="replace an existing install path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    skill_root = Path(__file__).resolve().parents[1]
    ensure_skill_root(skill_root)

    destinations = []
    if args.target in {"codex", "both"}:
        destinations.append(Path.home() / ".agents" / "skills" / SKILL_NAME)
    if args.target == "codex-legacy":
        codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        destinations.append(codex_home / "skills" / SKILL_NAME)
    if args.target in {"claude", "both"}:
        destinations.append(Path.home() / ".claude" / "skills" / SKILL_NAME)

    for dest in destinations:
        install(skill_root, dest, args.mode, args.force)
    return 0


def ensure_skill_root(path: Path) -> None:
    skill_md = path / "SKILL.md"
    if not skill_md.exists():
        raise SystemExit(f"SKILL.md not found at {skill_md}")


def install(src: Path, dest: Path, mode: str, force: bool) -> None:
    if dest.exists() or dest.is_symlink():
        if not force:
            print(f"exists: {dest} (use --force to replace)")
            return
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)

    dest.parent.mkdir(parents=True, exist_ok=True)
    if mode == "symlink":
        try:
            dest.symlink_to(src, target_is_directory=True)
            print(f"symlink: {src} -> {dest}")
            return
        except OSError as exc:
            print(f"symlink failed: {exc}")
            print("falling back to copy; copy installs will not automatically sync future source changes")

    shutil.copytree(src, dest, ignore=copy_ignore)
    print(f"copy: {src} -> {dest}")


def copy_ignore(directory: str, names: list[str]) -> set[str]:
    ignored = {".git", "__pycache__", ".future-self"}
    ignored.update(name for name in names if name.endswith((".pyc", ".pyo")))
    return ignored.intersection(names)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PermissionError) as exc:
        print(f"错误: {exc}")
        raise SystemExit(1)
