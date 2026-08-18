# PPT Skill v3 Codex 可编辑

这是一个中文 AI PPT Skill 主包，覆盖 PPT 生成、改造、审查、可编辑化和演讲稿输出流程。

## 仓库内容

- `SKILL.md`：Skill 主入口和主控规则。
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
```
