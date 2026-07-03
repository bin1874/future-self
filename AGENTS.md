# Agent Instructions

This repository contains the `future-self` Agent Skill. Treat `SKILL.md` as the behavior source of truth, and keep scripts/templates/evals aligned with it.

## Scope

The skill only handles two user moments:

- Scene A: before action, when the user is avoiding, delaying, or about to indulge instead of doing a beneficial small action.
- Scene B: after action, when the user has completed a beneficial small action.

Do not broaden it into general coaching, therapy, productivity advice, or emotional companionship. If a user input is outside daily small-action procrastination, especially crisis or severe mental distress, normal conversation applies and memory must not be written.

## Memory Rules

Runtime memory lives in the caller's current working directory:

```text
.future-self/
  profile.md
  memory-summary.md
  raw-conversations/YYYY-MM.md
```

Important rules:

- Do not read `raw-conversations/` during normal Scene A/B handling.
- Normal responses read only `profile.md` and `memory-summary.md`.
- Raw logs are for user-requested review/search, recovery, and debugging.
- `.future-self/` is private user data. Do not commit it, inspect it casually, or use it as project fixture data.
- If editing memory manually, run `python3 scripts/lint_memory.py "$ROOT"` afterward.

## Script Responsibilities

Use scripts for deterministic storage behavior.

- `scripts/scaffold_memory.py` creates `.future-self/`, writes initial files, writes `.future-self/.gitignore`, warns if memory is already tracked by Git, and backs up overwritten files when `--force` is used.
- `scripts/update_memory.py` appends raw logs, inserts recent-index entries, generates stable record ids, backfills A/B completion, detects window compression, and writes private file permissions.
- `scripts/lint_memory.py` validates required sections, recent-entry headers, record ids, raw pointers, raw log existence, and 15-entry/14-day window constraints.
- `scripts/install.py` installs the skill into Codex and/or Claude Code skill directories.

The model owns semantic work: scene judgment, response generation, user summary, response summary, and long-term summary text. The scripts own file mechanics.

## Development Checks

Run these before finishing script or eval changes:

```bash
python3 -m py_compile scripts/scaffold_memory.py scripts/update_memory.py scripts/lint_memory.py scripts/install.py
python3 -m json.tool evals/evals.json >/dev/null
```

For memory behavior changes, also run an end-to-end temporary-directory test:

```bash
tmp=$(mktemp -d)
python3 scripts/scaffold_memory.py "$tmp" \
  --target "睡前收拾行李" \
  --target-type "新习惯" \
  --future-self "未来的我晚上就摊开行李箱" \
  --tone "直接" \
  --dislike "说教" \
  --timestamp "2026-07-02 16:00"

out=$(python3 scripts/update_memory.py "$tmp" \
  --scene A \
  --user-input "现在不想收拾行李" \
  --response "这时候不想动很正常。你躲的是明早的慌。先把箱子拿出来。" \
  --user-summary "不想收拾行李" \
  --minimal-action "把箱子拿出来" \
  --timestamp "2026-07-02 16:01")

rid=$(printf '%s' "$out" | python3 -c 'import json,sys; print(json.load(sys.stdin)["record_id"])')

python3 scripts/update_memory.py "$tmp" \
  --scene B \
  --user-input "我刚把箱子拿出来了" \
  --response "你把箱子拿出来了，接上了刚才那一步。明早少面对一个从零开始的乱局。谢谢你。" \
  --user-summary "把箱子拿出来了" \
  --response-summary "确认完成了刚才的最小动作" \
  --related-id "$rid" \
  --timestamp "2026-07-02 16:02"

python3 scripts/lint_memory.py "$tmp" --today 2026-07-02
```

## Editing Guidelines

- Keep `SKILL.md`, `assets/`, `scripts/`, and `evals/` in sync.
- Prefer structured parsing and deterministic scripts over ad hoc Markdown edits.
- Preserve raw user text in raw logs. Neutralize structure only in `profile.md` and `memory-summary.md`.
- Do not change tracked project `.gitignore` to protect user memory. Use `.future-self/.gitignore` and `.git/info/exclude`.
- Do not auto-run destructive Git commands like `git rm --cached .future-self/...`; warn instead.
- Keep responses in examples short and concrete. Avoid empty encouragement such as “加油”, “你真棒”, or “你可以的”.

## Review Focus

When reviewing changes, prioritize:

- Trigger scope. Does it accidentally activate on ordinary speech like “刚做完手术”?
- Scene B judgment. Does it avoid confirming obvious indulgence?
- Memory continuity. Are related A/B entries linked without fabricating history?
- Privacy. Are crisis inputs and opt-out requests kept out of memory?
- Markdown safety. Can user-provided text break headings, fields, or raw pointers?
- Backward compatibility. Can old summaries without `记录ID` be migrated safely?
