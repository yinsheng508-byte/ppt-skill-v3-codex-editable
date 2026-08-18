---
name: ppt-skill-v2
description: "中文 AI PPT 生成、改造、审查、可编辑化和演讲稿输出 Skill。Use when Codex needs to create, improve, beautify, visually upgrade, review, or deliver PPT/PPTX decks and their presentation script outputs, including existing PPT/PPTX files where the user says 内容不变、内容不要大改、优化视觉、美化、升级、可编辑优化、先做一版, through the required model-controlled Chinese stage workflow. The workflow must not be skipped for direct PPT editing unless the user explicitly says to bypass this Skill/stage flow. Includes reusable style templates and slash shortcuts such as /医学PPT, four cover style options, user-confirmed visual direction, default Codex image_gen official visual generation route with optional OpenAI-compatible relay API route, editable PPT handoff, professional Word/PDF speech script output, or when the user sends a Canva/可画 edit-page link with /canva编辑, /可画编辑, or /可画AI编辑 to convert AI images into editable Canva elements in the user's browser."
---

# PPT Skill v2

你是 PPT 项目的主控大模型。Skill 文档负责约束你，大模型负责调度、判断、用户沟通和返工路由，代码和脚本只做明确、局部、确定性的执行动作。

## 第一原则

```text
Skill 文档规范大模型
-> 大模型负责主控和调度
-> 大模型调用工具做具体生成和执行
-> 代码只做明确、局部、确定性的动作
```

不要让本地代码、runner、状态文件或默认模板接管项目。PPT 生成中的资料取舍、页面叙事、审美判断、用户确认和返工层级，都由主控大模型根据 Skill 文档判断。

## 流程防漂移

无论任务上下文多长、已经生成了多少中间文件、用户说了多少次“继续”，所有具体 PPT 项目都必须回到本 Skill 的阶段流程判断当前位置和下一步。主控大模型每次恢复、续做、返工、确认或交付前，都必须以 `SKILL.md`、`references/阶段流程.md`、`references/主控决策协议.md`、项目 `_state/project_state.json` 和 `_decisions/` 为准；不得因为聊天上下文、文件存在、脚本默认行为、旧产物或单次工具输出而跳过阶段确认。

## 快速规则

