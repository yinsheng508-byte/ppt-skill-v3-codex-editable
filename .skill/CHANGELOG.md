# Changelog

本文件记录 PPT Skill 的仓库发布版本。稳定调用名仍是 `ppt-skill-v3`，runtime package 仍是 `ppt_skill_v3`；这里的版本号只用于同步、发布和变更说明。

历史条目只记录当时版本事实。若旧条目与最新版本口径冲突，以最高版本条目、`.skill/SKILL.md` 和正式 references 为准。

## 1.0.4 - 2026-09-12

本次是 GitHub 同步前的发布打包收口，重点处理普通用户包的边界和维护入口。

调整：

- 新增 `docs/维护规划.md`，作为 GitHub 和分发包中的发布维护规划入口。
- 打包白名单补充 `docs/维护规划.md`，并继续排除 `tests/`、`docs/current/`、`docs/archive/`、`输入资料/`、`PPT输出/`、旧 `inputs/outputs/tmp`、缓存和 zip。
- 更新 package 测试，明确维护说明和维护规划都进入包，过程文档和测试不进入包。

验收：

- `python3 .skill/scripts/pptctl.py inspect-installation`
- `python3 .skill/scripts/pptctl.py validate-style-templates`
- `python3 .skill/scripts/pptctl.py validate-k12-subject-profiles`
- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .skill`
- `PYTHONPATH=.skill/scripts/runtime:.skill/tests python3 -m unittest discover -s .skill/tests -v`
- `python3 .skill/scripts/package_skill.py --output-dir .skill/dist`

## 1.0.3 - 2026-09-12

本次完成深度体检后的当前口径收敛：让 AI 主控保留判断权，runtime 只做确定性检查，并清理旧入口、旧说明文件和重复 reference。

调整：

- 阶段2A封面候选不再被正式全量图片结果缺失提前硬拦；完整图片版 PDF 确认阶段仍要求正式图片、PDF、hash 和 manifest 证据。
- 删除 `/文件整理`、`/整理` 作为用户快捷指令入口；`organize-deliverables` 保留为阶段4内部整理动作。
- 不再恢复或要求 `封面风格选择说明.md`、`阶段2_确认说明.md`、`讲稿生成说明.md`、`教案生成说明.md`。
- K12 教案 schema/runtime 降低机械质量门槛，只硬查结构、路径、manifest、文件和安全事实；教学质量交回主控判断。
- `视觉系统统一规范.md`、`阶段2审美QA规范.md` 和 `版本与兼容说明.md` 已合并进对应正式文档后移除。
- 阶段2提示词、图片风格、封面候选和生图证据链重新串联到 `PPT一致性.md` 与 `图片风格.md` 的当前项目来源。
- 中转站默认 base URL 对齐为 `http://direct-api.cangyuansuanli.cn/`，并补充 `direct-api` / `cangyuan` 路线别名。
- Canva 规范保留为唯一阶段外辅助编辑文档；风格模板规范只负责模板触发、注册和维护。
- 删除无引用的通用用户确认说明模板，并把阶段1总览模板改为“不是额外确认文件”的辅助模板。
- `make-decision` 生成的 `allowed_actions` 改用当前 CLI/drift 动作名；历史图片记录动作名和旧 packets 动作名只作为兼容别名识别。

验收：

