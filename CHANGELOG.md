# Changelog

本文件记录 PPT Skill 的仓库发布版本。稳定调用名仍是 `ppt-skill-v2`，runtime package 仍是 `ppt_skill_v2`；这里的版本号只用于同步、发布和变更说明。

## 0.2.0 - 2026-08-26

本次是轻量化路由与 Canva 辅助编辑更新。

新增：

- 新增 `/canva`、`/可画` 阶段外 Canva 辅助编辑入口：导入或手动上传 PPT/PDF，用户手动 Magic Layers，回传 Canva 链接后由 Codex 使用 Canva 插件批量修正文案和样式。
- 新增 `create-canva-task-brief` runtime 命令，用于在具体 PPT 项目中生成 Canva 辅助编辑任务 brief，不修改阶段状态。
- 新增 drift-check 大类动作：`stage1_plan`、`stage2_image`、`stage3_editable`、`stage4_script`、`canva_auxiliary`，降低 Agent 选择 action 名的负担。
- 新增 controller decision schema 与 runtime 决策枚举同步测试，防止决策类型漂移。

调整：

- `SKILL.md` 增加更短的路线判断：默认四阶段、Canva 辅助、明确跳过才直接改文件、继续/确认/返工先恢复项目状态。
- 明确阶段2用户确认过的封面和试样页默认复用，不为正式全套图片重复生成。
- 明确阶段3正式路线仍是 OfficeCLI；Canva/Magic Layers 结果只作为阶段外辅助或阶段4外部锁稿来源，不自动算阶段3完成。
- 旧 Canva 浏览器自动点击 `AI图层` 路线改为 Legacy，只在用户明确要求浏览器控制时使用。
- 阶段0资料入口增加轻量判断：普通参考资料先登记来源和用途，只有需要完整提取、复刻、仿写或改造成 PPT 时才进入完整公众号资料包链路。
- `docs/current/` 口径收敛为开发规划入口，正式执行规则仍以 `SKILL.md` 和 `references/` 为准。

修复：

- 修正主控决策协议中的旧动作名 `call_editable_ppt_provider`，统一为 `build_officecli_coordinate_deck`。
- 补齐 `controller_decision.schema.json` 中缺失的 `reopen_stage3_sample_after_stage4`。

兼容性：

- 不改稳定 Skill 调用名 `ppt-skill-v2`。
- 不改 Python package 名 `ppt_skill_v2`。
- 不改现有项目目录结构或已存在项目状态字段。
- 不新增 Canva 作为阶段3正式 provider。

验收：

- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`
- `PYTHONPATH=scripts/runtime python3 -m unittest discover -s tests`
- `python3 scripts/pptctl.py validate-style-templates`

## 0.1.0 - 2026-08-20

初始 GitHub 发布版本，包含中文 PPT 四阶段主控流程、阶段2图片版 PPT、阶段3 OfficeCLI 可编辑 PPT、阶段4演讲稿输出、恢复摘要、drift-check、work packet 和基础打包能力。
