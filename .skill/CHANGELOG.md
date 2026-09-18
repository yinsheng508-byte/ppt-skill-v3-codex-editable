# Changelog

本文件记录 PPT Skill 的仓库发布版本。稳定调用名仍是 `ppt-skill-v3`，runtime package 仍是 `ppt_skill_v3`；这里的版本号只用于同步、发布和变更说明。

历史条目只记录当时版本事实。若旧条目与最新版本口径冲突，以最高版本条目、`.skill/SKILL.md` 和正式 references 为准。

## 1.1.0 - 2026-09-18

本次将当前工作区已完成的阶段1/2、资料登记和国际版 Canva 辅助编辑改造合并为正式发布版本；稳定调用名仍是 `ppt-skill-v3`，runtime package 仍是 `ppt_skill_v3`。

新增与调整：

- 阶段1以 `content.json` 作为正文权威来源，同步规划、逐页稿和提示词简报；图片请求按页冻结、结果保留不可变 SHA 证据，活动 work packet 改为轻量指针。
- `drift-check` 按具体动作收窄检查范围，`resume-brief`、`next-action` 和漂移检查默认即时返回，只有显式 `--persist` 才写控制快照。
- 资料登记同时维护项目内部归档与 `输入资料/<项目名>/` 用户入口副本，并在索引和资料清单中保留两条路径。
- 国际版 Canva 辅助编辑建立宿主/执行器、页级权威文案与视觉审计、敏感值拒绝记录和阶段外状态边界；允许范围内默认每批 5 页，经主控回读通过后直接提交。

兼容与发布边界：

- 历史项目、旧 task schema、旧派生材料和历史成功记录保持只读兼容；不自动迁移、删除或改写用户项目。
- GitHub 与发布包只纳入入口、正式规范、模板、runtime、schema、维护说明和 changelog；测试、过程文档、`输入资料/`、`PPT输出/`、构建产物及本机开发目录不随发布提交。

验收：

- 运行安装检查、模板/K12 校验、全量单测、runtime 编译、Skill 快检与发布包 manifest 审计。

## 1.0.12 - 2026-09-18

本次按最新执行口径收紧 Canva 批次策略：允许范围内的 Canva 辅助编辑默认 5 页一批，AI 主控回读文案与预览通过后直接提交，不等待用户确认。

调整：

- 正式 Canva 规范将“每批默认 3 到 5 页，复杂页 1 到 2 页”改为“每批默认 5 页，最后不足 5 页按剩余页处理”。
- 复杂页不再自动拆成 1 到 2 页，也不因此引入用户确认门禁；工具限制、预览异常、回读失败或视觉未闭环时仍必须 cancel。
- 新建 task 的 `commit_policy` 新增 `default_batch_page_count=5`，workflow 同步提示默认 5 页一批并直接提交。
- Skill 入口、维护说明、agent 默认提示和本地任务卡同步为默认 5 页批次策略。

验收：

- `test_canva_task.py` 增加默认批次页数断言。
- 本次不触碰真实 Canva 设计、不写项目阶段 state。

## 1.0.11 - 2026-09-18

本次补充国际版 Canva 辅助编辑的 AI 主控口径：逐页文案与视觉校验不是纯机械字段检查，而是由主控理解页面角色、权威文案和阶段2视觉意图后，再留下可回读证据并提交允许范围内的修订。

调整：

- 正式 Canva 规范改为“AI 主控的逐页文案与视觉校验”，明确 `page_audit.json` 是主控判断后的证据，不替代主控的页面理解和审美判断。
- 每页视觉校验要求结合页面角色、信息重点和阶段2参考，说明为什么已贴近参考或为什么只能转人工。
- Skill 入口、阶段流程、维护说明、agent 默认提示和新建 task brief workflow 均同步为“AI 主控判断 + runtime 证据门禁”。
- 直接 commit、`pre_authorized`、controller-reviewed preview、文案回读、视觉闭环、人工待办范围和阶段外边界保持不变。

验收：

- 本次仅收口规范与 brief 语义，不触碰真实 Canva 设计、不写项目阶段 state。
- 相关验证命令见当前任务卡 TC-08 与 TC-06 回写。

## 1.0.10 - 2026-09-18

本次把国际版 Canva 双宿主辅助编辑收敛为可由 AI 实际执行和验证的页级合同。WorkBuddy 仍使用 Canva MCP，Codex 仍使用 Canva 插件；两者在允许范围内均不再等待用户逐批确认，而是在 AI 回读通过后直接提交。

调整：