- `python3 .skill/scripts/pptctl.py inspect-installation`
- `python3 .skill/scripts/pptctl.py validate-style-templates`
- `python3 .skill/scripts/pptctl.py validate-k12-subject-profiles`
- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .skill`
- `PYTHONPATH=.skill/scripts/runtime:.skill/tests python3 -m unittest discover -s .skill/tests -v`
- `python3 .skill/scripts/package_skill.py --output-dir .skill/dist`

## 1.0.2 - 2026-09-12

阶段2所有新请求统一使用主控整理的图片风格与画面计划。移除尺寸和流程说明，保留批准正文、独立参数及实际宽高/比例验收。

- 新增读取来源和登记画面计划命令；封面、5页试样、全量及返工使用同一编译器。
- 当前风格、完整禁用项和适用页面组件进入计划；标题/章节文字显式引用批准正文，页码单独控制。
- 新请求在提交前复核来源、版本及实际提示词；旧成功记录和在途请求保留原文，失败请求不进入用户文档。
- 编辑图片的本地输入与提示词一起冻结；修复编辑端点成功结果无法登记、来源编辑中导致在途结果无法回收的问题。
- 实际图片增加16:9比例检查，默认相对容差2%，与像素尺寸检查独立；不拉伸、不裁切原图。
- 参考说明保留在代码块外，修正重复“借鉴”文案；提示词文档支持成功记录重建和附件导出。
- 正文区只含批准原文，标题/章节用途在正文区外按段引用，避免用途标签被画入图片。
- 修复合法已决策返工被旧依据检查阻断；未授权过期、缺图与hash损坏仍阻断。

## 1.0.1 - 2026-09-12

本次把阶段2默认生图路线切换为苍原国内直连中转站，并补齐 OpenAI-compatible 生成请求与证据链。

调整：

- 新项目阶段2A封面候选、阶段2B试样和剩余整页图片默认走 `openai_image_api`。
- 默认中转配置统一为 `http://direct-api.cangyuansuanli.cn/`、`/v1/images/generations`、`gpt-image-2.5`、`1672x941`、`response_format=b64_json`。
- `run-image-api-batch` 支持 `--response-format`，packet、dry-run、batch report 和 API evidence 均记录响应格式。
- URL 图片下载失败会给出明确 HTTP 状态，避免把 provider URL 403 误判为普通生成失败。
- `make-decision` 阶段2默认生图决策会同时写入 `basis/execution.image_generation_route=openai_image_api`，并自动开放 `run_image_api_batch`。
- 主控决策校验会阻断中转 API 路线缺少 `run_image_api_batch`、官方 `codex_image_gen` 路线误写 `run_image_api_batch` 等路线和动作不一致问题。
- 新 `/v1/images/generations` 正式结果必须记录 `response_format`；旧 Grsai `/v1/draw/completions` 历史结果可继续读取。
- API 主请求连接失败、无效 `b64_json` 和 provider URL 下载网络错误会抛出更明确的 `ValidationError`。
- `codex_image_gen` 保留为显式备用路线；旧 Grsai `/v1/draw/completions` 解析能力只作为 legacy 兼容保留。

## 1.0.0 - 2026-09-12

本次确立 PPT Skill v3 的正式 1.0.0 版本口径，并进入目录隔离、Codex/WorkBuddy 双主体适配和跨平台中文路径兼容的落地改造阶段。

规划：

- 根目录目标收敛为入口文档、`输入资料/`、`PPT输出/` 和 `.skill/` 四项。
- Skill 主体后续迁入 `.skill/`，项目输入和输出明确放在 Skill 外部。
- Codex 形态使用根入口 `AGENTS.md`；WorkBuddy 形态使用根入口 `CODEBUDDY.md`。
- 新项目输出目标调整为 `PPT输出/<中文项目名>/`，不再嵌套 `projects`。
- `.skill/docs/维护说明.md` 将记录当前主体、版本号、安装方式、路径规则和 Windows/macOS 中文兼容检查。

兼容性：

- 稳定 Skill 调用名仍是 `ppt-skill-v3`，Python package 名仍是 `ppt_skill_v3`。
- 旧 `outputs/projects` 项目路径仅作为历史项目恢复和迁移线索，不作为新项目正式路径。
- 当前条目只确立版本和实施任务卡，目录迁移与 runtime 改造需按任务卡分阶段落地。

## 0.4.0 - 2026-09-12

本次重构阶段模型：旧可编辑 PPT 路线移出正式流程，阶段3改为逐字稿与 K12 教案输出，阶段4改为文件整理交付。

调整：

