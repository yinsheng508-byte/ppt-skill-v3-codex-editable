# PPT Skill v2（Codex 可编辑架构迭代）

这是一个中文 AI PPT Skill 主包，覆盖 PPT 生成、改造、审查、可编辑化和演讲稿输出流程。

## 版本口径

- 正式 Skill 调用名继续是 `ppt-skill-v2`，`agents/openai.yaml` 的默认提示词也继续使用 `$ppt-skill-v2`。
- Runtime Python package 继续是 `ppt_skill_v2`，schema、历史项目状态和本机密钥路径保留 v2 兼容口径。
- 当前仓库或目录中的 `v3` 只表示 Codex 可编辑路线和防漂移控制面的架构迭代，不代表已经迁移到新的 Skill name。
- 详细口径见 `references/版本与兼容说明.md`。

## 仓库内容

- `SKILL.md`：Skill 主入口和主控规则，保持短入口和 reference 路由。
- `AGENTS.md`：本仓库维护约定。
- `references/`：阶段流程、质量标准、生图证据链和可编辑 PPT 路线等规范。
- `assets/`：模板和风格模板。
- `scripts/`：确定性运行脚本、schema 和辅助工具。
- `agents/`：可复用 agent 配置。
- `inputs/`、`outputs/`、`tmp/`：仅保留空目录占位；本地项目输入、输出和临时文件不会上传。

## 不包含

本仓库不会提交具体 PPT 项目的输入资料、生成结果、中间缓存、临时文件、密钥或本地测试缓存。

## 校验

在 Codex Skill 开发环境中可运行：

```bash
python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
python3 scripts/pptctl.py validate-style-templates
PYTHONPATH=scripts/runtime python3 -m unittest discover -s tests
```
