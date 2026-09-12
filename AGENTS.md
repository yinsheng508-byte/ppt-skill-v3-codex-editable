# AGENTS.md

## 当前主体

- 当前 profile：`codex`
- 当前版本：`1.0.5`
- 生成时间：`2026-09-12T20:58:27+08:00`

## 必读顺序

1. 当前目录是 PPT Skill 工作区壳层，不是 Skill 根目录，也不是具体 PPT 项目目录。
2. Skill 主体在 `.skill/`，执行任何 Skill 任务前必须先读 `.skill/SKILL.md`。
3. 维护、安装、打包、跨平台检查或主体切换任务，必须再读 `.skill/docs/维护说明.md`。
4. 具体 PPT 项目必须放在 `PPT输出/<中文项目名>/`，输入资料放在 `输入资料/`。

## 根目录约束

根目录只保留当前入口文件、`输入资料/`、`PPT输出/` 和 `.skill/`。Codex 形态使用 `AGENTS.md`；WorkBuddy 形态使用 `CODEBUDDY.md`。两者不得并存。

## 常用命令

```bash
python3 .skill/scripts/pptctl.py inspect-installation
python3 .skill/scripts/pptctl.py install-profile --target codex
python3 .skill/scripts/pptctl.py install-profile --target workbuddy
```
