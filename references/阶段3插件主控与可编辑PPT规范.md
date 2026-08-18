# 阶段3 OfficeCLI 主控与可编辑 PPT 规范

本文件是阶段3可编辑 PPT 的正式执行规范。阶段3目标是一次生成可编辑初稿，不把 AI 流程做成反复自动校准的慢系统。

文件名保留“插件主控”仅为兼容既有 SKILL 路由；正文正式口径以 OfficeCLI-only 为准。

## 责任边界

主控大模型负责：

- 判断当前阶段和用户确认状态。
- 写 `text_unit_split_plan.json` 和 `text_ownership_map.json`，并基于阶段2确认图精准识别/标注 `editable_coordinate_plan.json`。
- 为复杂页选择 1 页跑真实 OfficeCLI native style probe，用 `font_calibration_profile.json` 辅助固化字号、行高、字重和内边距策略；profile 未 passed 或 style profile 未命中时写 warning，由主控判断是否局部返工。
- 生成或读取 `_state/阶段3/ai_quality/stage3_quality_profile.json`，必要时生成 `controller_review_plan.draft.json`，用来调度高风险页复核、native style probe、返工或接受取舍；质量画像不是新的硬门禁。
- 在 OfficeCLI 坐标填字前把文字坐标复刻结果交给用户确认；用户未确认坐标前不得运行 OfficeCLI builder。
- 调用 OfficeCLI builder、OfficeCLI readback 和必要的渲染复核。
- 读取渲染图、OfficeCLI readback、coordinate execution report 和 QA，拦截明显错误；细微排版问题允许交付后人工后调。

OfficeCLI builder 负责：

- 按 brief 和 `editable_coordinate_plan` 生成真实 PPTX。
- 按 `text_unit_id` 逐个创建、逐个填入、逐个命名 PPT 原生文本对象；一个 text unit 对应一个文本对象，不能把多个 text unit 合并进同一个文本框。
- 优先使用 `text_unit.display_text` 填字；没有 `display_text` 时才使用 `text`。不得临时改写文案或自行断行。
- 按 `native_elements` 创建少量原生底形，如 badge、编号圆点、色条和简单线条，并按 `z_order` 放在文字下方或上方。
- 输出 OfficeCLI command evidence、PPTX、OfficeCLI manifest、readback、render review 和 coordinate execution report。
- 不决定阶段切换、用户确认或最终交付。

runtime 负责：

- 校验 PPTX sha、页数、证据字段、coordinate execution report 覆盖关系和 stale hash。
- 被动生成阶段3 AI 质量画像和主控 review plan draft，聚合 coordinate warning、font profile、execution report、OfficeCLI builder warning、QA 覆盖和阶段3决策线索。
- 记录 `_state/阶段3/manifests/editable_deck.json`。
- 不判断 PPT 好不好看，不自动改 PPT，不自动进入下一阶段。

## 标准节奏

1. 确认阶段2图片版 PDF 已经用户确认。
2. 记录 `_state/阶段3/text_unit_split_plan.json`，按独立视觉文本对象拆细可编辑文字。
3. 记录 `_state/阶段3/text_ownership_map.json`。
4. 基于 ownership map 生成阶段3保真去字背景。
5. 对复杂页跑 1 页真实 OfficeCLI native style probe，并记录 `_state/阶段3/font_calibration_profile.json`；probe 不是额外确认点，未 passed 时作为主控风险提示。
6. 基于阶段2确认图精准识别/标注文字坐标，记录 `_state/阶段3/editable_coordinate_plan.json`。
7. 运行 `build-stage3-quality-profile`，必要时运行 `create-stage3-controller-review-plan-draft`；主控据此决定是否补 probe、局部返工、扩大高风险页复核或接受某些人工后调项。
8. 把阶段3文字坐标复刻结果交给用户确认；用户确认无误并记录 `approve_stage3_coordinate_plan_start_text_fill` 后才继续。
9. 运行 `build-editable-brief`。
10. 运行 `build-officecli-coordinate-deck` 生成 PPTX、OfficeCLI manifest 和 readback。
11. 运行 `build-coordinate-execution-report --source officecli` 生成 coordinate execution report。
12. 运行 `record-editable-deck --provider officecli` 入账。
13. QA 前刷新 `build-stage3-quality-profile`；必要时运行 `record-native-render-check`，普通页可跳过或轻量记录，复杂页只拦截明显漂移、遮挡、溢出、漏字和错字。
14. 运行 `record-coordinate-stage3-qa`；QA 可引用 quality profile 和 review plan，通过后才交给用户确认可编辑 PPT。

## 正式 Manifest

正式 editable deck manifest 至少包含：

- `provider=officecli`
- `provider_evidence_id`
- `tool_call_id`
- `deck_path`
- `slides_count`
- `pptx_sha256`
- `runtime_evidence.text_ownership_map`
- 可选 `runtime_evidence.text_unit_split_plan`
- 可选 `runtime_evidence.font_calibration_profile`
- 可选 `runtime_evidence.native_style_probe`
- `runtime_evidence.editable_coordinate_plan`
- `runtime_evidence.officecli_manifest`
- `runtime_evidence.inspect`
- `runtime_evidence.render_review`
- `runtime_evidence.text_fill_execution_report`

`officecli_manifest.json` 至少包含：

- `provider=officecli`
- `officecli_version`
- `mode`
- `coordinate_plan`
- `pptx_source`
- `commands`
- `command_results`
- `background_placements`
- `text_shapes`
- `native_shapes`
- `readback`
- `warnings`
- `errors`

## OfficeCLI Builder 要求

OfficeCLI builder 必须：

- 背景 `exact_full_slide` 铺底，不使用会裁切的模式。
- 使用同一 `coordinate_canvas` 换算背景、文字和 native elements。
- 一个 `text_unit_id` 一个文本 shape，shape name 可追溯且优先等于 `text_unit_id`。
- 显式设置 `font.ea`、`font.latin`、`font.cs`、字号、颜色、字重、行距、内边距、水平对齐和垂直对齐。
- 默认 `autoFit=none`；如 `fit_policy.auto_shrink=false`，不得静默缩小文字。
- 输出 command evidence，默认使用 OfficeCLI batch；失败时不生成 passed manifest。
- readback 后记录每个 text unit 的 `shape_path`、`shape_id`、`shape_name`、`relative_box`、字体槽、字号、颜色、字重、行距、内边距和对齐。
- 可用 `PPT_PROBE_SLIDE_INDEX` 或 CLI 参数只跑一页 native style probe，但不得借此覆盖正式入账产物。

## 禁止事项

- 不让 runtime 自动替用户确认。
- 不在用户确认文字坐标复刻前运行 OfficeCLI builder 填字。
- 不把 OfficeCLI builder 自有 manifest 当正式 editable deck manifest；正式入账仍由 `record-editable-deck` 完成。
- 不生成或要求旧 `visual_slot_map/text_fill_plan` 作为新流程正式输入。
- 不用 OCR 从阶段2图片恢复文字内容。
- 不把 `stage3_quality_profile.json` 或 `controller_review_plan.draft.json` 当成替代用户确认、坐标 QA 或主控判断的自动通过条件。
- 不在缺少 OfficeCLI readback、render review、coordinate execution report 或坐标 QA v2 时交给用户确认。
- 不把多个独立 `text_unit`、多个 bullet、多个卡片或多个流程节点文字合并成一个文本框。
- 不用会裁切的方式铺阶段3背景；如果工具限制导致裁切，必须在 OfficeCLI manifest 中记录并视为需要返工。