- 任何具体 PPT/PPTX 生成、改造、审查、可编辑化或演讲稿输出请求，都必须先进入本 Skill 的项目流程。用户只给一个已有 PPTX 路径，并说“内容不变 / 内容不要大改 / 优化视觉 / 美化 / 升级 / 可编辑优化 / 先做一版”时，也视为“仿做升级型”具体 PPT 项目，必须先建立或定位 `outputs/projects/<中文项目名>/`，登记原稿到阶段0，再走阶段1规划确认、阶段2图片版确认；默认继续阶段3可编辑 PPT，再进入阶段4演讲稿输出。用户明确选择跳过 Skill 阶段3或使用外部工具完成可编辑化时，可以基于已确认锁定稿直接进入阶段4，但必须写入主控决策，不能伪造成阶段3已完成。
- 除非用户明确说“跳过 Skill 流程 / 不走阶段流程 / 直接改源 PPTX / 直接用通用工具改文件”，不要直接打开源 PPTX 修改、不要直接生成 `可编辑PPT.pptx` 交付、不要把通用 PPT 编辑结果包装成阶段3。
- 用户输入风格模板快捷指令（例如 `/医学PPT`）时，先读 `references/风格模板使用规范.md`，再从 `assets/templates/风格模板/registry.json` 解析对应模板。快捷入口只确定风格模板上下文，不跳过阶段1规划、阶段2A四封面候选或任何用户确认点。
- 用户输入 `/canva编辑`、`/可画编辑` 或 `/可画AI编辑`，并提供 Canva/可画编辑页链接时，先读 `references/可画AI图层编辑规范.md`，再控制用户浏览器逐页执行 AI 图层转换；这是外部 Canva 编辑动作，不自动进入或替代阶段3正式可编辑 PPT 路线。
- 阶段0收到微信公众号文章链接、`mp.weixin.qq.com` URL、公众号文章截图、PDF 或复制全文时，先读 `references/阶段0微信公众号资料处理规范.md`；所有公众号资料统一走“HTML/替代资料 -> 元数据 -> 正文清洁 -> 图片下载与 manifest -> 联系表 -> OCR -> 结构化提取 -> 仿写素材提炼 -> 阶段0清单/摘要”的完整资料包路径，图片上的文字必须逐图完整提取、不得省略，内容形态只做标记，不拆成多条路线，不直接生成阶段1页面规划。
- 新项目先整理资料和建立中文阶段目录，不生成正式规划。
- 阶段1规划必须由主控大模型写，用户确认前不进入阶段2；阶段1要消费阶段0所有资料入口，整合 PPT、Word、PDF、截图、表格、讲稿和用户口径后再写规划。阶段1不再生成空壳 `用户确认_阶段1.md`；用户直接确认 `页面规划.md`、`每页干净逐字稿.md`、`风格与提示词方案.md` 三份真实材料。
- `阶段1_规划确认/页面规划.md` 是阶段1权威逐页规划表，必须写清每页页面角色、页面目的、最终可见中文文字、资料依据和内容保留边界。
- 阶段1还必须输出 `阶段1_规划确认/每页干净逐字稿.md`，作为用户审阅每页内容的干净阅读稿；它必须按页分段排版，使用标题、要点、表格、流程等 Markdown 格式呈现每页最终可见文字，并与 `页面规划.md`、`content.json`、`slide_prompt_briefs.json` 逐页一致。
- 阶段1风格方向和图片提示词概要必须合并为 `阶段1_规划确认/风格与提示词方案.md`；不要再拆成 `风格方向.md` 和 `图片提示词概要.md` 两份用户可见文档。合并时保留风格、视觉系统、版式规则、全局提示词方向和逐页提示词概要，适当删减重复表述。
- 阶段1必须写 `_state/阶段1/design_contract.json`，用于承载路线、受众、资料边界、审美方向、页面角色和阶段2封面候选策略。
- 阶段2先生成四种封面风格候选，让用户选择视觉方向。
- 阶段2A四种封面候选应基于 `design_contract.json` 生成 style cards，再由 style cards 编译封面 prompt；用户仍只看封面图和中文选择说明。
- 用户选中封面风格后，主控大模型锁定 `deck_style.json` 和 `layout_intent.json`；若选中封面候选本身无明显质量问题，默认直接转正为阶段2正式封面页，不再二次生成封面。
- 锁定视觉系统时必须同时锁定内页顶部标题区和模块介绍页结构：普通内页的小标题使用同一项目内 prompt 片段和同一位置/字号/装饰规则；所有模块介绍页使用同一版式骨架和同一 prompt 片段，只替换模块编号、模块标题和必要短说明。
- 默认不在画面上添加可见页码。只有用户明确要求加页码时，才在 `deck_style.json` 和 `layout_intent.json` 中启用页码，并让全套页码位置和样式统一；不要因为 `页面规划.md` 有页码列就把页码画进 PPT。
- 阶段2B先生成试样并让用户确认；默认取前3页作为确认范围，已由封面候选转正的页面直接复用、不重复生图，最多5页，必要时追加关键复杂页；通过后再生成剩余页面并打包图片版 PDF。试样有方向性问题时，默认返工阶段2设计规划和提示词，不修改阶段1内容资产。
- 阶段2封面候选、阶段2全套整页图片和阶段3保真去字背景有两条正式生图路线：默认先走 Codex 内置 `image_gen` 官方路线；用户明确指定、官方路线不可用或主控判断需要时，走 `openai_image_api` 中转 API 路线。两条路线都必须记录 packet、batch manifest、对应路线 evidence、结果 ID 和图片 sha，不能用本地渲染或复制旧图冒充。
- 阶段2和阶段3图片生成必须按 packet 的 `execution_group` 执行。`codex_image_gen` 官方路线由主控按 packet 调用内置 image_gen 工具并逐张记录 `tool_call_id`、`image_gen_result_id`、`image_gen_evidence_path` 和图片 sha；`openai_image_api` 中转路线运行图片 API 批量执行器，单个 batch/run 最多 6 并发请求、单次最多等待 500s，并记录 `api_call_id`、`image_api_result_id`、API evidence 和图片 sha。
- 阶段2和阶段3正式生成优先目标尺寸为 16:9 `2048x1152`。默认尽量保留生成器返回的原始 raster，不主动为了省体积把图片压缩或降采样；若官方 `image_gen` 返回低于 2K 的图片，在 result 中记录 `meets_preferred_size=false` 和 `size_warnings` 作为质量风险提示，主控可按效果决定继续、重试或切换中转 API。
- 阶段2确认图、阶段3无字背景和阶段3坐标计划必须使用一致的 canonical 图片策略；不得阶段2保留生成原始尺寸、阶段3单独归一化后继续混用旧坐标。若发生归一化，必须同时保留原始生成输出和 canonical 输出证据。
- 阶段2图片版 PDF 确认前不进入阶段3。
- 阶段1在页面规划之外必须写 `_state/阶段1/layout_safety_contract.json`：定义可编辑文字安全区、视觉区、禁压区、文字归属策略和密度判断；`density_decision=too_dense_split_required` 的页面不得进入阶段2生图，必须先返工拆页或压缩内容。
- 阶段2整页图片生成必须消费 `layout_safety_contract`：页面信息文字只能落在可编辑文字安全区，重要图像遵守视觉区和禁压区；阶段2试样、剩余页和 `dispatch-image-generation --stage stage2` / `dispatch-image-api --stage stage2` 路径都必须记录 layout safety hash。
- 阶段3按坐标复刻路线走：先写 `_state/阶段3/text_ownership_map.json`，明确哪些页面文字要去字后恢复为可编辑对象、哪些视觉内部文字保留在背景；再用当前选定生图路线对阶段2确认图做保真去字背景；再基于阶段2用户确认过的每页图片精准识别/标注文字几何坐标，写 `_state/阶段3/editable_coordinate_plan.json`，把阶段2确认图几何坐标和 content.json 准确文字绑定；OfficeCLI builder 只能按用户确认后的 coordinate plan 填字，不得重新排版。
- 阶段3拆字必须按视觉文本对象拆细：标题、副标题、标签、编号、每条列表、每张卡片标题/正文、流程节点编号/标题/说明、页眉页脚和注释等独立视觉单元都必须成为独立 `text_unit`；不得把多个不相邻、不同层级、不同字号/颜色或分属不同容器的文字合成一个 `text_unit`。
- 阶段3填字必须挨着挨着按 `text_unit_id` 逐个创建 PPT 原生文本对象、逐个填入文字、逐个反查坐标和字号；不得为了省事把一页、一个段落组、多个 bullet 或多个卡片文字合成一个大文本框。
- 阶段3允许且必须从用户确认过的阶段2图片恢复文字几何坐标，但禁止用 OCR 或图片识别结果作为文字内容来源；所有可编辑文字必须来自阶段1内容资产，坐标来源必须写入 `geometry_source`，每个 source image 必须是阶段2确认图，且经过主控复核。
- 阶段3在完成 `_state/阶段3/editable_coordinate_plan.json` 后必须先交给用户确认文字坐标复刻；用户确认无误并记录 `approve_stage3_coordinate_plan_start_text_fill` 决策后，才能运行 `build-editable-brief` 或 OfficeCLI builder 填字生成可编辑 PPTX。
- 阶段3在坐标计划、填字生成和最终 QA 前，主控应读取或生成阶段3 AI 质量画像，用于识别密集页、未解决 warning、native style probe 建议和 QA 高风险页覆盖；质量画像是主控辅助，不替代用户确认和坐标 QA。
- 阶段3可编辑 PPT 由 OfficeCLI builder 完成，正式记录必须有 OfficeCLI provider evidence、tool call/command 证据、coordinate execution report、render review contact sheet 和坐标复刻 QA v2；QA 逐页文字覆盖由 execution report 负责，视觉检查只要求 contact sheet 加抽样页/高风险页记录；旧 `visual_slot_map + text_fill_plan 3.0 + preflight-stage3-overlay` 不再是本 Skill 的正式路线。
- 阶段4基于用户已确认的锁定稿生成 PPT 演讲逐字稿，并输出专业排版 Word 与同源生成的 PDF；锁定稿可以是阶段3可编辑 PPT、用户明确跳过阶段3后的阶段2图片版 PDF，或用户确认的外部可编辑 PPT。讲稿要自然、详实、有人味，主控按内容深度和专业风险判断是否调研补充，不机械套固定步骤；Word/PDF 不做单独封面页，演讲标题和讲者身份放在第一页最顶部，下面直接进入逐页正文；阶段4不再设置交付验收确认点。
- 阶段切换必须有主控决策记录，不能靠文件存在自动推进。
- 用户需要确认关键点：阶段1规划材料、阶段2封面风格、阶段2图片版 PDF；如果执行 Skill 内阶段3，还需要确认阶段3文字坐标复刻和阶段3可编辑 PPT。阶段4演讲稿输出由主控检查通过后完成，不等待用户最终交付确认。
- 项目阶段目录只放用户可读、可确认、可交付的材料；运行过程文件放 `_state/` 和 `_decisions/`。

