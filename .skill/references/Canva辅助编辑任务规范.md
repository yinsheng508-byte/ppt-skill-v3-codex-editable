# Canva 辅助编辑任务规范

## 定位

`/canva`、`/可画` 进入阶段外 Canva 辅助编辑任务。旧别名 `/canva编辑`、`/可画编辑`、`/可画AI编辑` 仅作为兼容识别，不新增独立流程。

默认流程：

```text
导入 PPT/PDF 到 Canva，或让用户手动上传
-> 用户在 Canva 手动执行 Magic Layers
-> 用户回传 Canva 编辑链接
-> Codex 使用 Canva 插件做支持范围内的文案和样式修正
```

Canva 辅助编辑不是阶段3，不替代阶段3。阶段3正式路线仍是基于用户确认锁定稿生成逐字稿、Word/PDF 和按需 K12 教案。

## 强边界

Canva 任务可以读取阶段1和阶段2作为参考，但不能改变 PPT 项目的阶段状态。

禁止：

- 不写 `_state/阶段3/*` 作为阶段3完成证据。
- 不写 `阶段3_逐字稿与教案输出/*`。
- 不设置 `project_state.confirmed.stage3_speaker_script=true` 或 `project_state.confirmed.stage3_lesson_plan=true`。
- 不写 `stage3_outputs_completed` 或 `stage4_deliverables_organized`。
- 不把 Canva 链接、Canva 设计或 Canva 导出稿自动冒充阶段3逐字稿、教案或阶段4整理产物。
- 不因为 Canva 任务完成就自动进入阶段3或阶段4。

如果用户明确要求“用 Canva 最终稿生成逐字稿/教案”，必须另行确认该导出稿是外部锁定稿，再按阶段3外部锁定稿规则处理。`/canva` 本身不默认产生阶段3锁定稿。

## 输入与来源

项目内调用时，先读取：

```text
_state/project_state.json
_state/阶段1/content.json
阶段1_规划确认/每页干净逐字稿.md
阶段1_规划确认/页面规划.md
阶段2_图片版PPT/pdf/<封面第一页主题>｜图片版PPT.pdf
阶段2_图片版PPT/img/
```

项目内权威来源：

- 文案以阶段1 `content.json`、`每页干净逐字稿.md` 和 `页面规划.md` 为准。
- 视觉以阶段2图片版 PDF 和阶段2页面图为参考。
- Canva 识别出的文本只作为待修改对象，不作为权威内容来源。

如果阶段1或阶段2缺失，先汇报缺口；不要借 Canva 任务补写阶段资产。

非项目调用时，如果用户只给 Canva 链接、PDF、PPTX 或图片，则作为普通 Canva 辅助编辑任务处理。没有权威文案时，只能做明显错别字、伪字、乱码和有限样式调整。

## 标准流程

1. 判断任务是否属于项目内 `/canva`。
2. 项目内任务读取阶段1权威文案和阶段2视觉参考。
3. 优先尝试通过 Canva 插件导入 PPT/PDF 为 presentation。
4. 插件不能接收当前文件时，让用户在 Canva 网页内手动上传。
5. 用户在 Canva 内手动执行 Magic Layers，并确认页面保留在同一个设计里。
6. 用户回传 Canva 编辑链接和已处理页码范围。
7. Codex 用 Canva 插件读取设计页数、缩略图和文本层。
8. 按页对齐阶段1文案和阶段2视觉参考。
9. 分批执行支持范围内的文本替换、样式调整、位置和尺寸调整。
10. 每批预览，用户确认后 commit；用户不确认则 cancel 或说明草稿未保存。
11. 输出 Canva 辅助编辑总结和人工待处理项。

## Canva 插件能力边界

可使用 Canva 插件能力：

- 导入 PDF/PPTX/HTML 等为 Canva 设计；PDF/PPTX 目标类型优先为 presentation。
- 读取设计信息、页数、页面缩略图和文本内容。
- 启动编辑 transaction。
- 替换整段文本或查找替换局部文本。
- 调整字号、粗细、斜体、颜色、对齐、行高、下划线和列表样式。
- 移动元素和缩放元素。
- 预览修改，并在用户确认后提交。

