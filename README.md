# future-self-skill

`future-self-skill` 是 `future-self` Agent Skill 的开源项目，用“未来的自己”的口吻处理两个很窄的时刻：

- 行动前：用户正在拖延、逃避、想放纵一件对未来有益的小事时，给三句话拦截。
- 行动后：用户刚完成一件对未来有益的小事时，给三句话确认和感谢。

它不是通用聊天、心理咨询、人生建议或情绪陪伴工具。它的产品价值来自三件事：针对当下具体场景、记得用户之前的立场和行动、用用户亲口描述的“未来自己画像”作为轻量锚点。

## 项目结构

```text
SKILL.md                         Skill 规范和主要行为说明
assets/                          profile/summary/raw log 模板
scripts/scaffold_memory.py       初始化 .future-self/ 记忆目录
scripts/update_memory.py         写入 raw log、近期索引、record id、窗口压缩
scripts/lint_memory.py           检查记忆目录结构和 raw 指针
scripts/install.py               安装到 Codex / Claude Code skills 目录
evals/                           行为回归样例
```

运行时会在当前工作目录创建本地记忆目录：

```text
.future-self/
  profile.md
  memory-summary.md
  raw-conversations/YYYY-MM.md
```

`.future-self/` 是用户隐私数据。脚本会在目录内写 `.gitignore`，并尝试通过 `.git/info/exclude` 避免误提交；如果发现已有 `.future-self/` 文件被 Git 跟踪，只警告，不自动从索引移除。

## 安装

从仓库根目录运行：

```bash
python3 scripts/install.py --target both --mode symlink
```

目标：

- `--target codex` 安装到 `~/.agents/skills/future-self`
- `--target codex-legacy` 安装到 `${CODEX_HOME:-~/.codex}/skills/future-self`
- `--target claude` 安装到 `~/.claude/skills/future-self`
- `--target both` 安装到 Codex 和 Claude Code

如果 symlink 因权限或平台限制失败，脚本会回退到 copy。copy 模式不会自动同步后续源代码修改。

## 记忆脚本

初始化：

```bash
python3 scripts/scaffold_memory.py "$PWD" \
  --target "睡前收拾行李" \
  --target-type "新习惯" \
  --future-self "3年后的我睡前已经把行李箱摊开，早上不再慌" \
  --tone "直接但别命令" \
  --dislike "说教、空话"
```

写入一次场景记录：

```bash
python3 scripts/update_memory.py "$PWD" \
  --scene A \
  --user-input "现在不想收拾行李" \
  --response "这时候不想动很正常。你躲的是明早的慌。先把箱子拿出来。" \
  --user-summary "不想收拾行李" \
  --minimal-action "把箱子拿出来"
```

检查记忆目录：

```bash
python3 scripts/lint_memory.py "$PWD"
```

`update_memory.py` 负责确定性写入：生成稳定 `record id`、追加 raw log、插入近期索引、回填 A/B 完成关系、检测 15 条且 14 天的窗口。模型只负责生成语义摘要和必要的长期摘要。

如果窗口压缩需要模型摘要，`update_memory.py` 会先输出 fold candidates 并以退出码 `2` 停止，不写文件。拿到新的长期摘要后，再用 `--long-term-summary` 重跑。

## 验证

基础检查：

```bash
python3 -m py_compile scripts/scaffold_memory.py scripts/update_memory.py scripts/lint_memory.py scripts/install.py
python3 -m json.tool evals/evals.json >/dev/null
```

端到端 smoke test：

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

## 隐私边界

- `.future-self/` 是明文本地文件。
- raw log 保留用户原文，但日常回应默认只读 `profile.md` 和 `memory-summary.md`。
- 危机、严重心理困扰、自伤风险等输入不套用场景 A/B，也不写 raw log 或 summary。
- 用户说“这次别记录”或“不要保存这句话”时，不写入任何记忆文件。
- 用户要求删除历史时，应同步修改 raw log 和 `memory-summary.md`。
