# Canva 辅助编辑任务规范

## 定位与路由

`/canva`、`/可画` 都表示**国际版 Canva**的阶段外辅助编辑任务；旧别名 `/canva编辑`、`/可画编辑`、`/可画AI编辑` 仅作兼容识别，不新增流程。它们不接入、不探测中国版可画。

Canva 辅助编辑不是阶段3，不替代阶段3。阶段3仍以用户确认的锁定稿为输入，生成逐字稿、Word/PDF 和按需 K12 教案。

执行器只影响工具调用，不影响业务流程、阶段边界、权威来源和直接提交纪律：

| 条件 | 执行器 | 处理 |
|---|---|---|
| WorkBuddy，当前会话中完整 `mcp__canva__*` 编辑工具可用 | `canva_mcp` | 走 Canva MCP 路线 |
| Codex，当前会话中 Canva 插件可用 | `canva_plugin` | 走 Canva 插件路线 |
| WorkBuddy MCP 或 Codex 插件不可见、未授权或无设计编辑权限 | `manual_handoff` / `blocked_connector` | 提示用户连接、OAuth 或手动处理；不得虚报可编辑任务完成 |

宿主 profile 只用于选择首选执行器：`CODEBUDDY.md` 代表 WorkBuddy，`AGENTS.md` 代表 Codex。真正选择必须先探测当次工具与授权状态；Python runtime 不得仅凭 profile 猜测 MCP 已可用。

默认流程：

```text
工具/授权 preflight
-> 创建阶段外 task brief，记录 provider、host、executor
-> 用户导入或回传 Canva 编辑链接
-> 用户手动 Magic Layers
-> AI 主控逐页理解页面角色、阶段1权威文案和阶段2视觉参考
-> 形成可回读的页级审计与修订计划
-> 小批执行文本/样式修正
-> AI 回读并核验本批每页预览
-> 直接 commit
-> 重新读取已保存结果并写审计记录
```

在用户触发 `/canva`、`/可画` 或明确要求 Canva 修订时，两个宿主都拥有**本次允许范围内的直接提交授权**：不得再因等待逐批主动确认而暂停。直接提交不等于跳过校验，也不扩大可编辑范围；无法通过回读核验、无编辑权限或不在支持范围内的事项仍必须 cancel 或转人工。

这不是纯机械脚本流程。AI 主控要先理解这一页要表达什么、哪些文字是权威内容、哪些视觉层级来自阶段2参考，再决定“该修什么、能不能修、修到什么程度”。`page_audit.json` 和 runtime 校验只是留下证据并阻止无依据提交，不能替代主控的页面理解和审美判断。

## 强边界

Canva 任务可以读取阶段1和阶段2作为参考，但不能改变 PPT 项目的阶段状态。

禁止：

- 不写 `_state/阶段3/*` 作为阶段3完成证据。
- 不写 `阶段3_逐字稿与教案输出/*`。
- 不设置 `project_state.confirmed.stage3_speaker_script=true` 或 `project_state.confirmed.stage3_lesson_plan=true`。
- 不写 `stage3_outputs_completed` 或 `stage4_deliverables_organized`。
- 不把 Canva 链接、Canva 设计或 Canva 导出稿自动冒充阶段3逐字稿、教案或阶段4整理产物。
- 不因为 Canva 任务完成就自动进入阶段3或阶段4。
- 不用 Canva 文本层、OCR 或 Magic Layers 识别结果覆盖阶段1权威文案。
- 不把本机私有路径当作 URL 传给 Canva，不为上传制造公共临时外链。

如果用户明确要求“用 Canva 最终稿生成逐字稿/教案”，必须先确认该导出稿是外部锁定稿，再按阶段3外部锁定稿规则登记为 `external_locked_deck`。`/canva`、`/可画` 本身不默认产生阶段3锁定稿。

## 输入与权威来源

项目内调用前读取：

```text
_state/project_state.json
_state/阶段1/content.json
阶段1_规划确认/每页干净逐字稿.md
阶段1_规划确认/页面规划.md
阶段2_图片版PPT/pdf/<封面第一页主题>｜图片版PPT.pdf
阶段2_图片版PPT/img/
```

