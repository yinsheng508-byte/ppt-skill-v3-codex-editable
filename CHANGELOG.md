# Changelog

本文件记录 PPT Skill 的仓库发布版本。稳定调用名仍是 `ppt-skill-v2`，runtime package 仍是 `ppt_skill_v2`；这里的版本号只用于同步、发布和变更说明。

## 0.3.0 - 2026-09-02

本次新增 K12 阶段4教案设计能力，并进一步收敛为 AI 主控写作、runtime 只做确定性渲染和底线检查。

新增：

- 新增 K12 教案设计规范：只服务小学、初中、高中课件项目，非 K12 项目仍只输出阶段4演讲逐字稿。
- 新增 `education_context` 轻量教育上下文，用于记录可确认的学段、年级、学科、课题、教材线索和课时策略。
- 新增 K12 学科 profile registry，覆盖语文、数学、英语、物理、化学、生物、科学、政治/道德与法治、历史、地理、美术/艺术、信息科技、劳动、体育与健康。
- 新增阶段4教案生成命令：`build-lesson-plan-context`、`build-lesson-plan`、`record-lesson-plan-qa`。
- 新增 `validate-k12-subject-profiles` 命令，用于校验 K12 学科 profile 配置。
- 新增教案设计 Markdown、Word、PDF 三件套和 `lesson_plan_manifest.json` 入账路线。

调整：

- 阶段4可在 K12 项目中同时输出演讲逐字稿和教案设计；`stage4_script_completed` 保持兼容命名，但对 K12 项目同时代表教案三件套已完成。
- 教案内容质量由主控模型判断，runtime/doctor 只检查 K12 条件、材料追溯、文件存在、hash、PDF 可读性、教师可见文本清洁、实验安全等硬问题。
- 教案不以页数定质量；PDF 页数只记录排版结果，不触发低页数提示、warning 或完成判断。内容偏薄时由主控自然扩写教学分析、教学过程、任务评价、作业、板书和反思。
- 教学过程收敛为教师可读五列表：环节、教师活动、学生活动、任务与评价、设计意图/二次备课；时间、PPT 页码和材料来源不作为固定可见列。
- 板书设计和教学方案规范增强，强调课堂任务链、关键提问、追问纠偏、学生产出、评价证据、知识结构、问题链和方法链。
- 阶段4讲稿生成说明去工程化，减少 runtime、manifest、内部决策名等教师或用户不需要看到的表达。

兼容性：

- 不改稳定 Skill 调用名 `ppt-skill-v2`。
- 不改 Python package 名 `ppt_skill_v2`。
- 旧项目没有 `education_context` 时仍可恢复；K12 判断只在有明确学段、年级、学科、课题、教材等信号时触发。
- `stage4_lesson_plan_required` 保留为兼容读取别名，新写入优先使用 `stage4_outputs.lesson_plan.required`。
- `docs/`、`tests/`、`outputs/` 仍按 `.gitignore` 作为本地开发、验收和项目产物目录，不进入公开 Skill 包。

验收：

- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`
- `python3 scripts/pptctl.py validate-style-templates`
- `python3 scripts/pptctl.py validate-k12-subject-profiles`
- `PYTHONPATH=scripts/runtime python3 -m unittest discover -s tests -v`
- `python3 -m compileall -q scripts/runtime/ppt_skill_v2`
- `git diff --check`

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
