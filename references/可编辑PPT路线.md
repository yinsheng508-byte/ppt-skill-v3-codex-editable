# 可编辑 PPT 路线

## 正式路线

阶段3只承认坐标复刻可编辑重建路线：

```text
阶段1逐字稿
-> 阶段2确认图
-> text_unit_split_plan 拆细可编辑文字单元
-> text_ownership_map
-> 当前选定生图路线生成保真去字背景（默认 codex_image_gen，或显式 openai_image_api）
-> font_calibration_profile 单页真实填字 probe
-> 基于阶段2确认图精准识别/标注 editable_coordinate_plan
-> build-stage3-quality-profile / controller_review_plan.draft 主控复核
-> 用户确认文字坐标复刻
-> OfficeCLI builder 按坐标生成 PPTX
-> OfficeCLI readback 生成 coordinate execution report + 轻量 render review / 坐标 QA v2
-> runtime 正式入账，交付可编辑初稿
```

旧 `visual_slot_map + text_fill_plan 3.0 + preflight-stage3-overlay` 不再是本 Skill 的正式路线。旧产物只可作为历史排查资料，不能作为新项目通过依据。

可使用 `create-text-ownership-map-draft` 和 `create-editable-coordinate-plan-draft` 生成草稿以减少手写负担；draft 只能作为主控复核起点，`basis.status=draft` 的 coordinate plan 不能直接正式入账，必须由主控替换真实坐标并改成已复核版本后再运行 `record-editable-coordinate-plan`。

## 核心红线

- 必须从用户确认过的阶段2图片精准恢复文字几何坐标；`source_image.path` 必须指向阶段2确认图。
- 禁止从 OCR 或图片识别结果恢复文字内容。
- 所有可编辑文字必须来自阶段1内容资产，通常是 `_state/阶段1/content.json`。
- OfficeCLI builder 不得临时猜坐标、自动重排、用默认 title/body/footer 样式替代 coordinate plan。
- 拆字必须先写入 `_state/阶段3/text_unit_split_plan.json`；可编辑文字按独立视觉文本对象拆成 `split_unit` / `text_unit`，OfficeCLI 填字必须按 `text_unit_id` 逐个创建 PPT 原生文本对象，不得合并多个 text unit。
- 复杂页先用一页真实 OfficeCLI native style probe 校准字号倍率、行高倍率、字重和内边距；`font_calibration_profile` 和 `style_profile_id` 是主控判断字体策略的依据，未通过或未命中时写入 warning，不把坐标计划记录变成额外硬门槛。
- 阶段3 AI 质量画像只辅助主控识别风险页、native style probe 建议、builder warning 和 QA 覆盖缺口，不作为新的通过/失败门禁。
- 用户确认 `_state/阶段3/editable_coordinate_plan.json` 前，不得运行 `build-editable-brief` 或运行 OfficeCLI builder 填字。
- 没有真实 PPTX、provider evidence、tool_call、inspect、render review、coordinate execution report 和坐标 QA v2，不能进入阶段3用户确认。
- 阶段3交付的是可编辑初稿，不默认追求多轮自动像素级校准；明显错误拦截，细节允许人工后调。

## 阶段3顺序

1. 主控写 `_state/阶段3/text_unit_split_plan.json`，用阶段1每页干净逐字稿确认可编辑文字拆分粒度。
2. 可运行 `create-text-ownership-map-draft` 生成 ownership 草稿，主控复核页面信息文字和视觉内部文字的归属后，再用 `record-text-ownership-map` 正式入账；如果 split plan 存在，ownership 必须通过 `split_unit_id` 承接可编辑 split units。
3. 用 `dispatch-image-generation --stage stage3-background`（默认 `codex_image_gen`）或显式 `dispatch-image-api --stage stage3-background` 基于 ownership map 派生 `restore_targets`，生成保真去字背景。
4. 高风险页选择 1 页跑真实 OfficeCLI native style probe，并记录 `_state/阶段3/font_calibration_profile.json`；probe 结论用于主控校准，未 passed 时坐标计划可先记录但必须带 warning。
5. 可运行 `create-editable-coordinate-plan-draft` 基于 ownership、阶段2确认图和阶段3背景结果生成坐标草稿和预览；主控必须把草稿占位框替换为阶段2确认图上的真实文字坐标，确认不是 draft 后再用 `record-editable-coordinate-plan` 正式入账。
6. 运行 `build-stage3-quality-profile`，必要时再运行 `create-stage3-controller-review-plan-draft`，由主控复核密集页、未解决 warning、possible merged、native style probe 建议和 QA 高风险页候选；如决定不采纳建议，在 review plan 或 QA optional 字段中说明取舍。
7. 把文字坐标复刻结果交给用户确认；用户确认无误并记录 `approve_stage3_coordinate_plan_start_text_fill` 后，才进入填字。
8. 运行 `build-editable-brief`，brief 引用 split plan、ownership map、font profile 和用户确认后的 coordinate plan。
9. 运行 `build-officecli-coordinate-deck` 生成真实可编辑 PPTX，并输出 OfficeCLI manifest/readback/render review 证据。
10. 运行 `build-coordinate-execution-report --source officecli` 生成 schema_version=2.0 的 `_state/阶段3/text_fill_execution_report.json`。
11. 运行 `record-editable-deck` 入账正式 manifest。
12. QA 前刷新 `build-stage3-quality-profile`，必要时记录 `native_render_check.json`，然后运行 `record-coordinate-stage3-qa` 记录坐标 QA v2。普通页不要求多轮 native calibration，高风险页只做必要复核。

## 主控检查

提交用户确认前检查：

- PPTX 真实存在、页数正确、sha 已记录。
- manifest 记录 `text_ownership_map`、`editable_coordinate_plan`、OfficeCLI readback、render review、execution report、`officecli_manifest` 和 provider/tool evidence；新链路还应记录可选 `text_unit_split_plan`、`font_calibration_profile`、`native_style_probe`。
- execution report 覆盖全部 coordinate text units，且 `pptx_sha256` 与入账 PPTX 一致。
- `_state/阶段3/ai_quality/stage3_quality_profile.json` 已生成或刷新；如有 `controller_review_plan.draft.json`，最终 QA 应说明推荐高风险页的复核覆盖或接受理由。
- 坐标 QA v2 的 contact sheet、逐页渲染图和 checks 已通过。
- doctor 无 stage3 stale issue。
- 漏字、错字、数值单位错误、明显遮挡、明显溢出必须处理；细微字距、框宽、行高和局部对齐可以交给人工后调。