每页审计时的优先级：

1. `_state/阶段1/content.json` 中该页 `final_visible_text` 是最终可见文案首要权威。
2. `每页干净逐字稿.md` 复核标题、要点、编号、单位、数字和断句。
3. `页面规划.md` 判断页面角色和应该突出的信息层级。
4. 阶段2 PDF 与对应页面图是颜色、字号关系、粗细、对齐和留白的视觉参考。
5. Canva richtext 只作为待修改对象，不是文案权威。

若项目内阶段1或阶段2资产缺失，先汇报缺口，不借 Canva 任务补写阶段资产。非项目调用仅可做明显错别字、伪字、乱码与有限样式修正；没有权威文案时不得声称完成逐字稿校验。

## 导入、链接与 Magic Layers

1. 用户已回传国际版 Canva 编辑链接时，优先使用该设计。
2. 链接遗失时，只有执行器具备搜索能力且授权允许，才按项目名/课件标题搜索**已有**设计；搜索不创建新设计。
3. 仅当前对话可传文件或用户提供的公开 HTTPS URL 可以由执行器导入。本机文件由用户手动上传。
4. Magic Layers 由用户手动完成。用户应回传编辑链接、已处理页码范围、失败页或效果不佳页。
5. 读取设计后检查页数、编辑权限、文本层和是否仍有整页图片。文本层很少、仍不可编辑或页数不符时，让用户继续处理；不 OCR 猜测，不硬改。

## AI 主控的逐页文案与视觉校验

这一节是给 AI 主控执行的**逐页合同**，不是泛泛的检查建议，也不是脱离上下文的机械勾选表。每一页都必须先建立“阶段1权威文案 -> Canva 页面”的映射，由主控结合页面角色、信息重点和阶段2视觉参考判断修订策略，再把判断结果写入 `page_audit.json`；没有合格 page audit，不得对该页执行操作或 commit。不得记录签名缩略图 URL。

### 每页执行卡（AI 主控按页判断并留证）

1. **定位页**：用页序将 `content.json.slides[].slide_index` 映射到一个 Canva `canva_page_id`，记录 `is_editable`、`is_responsive`。页数不一致、文本层不可读或仍是整页图片，停止该页，写 `waiting_manual_magic_layers` 或人工待办。
2. **取得唯一权威文字**：读取同一 `slide_index` 的 `content.json.final_visible_text`，原样写为 `expected_text`；`每页干净逐字稿.md` 只用于复核标题、编号、单位、数字、标点和断句。不得改写、归纳、调换顺序，`expected_text` 必须逐项完全等于 `final_visible_text`。
3. **逐对象文案比对**：读取该 Canva 页的文本对象，写入 `current_text`；逐项比较标题、正文、要点、编号、单位、数字、标点、空格和断句。每个差异写为 `findings[]` 的“类别 + 当前文字 + 期望文字”，并指定最小 `proposed_operations`；不以 OCR 猜测替代文本对象读取。
4. **逐对象视觉比对**：主控先判断该页的信息层级与视觉意图，再以同页阶段2 PDF/页面图为参照，对标题、正文、要点、图注/页脚分别检查层级、字号、粗细、颜色、对齐、行高、列表样式、最小位置/尺寸，以及替换后的溢出、遮挡、断行。每项写为 `visual_checks[]`：`role`、`attribute`、`before`、`target`、`after`、`status`。
5. **分流**：可由当前执行器安全完成的文字和文字样式修正进入批次；字体族、背景、复杂形状、动画、增删内容、换图/填充、页面重排和响应式页不支持操作写入 `manual_todos`，不为了“完成”而越权修改。
6. **操作后回读**：执行后再次读取同页文本与预览。`copy_check.post_edit_text` 必须逐项完全等于 `expected_text`，才可标为 `copy_check.status=pass`；任何未修复文案差异为 `needs_edit/blocked`，不得 commit。
7. **视觉闭环**：每个 `visual_checks[]` 必须有 `pass`、`not_applicable` 或 `manual_todo` 等明确结果，并能说明为什么已经贴近阶段2参考或为什么只能转人工。仍为 `needs_edit` 或 `blocked` 的视觉检查，不得 commit；人工待办不等于已修复。
8. **直接提交与回读**：AI 复核本批预览后，以 `confirmation_status=pre_authorized` 直接 commit；提交后重新只读检查保存结果，记录 committed 状态、已修正清单和剩余人工待办。这里不等待用户再次确认。