- 每页审计强制记录权威文字、修改前文字、修改后回读文字、发现项、拟执行操作和逐项视觉检查；通过的 `post_edit_text` 必须与同页 `content.json.final_visible_text` 精确一致。
- 视觉检查逐项覆盖文字角色与层级、字号、粗细、颜色、对齐、行高、列表、位置、尺寸、溢出、遮挡、断行；未闭环的 `needs_edit`/`blocked` 禁止 commit。
- 新建 task 升为 schema v1.2，写入 `direct_commit_after_controller_qa`；新批次在控制器审核预览、页级文案和视觉校验通过后，以 `pre_authorized` 直接 commit，保存后必须重新只读回读。
- schema v1.1 的确认式记录保持只读兼容；新 v1.2 task 不允许进入 `waiting_batch_confirmation`，也不允许将 `confirmed` 作为新提交授权。
- 直接提交没有放宽边界：Magic Layers、字体族、背景、复杂图形、增删内容/页面、换图和主动重排仍由人工处理，Canva 导出稿仍须用户确认才可作为阶段3外部锁定稿。

验收：

- `test_canva_task.py` 覆盖未审核预览、文案回读不匹配、未闭环视觉项、旧确认式授权与 v1.2 直接授权边界。
- 完整安装、模板、单测、编译、Skill 快检、打包和包内容检查命令见本次任务卡的 TC-06 回写。

## 1.0.9 - 2026-09-18

本次在不改变“内容确认 → 4 张封面 → 封面确认 → 5 页试样 → 试样确认 → 剩余页 → 最终 PDF 确认 → Stage 3 全格式 → Stage 4 整理交付”流程的前提下，收紧事实来源并去除内部重复写入。

调整：

- `content.json` 成为 Stage 1 正文唯一权威来源；页面规划、逐页稿和 prompt brief 的文字字段按来源摘要同步，旧项目保持兼容读取。
- 4 封面、5 页试样和内部生图登记使用动作相关严格检查，不扫描无关的后续阶段；最终 PDF、Stage 3/4 收口、手动 doctor 与异常恢复仍完整检查。
- Stage 2 成图按 SHA 保存一份不可变内部证据图，页面入口优先硬链接；冻结请求、提供方证据、正式结果和轻量尝试记录各自只保存本职事实，停止新写 `result_receipts`。
- 每个 batch 仅保留一份当前权威 manifest；提示词 Markdown 只在封面、试样、剩余页完成和显式刷新/导出时完整重建。
- 完整 work packet 仍归档，活动文件改为轻指针；`resume-brief`、`next-action`、`drift-check` 默认即时返回，只有 `--persist` 才保存控制快照。
- 外部锁定稿进入 Stage 3 时要求存在、声明 SHA 匹配和明确确认依据；标准路线仍必须先确认 Stage 2 图片版 PDF，外部模式不伪造 Stage 2 确认。

兼容：

- 旧 Stage 1 派生材料、完整活动包、控制快照、batch history 和提示词台账继续只读兼容；不自动迁移、删除或压缩真实项目。

验收：

- 全量单测 `274/274` 通过。
- `inspect-installation`、风格模板、K12 模板、runtime 编译、Skill 快检、打包全部通过。
- 已生成 `.skill/dist/ppt-skill-v3.zip` 与 manifest；过程文档和测试仍不进入发布包。

## 1.0.8 - 2026-09-18

本次完成国际版 Canva 双宿主阶段外辅助编辑收口：WorkBuddy 使用已授权的 Canva MCP，Codex 使用 Canva 插件；两者共享逐页权威文案校验、小批预览、用户确认与 commit/cancel 纪律。

调整：

- `/canva`、`/可画` 均固定表示国际版 Canva；runtime task v1.1 显式记录 provider、宿主和执行器，不再从 profile 猜测 MCP 可用性。
- 新增逐页审计、批次状态机、人工待办投影和受限导出记录；批次必须从 `draft` 收口，commit 必须记录“预览已展示 + 用户确认”。
- 恢复摘要以只读 sidecar 展示 Canva 任务、执行器、最后批次和人工待办，不影响项目阶段、next action 或 decision。
- 记录拒绝 token、签名 URL 和本机路径；`manual_handoff` 被明确标为 connector 阻断，不能冒充编辑完成。

验收：

- `python3 .skill/scripts/pptctl.py inspect-installation`
- `python3 .skill/scripts/pptctl.py validate-style-templates`
- `python3 .skill/scripts/pptctl.py validate-k12-subject-profiles`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.skill/scripts/runtime:.skill/tests python3 -m unittest discover -s .skill/tests -v`
- `python3 -m compileall -q .skill/scripts/runtime/ppt_skill_v3`
- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .skill`