- 正式阶段骨架改为：阶段0资料整理 -> 阶段1规划确认 -> 阶段2图片版 PPT -> 阶段3逐字稿与教案输出 -> 阶段4文件整理交付。
- `build-speaker-script`、`build-lesson-plan-context`、`build-lesson-plan` 和 `record-lesson-plan-qa` 改为阶段3能力，输出到 `阶段3_逐字稿与教案输出/` 和 `_state/阶段3/`。
- `/文件整理` / `organize-deliverables` 改为阶段4整理交付，只复制已存在的阶段1、阶段2、阶段3交付物，并继续将已存在的逐字稿 PDF、教案 PDF 用 `pdftoppm` 导出 `216 DPI / 3x_72dpi` PNG 图片副本。
- `pptctl --help` 不再暴露旧可编辑 PPT、坐标复刻、OfficeCLI 坐标构建、阶段3去字背景生成和阶段3视觉 QA 命令。
- 正式图片生成 runtime 只支持阶段2；旧 `stage3-background` / `stage3_background` 去字背景路线会被显式拒绝。
- `image_result.schema.json` 收窄为阶段2图片结果 schema，旧 stage3 background image result 不再是正式结果类型。
- 正式打包排除旧可编辑 runtime 模块和旧 schema，减少误调用和包体积。

兼容性：

- 稳定 Skill 调用名仍是 `ppt-skill-v3`，Python package 名仍是 `ppt_skill_v3`。
- 历史项目中的旧 stage4 逐字稿/教案字段、旧 `stage3_editable_deck` basis 和旧目录只作为 legacy 读取线索保留；新项目、新文档、新命令不再把它们作为正式路线。
- `/canva`、`/可画` 仍是阶段外辅助编辑，不替代阶段3输出，也不自动推进阶段。

## 0.3.1 - 2026-09-12

本次增强 `/文件整理` 交付目录：阶段4逐字稿 PDF 和 K12 教案设计 PDF 会在整理时额外导出高清 PNG 图片副本。

新增：

- 新增 `pdf_page_images.py`，使用 Poppler `pdftoppm` 将已存在 PDF 渲染为 `216 DPI / 3x_72dpi` PNG。
- `/文件整理` 主题目录新增 `逐字稿图片/page_*.png` 和 `教案设计图片/page_*.png`。
- `organize-deliverables` JSON 摘要新增 `rendered`，记录导出页数、DPI、scale、图片尺寸、sha256 和工具路径。

调整：

- `/文件整理` 仍是被动整理入口，不写 decision，不推进阶段，不修改确认状态；PDF 图片只是已存在 PDF 的确定性派生交付副本。
- 默认只使用 `pdftoppm`，不使用备用渲染器；找不到工具、PDF 损坏或渲染失败时，只跳过对应图片导出，其他交付物继续整理。
- 支持 `PPT_SKILL_PDFTOPPM` 指定可执行文件，或 `PPT_SKILL_POPPLER_PATH` 指定 Poppler bin 目录，兼容 macOS、Linux 和 Windows `pdftoppm.exe`。

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

- 不改稳定 Skill 调用名 `ppt-skill-v3`。
- 不改 Python package 名 `ppt_skill_v3`。
- 旧项目没有 `education_context` 时仍可恢复；K12 判断只在有明确学段、年级、学科、课题、教材等信号时触发。
- 在当时的阶段4模型中，`stage4_lesson_plan_required` 保留为兼容读取别名，新写入优先使用 `stage4_outputs.lesson_plan.required`；0.4.0 起新写入已迁到 `stage3_outputs.lesson_plan.required`。
- `docs/`、`tests/`、`outputs/` 仍按 `.gitignore` 作为本地开发、验收和项目产物目录，不进入公开 Skill 包。

验收：

- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`
- `python3 scripts/pptctl.py validate-style-templates`
- `python3 scripts/pptctl.py validate-k12-subject-profiles`
- `PYTHONPATH=scripts/runtime python3 -m unittest discover -s tests -v`
- `python3 -m compileall -q scripts/runtime/ppt_skill_v3`
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

- 不改稳定 Skill 调用名 `ppt-skill-v3`。
- 不改 Python package 名 `ppt_skill_v3`。
- 不改现有项目目录结构或已存在项目状态字段。
- 不新增 Canva 作为阶段3正式 provider。

验收：

- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .`
- `PYTHONPATH=scripts/runtime python3 -m unittest discover -s tests`
- `python3 scripts/pptctl.py validate-style-templates`

## 0.1.0 - 2026-08-20

初始 GitHub 发布版本，包含中文 PPT 四阶段主控流程、阶段2图片版 PPT、阶段3 OfficeCLI 可编辑 PPT、阶段4演讲稿输出、恢复摘要、drift-check、work packet 和基础打包能力。