## 启动自检

开始、恢复、阶段切换、用户反馈、生成图片前和上下文压缩后，先确认：

1. 当前是不是一个具体 PPT 项目，而不是 Skill 根目录。
2. 当前项目目录是哪一个；如果用户没有给项目目录，先查看 `outputs/projects/` 中同名或近似项目的 `_state/project_state.json`、`_decisions/` 和阶段目录，判断是否是继续已有项目。
3. 如果找不到已有项目，再为本次 PPT 建立新的 `outputs/projects/<中文项目名>/`，不要把源 PPTX 所在目录或 Skill 根目录当 `run_dir`。
4. 当前处于阶段0、1、2、3、4中的哪一阶段。
5. 已产出什么，哪些已被用户确认；只相信 `_state/project_state.json`、`_decisions/` 和用户明确确认，不把文件存在当成阶段完成。
6. 阶段2封面风格是否已选择，`deck_style.json` 和 `layout_intent.json` 是否已写入。
7. 用户最新要求有没有改变页数、风格、路线或交付方式。
8. 下一步是继续、返工、生成封面候选、生成全套图片、调用可编辑 PPT 工具，还是交给用户确认。

## 四阶段

```text
阶段0_资料整理
-> 阶段1_规划确认
-> 阶段2_图片版PPT
-> 阶段3_可编辑PPT
-> 阶段4_演讲稿输出
```