真实 WorkBuddy MCP 与 Codex 插件事务仍需在用户指定的非生产国际版 Canva 设计上分别完成“审计 -> 预览 -> 用户确认 -> commit”验收；该外部验收不由本地单测替代。

## 1.0.7 - 2026-09-18

本次精准收口阶段2独立生图提示词：每份新请求固定使用“画面文字、页面设计、视觉风格、关键约束”四段。AI 主控负责按页选择、归并和表达PPT版式一致性与图片风格继承，runtime 不再把上游自然语言规则重新扩写进 prompt。

调整：

- `image_prompt_plan` 保持既有字段和来源摘要，但登记时不再自动追加 `PPT一致性.md`、共享组件、安全区或风格禁用项。
- `current_plan` 保留正文、来源摘要和冻结请求的确定性校验，不再要求上游每条自然语言规则逐条出现在计划中。
- 编译器将文字角色、版式规则、构图和页码自然归入 `【页面设计】`，将图片继承归入 `【视觉风格】`，将文字边界与本页高风险问题归入 `【关键约束】`。
- 正式规范与阶段1模板明确：页面设计继承PPT版式，视觉风格继承图片表现；不增加字数、规则数量或视觉质量硬门禁。
- 提示词格式版本升为3；待发送的旧格式请求须由主控重新整理并派发，历史成功提示词和图片保持不变。

验收：

- `python3 .skill/scripts/pptctl.py inspect-installation`
- `python3 .skill/scripts/pptctl.py validate-style-templates`
- `python3 .skill/scripts/pptctl.py validate-k12-subject-profiles`
- `python3 -m compileall -q .skill/scripts/runtime/ppt_skill_v3`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.skill/scripts/runtime:.skill/tests python3 -m unittest discover -s .skill/tests -v`
- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .skill`

## 1.0.6 - 2026-09-13

本次完成阶段2提示词按页编译与普通页标题改造：解决 `PPT一致性.md` 整章注入、普通页默认带章节标签、跨页映射进入 prompt、Markdown 残留和重复禁用项稀释本页重点的问题。

调整：

- 普通内容页默认只使用页面标题组件，不自动生成章节标签、眉题或模块导航条。
- `PPT一致性.md` 解析改为按页过滤：普通页、模块页、封面、目录、结束页和页码范围例外只返回当前页有效规则。
- 新增提示词规则清洗工具，统一处理 Markdown 标记、文档说明、跨页映射、未启用章节标签、未绑定 `chapter_tag` 安全区和同义禁用项归并。
- `image_prompt_plan` 只注入当前页有效规则；`current_plan` 改为语义类别覆盖校验，不再要求一致性原文逐条存在。
- final prompt 跨字段使用语义 key 去重，避免照片/3D、未批准文字、温暖积极等要求重复输出。
- doctor 增加新待发 prompt 污染检查；旧成功提示词文档仅 warning，不自动改写历史证据。
- 正式规范和阶段1模板同步：章节标签必须显式 opt-in；没有章节标签不再被 QA 误判为缺失。

验收：

- `python3 .skill/scripts/pptctl.py inspect-installation`
- `python3 .skill/scripts/pptctl.py validate-style-templates`
- `python3 .skill/scripts/pptctl.py validate-k12-subject-profiles`
- `python3 -m compileall -q .skill/scripts/runtime/ppt_skill_v3`
- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.skill/scripts/runtime:.skill/tests python3 -m unittest discover -s .skill/tests -v`
- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .skill`
- `python3 .skill/scripts/package_skill.py --output-dir .skill/dist`

## 1.0.5 - 2026-09-12

本次是 GitHub 发布后的维护入口精简：去掉重复维护文档，只保留一个用户和维护者都能看懂的维护说明。

调整：

- 将 `docs/维护规划.md` 的发布边界、GitHub 上传边界和维护原则合并进 `docs/维护说明.md`。
- 删除 `docs/维护规划.md`，正式包只保留 `docs/维护说明.md` 一个维护入口。
- 打包白名单改为只允许 `docs/维护说明.md` 进入包，继续排除测试、过程文档、归档文档、输入输出和 dist 产物。

验收：

- `python3 .skill/scripts/pptctl.py inspect-installation`
- `python3 .skill/scripts/pptctl.py validate-style-templates`
- `python3 .skill/scripts/pptctl.py validate-k12-subject-profiles`
- `python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .skill`
- `PYTHONPATH=.skill/scripts/runtime:.skill/tests python3 -m unittest discover -s .skill/tests -v`
- `python3 .skill/scripts/package_skill.py --output-dir .skill/dist`

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