**该页通过条件**：`expected_text` 与阶段1权威文字完全一致；`copy_check.status=pass` 且 `post_edit_text` 完全一致；所有视觉检查已收口且没有 `needs_edit/blocked`；当前批次已 committed。缺任一项只能继续修复、cancel 或转人工，不得报告该页已完成。

主控判断顺序与允许操作：

| 优先级 | 校验项 | 允许操作 |
|---|---|---|
| 1 | 错别字、伪字、乱码 | 局部查找替换；匹配文本带足够上下文，避免误伤重复文字 |
| 2 | 漏字、多字、识别错词 | 先定位文字对象；整框确实错乱才整段替换 |
| 3 | 标点、空格、断句 | 依阶段1权威文案替换，不改变内容结论 |
| 4 | 标题、要点、编号、单位和数字 | 逐项比对 `final_visible_text` 与逐字稿 |
| 5 | 字号、粗细、颜色、对齐、行高、列表样式 | 调整已有文本对象，使其贴近阶段2视觉参考 |
| 6 | 标题/正文/注释层级 | 仅借已有文本对象的格式和最小位置/尺寸修复恢复层级 |
| 7 | 替换造成的溢出、遮挡、断行 | 仅做最小位置/尺寸修复，不主动重排版 |

不能承诺：

- 不承诺批量调用 Magic Layers。
- 不承诺修改字体族或精确 font family。
- 不新增文本框、页面，不删除或重排页面。
- 不修改背景色、渐变、复杂图形样式、动画、转场或透明度。
- 不主动重新设计页面。

涉及新增/删除文本内容、`delete_element`、换图、填充/素材、背景或主动重排版的事项，写入 `manual_todos.md`，不在本次允许范围内执行。MCP 响应式页只使用服务端明确允许的 operation；不支持的样式/层级问题转人工。

## 分批 transaction 与直接提交纪律

每批默认5页；最后不足5页时按剩余页处理。AI 主控完成允许范围内修订并回读通过后直接 commit，不等待用户确认：

```text
按页审计并形成差异清单
-> start-editing-transaction
-> perform-editing-operations
-> 获取并由 AI 主控回读本批每页缩略图/预览
-> commit-editing-transaction
-> 重新读取已保存页面
```

- `/canva`、`/可画` 的本次修订请求即为本范围内的 commit 预授权；不等待逐批主动确认。预览用于 AI 自检和审计，而不是新增用户门禁。
- 复杂页也默认进入5页批次；如工具限制、页面结构变化或回读失败导致该批无法闭环，应 cancel 后重新读取现状，不把草稿当作已保存结果。
- 预览异常、回读文字不等于权威文字、视觉检查未收口、工具失败或 transaction 失效时，必须 cancel；草稿不得称为已保存。
- transaction id 必须用启动调用返回的原值，不能跨批混用。
- 大设计先分页只读校验；不把整套 richtexts/fills 原文复制到任务记录。
- 连续工具失败、并发编辑导致 transaction 失效或页面结构变化时，停止批量操作、cancel、重新读取当前页面并向用户汇报。

## 执行器差异

### WorkBuddy：Canva MCP

- `canva_mcp` 仅在完整 `mcp__canva__*` 编辑能力可见、OAuth 已完成且设计具备编辑权限时使用。
- 可用范围限于读取设计/页面/文本、editing transaction、文本替换、文本格式、最小位置/尺寸修复、预览、commit/cancel和按需导出。
- `generate-design`、`create-design-from-candidate`、`upload-asset-from-url`、`update_fill`、`insert_fill`、协作评论与品牌套件不进入 PPT 项目正式流程。
- `export-design` 只产生 Canva 导出候选稿；签名导出/缩略图 URL 有时效，只记录设计 ID、格式、页范围和时间。

### Codex：Canva 插件