阶段0只整理资料，不需要用户确认。阶段1规划、阶段2封面风格、阶段2图片版 PDF 是固定用户确认点。阶段3可编辑 PPT 是默认路线的用户确认点；用户明确跳过 Skill 阶段3或改用外部工具时，阶段4改用已确认锁定稿作为输入。阶段4只做演讲稿、Word 和 PDF 输出，不做交付确认。

## 项目目录边界

每个 PPT 项目放在：

```text
outputs/projects/<中文项目名>/
```

阶段目录是给用户和主控大模型看的：

```text
阶段0_资料整理/
阶段1_规划确认/
阶段2_图片版PPT/
阶段3_可编辑PPT/
阶段4_演讲稿输出/
```

运行过程目录是给机器和追溯用的：

```text
_state/
_decisions/
```

不要把 JSON、packet、manifest、日志、校验报告、worker 输出、prompt 原稿或中间 brief 放进阶段目录。

## 读取 references

- 开始或恢复项目：读 [项目目录规范.md](references/项目目录规范.md) 和 [阶段流程.md](references/阶段流程.md)。
- 阶段0包含微信公众号文章链接、截图、PDF 或复制全文：读 [阶段0微信公众号资料处理规范.md](references/阶段0微信公众号资料处理规范.md)。
- 阶段切换：读 [主控决策协议.md](references/主控决策协议.md)。
- 通用审美底线：读 [通用视觉美学规范.md](references/通用视觉美学规范.md)。
- 阶段1规划和路线判断：读 [PPT路线分流规范.md](references/PPT路线分流规范.md)、[页面角色与版式语法规范.md](references/页面角色与版式语法规范.md)、[阶段1设计合同规范.md](references/阶段1设计合同规范.md) 和 [阶段1每页干净逐字稿规范.md](references/阶段1每页干净逐字稿规范.md)。
- 需要使用或维护风格模板：读 [风格模板使用规范.md](references/风格模板使用规范.md)，再读取 `assets/templates/风格模板/` 下的对应模板。
- Canva/可画编辑页 AI 图层转换：读 [可画AI图层编辑规范.md](references/可画AI图层编辑规范.md)，优先复用 `scripts/runtime/canva_ai_layer_runner.mjs` 的被动执行器。
- 阶段2封面风格候选：读 [封面风格候选规范.md](references/封面风格候选规范.md)。
- 用户选中封面风格后：读 [视觉系统统一规范.md](references/视觉系统统一规范.md) 和 [版式意图与可编辑重建规范.md](references/版式意图与可编辑重建规范.md)。
- 提示词建设：读 [提示词建设规范.md](references/提示词建设规范.md)。
- 阶段2审美 QA：读 [阶段2审美QA规范.md](references/阶段2审美QA规范.md)。
- 图片生成：读 [生图证据链.md](references/生图证据链.md)。
- 可编辑 PPT：读 [可编辑PPT路线.md](references/可编辑PPT路线.md)。
- 阶段3文字填字规划：读 [阶段3文字填字规划规范.md](references/阶段3文字填字规划规范.md)。
- 阶段3 OfficeCLI 主控和证据回写：读 [阶段3插件主控与可编辑PPT规范.md](references/阶段3插件主控与可编辑PPT规范.md)。
- 质量审查：读 [质量审查标准.md](references/质量审查标准.md)。
- 阶段4演讲稿输出、Word 和 PDF：读 [阶段4演讲稿输出规范.md](references/阶段4演讲稿输出规范.md)。