不能承诺：

- 不承诺直接批量调用多页 PDF 的 Magic Layers。
- 不承诺修改字体族或精确指定 font family。
- 不新增文本框。
- 不新增、删除或重排页面。
- 不修改背景色、渐变、复杂图形样式、动画、转场或透明度。
- 不把本机私有路径当作公开 URL 直接传给 Canva。
- 不为了上传文件而创建公共临时外链。

如果 Canva 插件不可见，先查找 Canva 插件工具；仍不可用时，说明需要连接或启用 Canva 插件，不切换到浏览器自动控制作为默认方案。

## 导入与 Magic Layers

只有文件是当前对话生成/上传的可传文件产物，或用户提供了现成公开 HTTPS URL，才直接交给 Canva 插件导入。对 `/Users/...`、`~/...`、Windows 本地盘等本机路径，不填到 URL 参数；插件无法导入时，让用户手动上传到 Canva。

Magic Layers 由用户在 Canva 内手动完成。用户完成后应回传：

- Canva 编辑链接。
- 已处理页码范围。
- 哪些页面 Magic Layers 失败或效果不好。

Codex 收到链接后检查设计能否访问、页数是否匹配、是否有可读文本层，以及是否仍有明显整页图片未拆分。如果文本层很少、页面仍不可编辑或页数不匹配，先让用户回 Canva 继续处理，不用 OCR 或猜测内容硬改。

## 文案和样式修正

文案修正优先级：

1. 错别字、伪字、乱码。
2. 漏字、多字、识别错词。
3. 标点、空格、断句。
4. 标题、要点、编号、单位和数字。
5. 因替换造成的溢出、遮挡或断行。

禁止用 Canva OCR 或 Magic Layers 识别文本覆盖阶段1文案；不把 Canva 中多出来的词擅自加入逐字稿；不因为 Canva 漏拆某些文字就删除阶段1内容；确需改内容时，返还给用户确认，不借 `/canva` 静默改阶段1合同。

样式目标是尽量贴近阶段2确认图，而不是让 Canva 自动重新设计。可调项限于插件支持的字号、粗细、斜体、颜色、对齐、行高、列表样式、文本框位置和大小。字体族、背景、复杂图形、漏拆文字、新增文本框、新增/删除/重排页面等写入人工待处理项。

## 批量编辑 transaction

每批修改遵循：

```text
start-editing-transaction
-> perform-editing-operations
-> 展示修改页缩略图
-> 用户确认
-> commit-editing-transaction
```

默认每批 3 到 5 页，复杂页每批 1 到 2 页。局部错字优先查找替换，整个文本框错乱时替换整段；样式、位置和尺寸只使用插件支持的操作。如果页面不支持对应操作，直接说明限制。

## 阶段外记录

项目内调用可先运行：

```bash
python3 .skill/scripts/pptctl.py create-canva-task-brief --run-dir <项目目录>
```

该命令只整理阶段1权威文案、阶段2图片版 PDF 路径、阶段2页面图路径和阶段外任务目录；不调用 Canva 插件，不上传文件，不修改阶段状态。

记录目录：

```text
_state/工具任务/canva/<task_id>/
```

推荐文件：

```text
task.json
import_attempt.json
design_link.json
reference_text_by_slide.json
page_audit.json
batch_edit_log.jsonl
manual_todos.md
```

这些文件只用于恢复和审计，不作为阶段门禁，不替代阶段3 manifest。

## Legacy 与完成汇报

旧浏览器自动点击 AI 图层路线已退出正式 Skill 包。用户明确要求这类浏览器控制时，先说明当前默认支持的是 Canva 插件或用户手动 Magic Layers 辅助流程；除非重新提供可维护执行器和验证依据，不要把浏览器自动点击包装成阶段3或默认 Canva 路线。

Canva 辅助任务完成后汇报 Canva 链接、页数、处理页码范围、已修正文案、已调整样式、未能处理的人工事项、是否已 commit 保存，以及阶段外记录目录。