- `canva_plugin` 仅在插件实际可用时使用。
- 使用插件相应的导入、读取、transaction、文本替换、文本格式、移动/缩放、预览和 commit/cancel能力。
- 插件不可见时说明需要连接或启用插件；不默认切到浏览器自动控制。

## 阶段外记录与恢复

项目内先运行：

```bash
python3 .skill/scripts/pptctl.py create-canva-task-brief --run-dir <项目目录> --provider canva_international --host-profile <codex|workbuddy> --executor <canva_mcp|canva_plugin>
```

该命令只创建阶段外 brief，不调用 Canva、不上传文件、不修改阶段状态。无法完成 preflight 时可创建 `--executor unresolved` 的 brief；不可把未知能力记录成可用 MCP。

记录目录：

```text
_state/工具任务/canva/<task_id>/
  task.json                       # provider、host_profile、executor、selection_basis
  import_attempt.json             # 设计获取记录，执行器无关
  design_link.json
  reference_text_by_slide.json
  page_audit.json                 # 逐页权威文案与视觉校验
  batch_edit_log.jsonl            # 批次、操作、预览、commit/cancel结果
  manual_todos.md
  export_record.json              # 仅实际导出时写入
```

这些文件只用于恢复和审计，不作为阶段门禁，不替代阶段3 manifest。恢复摘要应展示任务的 provider、executor、状态、最后批次状态和人工待办数量，但不改变项目的 `next_action`。

### 记录字段与状态合同

- 新 task 使用 schema v1.2。`page_audit.json` 初始为 `not_started`；每个页记录必须包含 `slide_index`、`canva_page_id`、`is_editable`、`is_responsive`、按权威优先级列出的 `authority_sources`、`expected_text`、`current_text`、`copy_check`、`findings`、`proposed_operations`、`visual_checks` 和 `manual_todos`。`authority_sources` 必须包含 `stage1_content`；`expected_text` 与 passed `copy_check.post_edit_text` 必须逐项等于该页 `final_visible_text`。
- 每个 `batch_edit_log.jsonl` 记录包含批次、页码、操作类型、transaction 状态、预览状态、commit 授权状态和本批页审计。一个批次只能先记录 `draft`，再以 `committed`、`cancelled` 或 `failed` 收口；直接 commit 必须有 `preview_status=reviewed_by_controller` 与 `confirmation_status=pre_authorized`。`confirmed` 仅是历史记录兼容值，不再是新批次门槛。不得记录 transaction id、完整 richtext/fill 原文、签名缩略图 URL 或签名导出 URL。
- `manual_todos.md` 的开放项格式为 `- [open] 页：<页码或未指定> | 类型：<分类> | 原因：<说明> | 授权：<是/否>`。Magic Layers、字体族、背景、复杂形状、动画、页面重排、增删内容、换图/填充和响应式页不支持操作都必须留在此处，不能通过“completed”掩盖。
- 只有发生实际导出尝试时写 `export_record.json`；每条仅记录设计 ID、格式、页范围、`exported|failed|cancelled` 结果和记录时间，绝不保存导出链接或本机落盘路径。

项目内可用以下确定性记录命令；它们只写当前 task 目录，不能调用 Canva、不能改变项目阶段状态：

```bash
python3 .skill/scripts/pptctl.py record-canva-task-event --run-dir <项目目录> --task-id <task_id> --event-json '<batch_event_json>'
python3 .skill/scripts/pptctl.py record-canva-task-export --run-dir <项目目录> --task-id <task_id> --export-json '<export_record_json>'
```

旧 `schema_version=1.0` 任务没有 executor 时只能只读识别为 `legacy_plugin_inferred`，不得自动回写旧文件。

## 完成汇报

每次完成或阻断都说明：

- 执行器和宿主，或 `blocked_connector/manual_handoff` 原因。
- Canva 设计 ID/链接、总页数和处理页码范围。
- 每页权威文案校验范围，已修正的“原文 -> 修正”清单。
- 已调整的字号、颜色、粗细、对齐、行高或层级清单。
- 每批 AI 主控回读预览、直接 commit/cancel 和提交后回读状态。
- 导出候选稿状态（如有），但不把它称为阶段3锁定稿。
- 未能处理的人工待办和阶段外记录目录。