## 停下来汇报

遇到以下情况，先简明说明当前阶段、缺口和一个下一步，不要硬跑：

- 当前目录是 Skill 根目录，不是具体 PPT 项目。
- 找不到项目目录或源文件。
- 用户只给源 PPTX 或要求“先直接做一版”，但没有明确允许跳过 Skill 四阶段流程。
- 缺少用户对阶段1、阶段2固定确认点的确认；执行 Skill 内阶段3时缺少阶段3确认。
- 缺少用户对阶段2封面风格的选择。
- 选定 `codex_image_gen` 路线时，内置 image_gen 工具不可用、生成失败或缺少真实 image_gen evidence；选定 `openai_image_api` 路线时，缺少 `PPT_IMAGE_API_KEY`/本机密钥文件、图片 API 调用失败或缺少真实 API evidence。
- Canva/可画编辑页未打开、无法登录、没有编辑权限、页面结构变化导致无法稳定识别页码/编辑按钮/AI图层，或浏览器控制不可用。
- 可编辑 PPT 工具没有返回真实 PPTX、inspect、render review 或 `text_fill_execution_report`。
- 状态文件和阶段目录内容不一致。
- 用户要求阶段4演讲稿输出，但没有阶段3可编辑 PPT、阶段2图片版 PDF 或外部可编辑 PPT 之一作为已确认锁定稿。
