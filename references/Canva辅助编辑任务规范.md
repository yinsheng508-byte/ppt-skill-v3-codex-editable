# Canva 辅助编辑任务规范

## 定位

当用户使用 `/canva`、`/可画`，或旧兼容别名 `/canva编辑`、`/可画编辑`、`/可画AI编辑` 时，进入阶段外 Canva 辅助编辑任务。

该任务的目标是：

```text
插件导入 PPT/PDF 到 Canva 或让用户手动上传
-> 用户在 Canva 手动执行 Magic Layers
-> 用户回传 Canva 编辑链接
-> Codex 使用 Canva 插件批量修正文案和样式
```

这不是阶段3，不替代阶段3。阶段3正式路线仍以 `可编辑PPT路线.md` 和 `阶段3插件主控与可编辑PPT规范.md` 为准。

## 强边界

Canva 辅助编辑任务可以读取阶段1和阶段2作为参考，但不能改变 PPT 项目的阶段状态。

禁止：

- 不写 `_state/阶段3/*`。
- 不写 `阶段3_可编辑PPT/*`。
- 不设置 `project_state.confirmed.stage3_editable_deck=true`。
- 不写 `approve_stage3_coordinate_plan_start_text_fill`。
- 不写 `approve_stage3_start_script_output`。
- 不把 Canva 链接或 Canva 设计冒充 `阶段3_可编辑PPT/ppt/可编辑PPT.pptx`。
- 不因为 Canva 任务完成就自动进入阶段4。

如用户后续明确要求“使用 Canva 最终稿进入阶段4”，必须另行确认，并按阶段4外部锁定稿规则处理。`/canva` 本身不默认产生阶段4锁定稿。

## 触发与输入

### 项目内调用

如果当前有明确 PPT 项目，先读取：

```text
_state/project_state.json
阶段1_规划确认/每页干净逐字稿.md
_state/阶段1/content.json
阶段2_图片版PPT/pdf/图片版PPT.pdf
阶段2_图片版PPT/img/
```

项目内调用的权威来源：

- 文案以阶段1逐字稿和 `_state/阶段1/content.json` 为准。
- 视觉以阶段2图片版 PDF 和阶段2页面图为准。
- Canva 识别出的文本只作为当前待修改对象，不作为内容来源。

如果阶段1或阶段2缺失，先汇报缺口；不要借 Canva 任务补写阶段资产。

### 非项目调用

如果用户只给 Canva 链接、PDF、PPTX 或图片，但没有项目目录：

- 作为普通 Canva 辅助编辑任务处理。
- 需要用户提供权威文案参考，才能做逐字稿级校对。
- 没有权威文案时，只能做明显错别字、伪字、乱码和有限样式调整。

## 标准流程

```text
1. 判断任务是否属于项目内 /canva。
2. 项目内任务读取阶段1文案和阶段2图片版 PDF。
3. 优先尝试通过 Canva 插件导入 PPT/PDF 为 Canva presentation。
4. 如果插件不能接收当前文件，提示用户手动上传到 Canva。
5. 用户在 Canva 里手动执行 Magic Layers，并确认所有页保留在同一个设计里。
6. 用户把 Canva 编辑链接复制回来。
7. Codex 用 Canva 插件读取设计页数、缩略图和文本层。
8. 按页对齐阶段1文案和阶段2视觉。
9. 分批执行文本替换、样式调整、位置和尺寸调整。
10. 每批展示预览，请用户确认。
11. 用户确认后 commit；用户不确认则 cancel 或说明草稿未保存。
12. 输出本次 Canva 辅助编辑总结和人工待处理项。
```

## Canva 插件能力边界

可使用 Canva 插件能力：

- 导入 PDF/PPTX/HTML 等为 Canva 设计；导入 PDF/PPTX 时目标类型优先选 presentation。
- 读取设计信息、页数、页面缩略图和文本内容。
- 启动编辑 transaction。
- 替换整段文本。
- 查找替换局部文本。
- 调整字号、粗细、斜体、颜色、对齐、行高、下划线和列表样式。
- 移动元素。
- 缩放元素。
- 预览修改并在用户确认后提交。

不能承诺：

- 不承诺直接批量调用多页 PDF 的 Magic Layers。
- 不承诺修改字体族或精确指定 font family。
- 不新增文本框。
- 不新增、删除或重排页面。
- 不修改背景色、渐变、复杂图形样式、动画、转场或透明度。
- 不把本机私有路径当作公开 URL 直接传给 Canva。
- 不为了上传文件而创建公共临时外链。

如果 Canva 插件不可见，先查找 Canva 插件工具；仍不可用时，说明需要连接或启用 Canva 插件，不切换到浏览器自动控制作为默认方案。

## PDF/PPTX 导入规则

优先尝试插件导入：

```text
工具意图：把阶段2图片版 PPT/PDF 导入 Canva，作为 presentation 设计。
输入：阶段2图片版 PDF 或用户提供的 PPT/PDF。
输出：Canva 设计链接或 design_id。
```

安全要求：

- 只有文件是当前对话生成/上传的可传文件产物，或用户提供了现成公开 HTTPS URL，才直接交给 Canva 插件导入。
- 对 `/Users/...`、`~/...`、Windows 本地盘等本机路径，不把路径填到 URL 参数。
- 不建议、不中转、也不默认创建公共临时下载链接。
- 插件无法导入时，停下来让用户在 Canva 网页内手动上传该文件。

手动上传时提醒用户：

- 选择阶段2图片版 PDF 或用户指定文件。
- 尽量让所有页面进入同一个 Canva presentation 设计。
- 上传后先不要大改页面结构，先执行 Magic Layers。

## Magic Layers 人工节点

Magic Layers 由用户在 Canva 内手动完成。

用户完成后应回传：

- Canva 编辑链接。
- 已处理页码范围。
- 哪些页面 Magic Layers 失败或效果不好。

Codex 收到链接后检查：

- 设计能否被 Canva 插件访问。
- 页数是否和参考 PPT/PDF 一致。
- 页面是否有可读文本层。
- 是否仍有明显整页图片未拆分。

如果文本层很少、页面仍不可编辑、或页数不匹配，先让用户回 Canva 继续处理，不用 OCR 或猜测内容硬改。

## 文案修正规则

项目内任务的权威文案顺序：

```text
_state/阶段1/content.json
阶段1_规划确认/每页干净逐字稿.md
阶段1_规划确认/页面规划.md
```

修正优先级：

1. 错别字、伪字、乱码。
2. 漏字、多字、识别错词。
3. 标点、空格、断句。
4. 标题、要点、编号、单位和数字。
5. 因替换造成的溢出、遮挡或断行。

禁止：

- 不用 Canva OCR 或 Magic Layers 识别文本覆盖阶段1文案。
- 不把 Canva 中多出来的词擅自加入逐字稿。
- 不因为 Canva 漏拆某些文字就删掉阶段1内容。
- 不大范围改写阶段1已确认文案；确需改内容时，返还给用户确认，不借 `/canva` 静默改合同。

## 样式调整规则

视觉参考：

```text
阶段2_图片版PPT/pdf/图片版PPT.pdf
阶段2_图片版PPT/img/slide_XXX.png
```

可调项：

- 字号。
- 粗细。
- 斜体。
- 颜色。
- 对齐。
- 行高。
- 列表样式。
- 文本框位置。
- 文本框大小。

目标是尽量贴近阶段2确认图，而不是让 Canva 自动重新设计。

人工待处理项：

- 字体族不对。
- 背景色或渐变不对。
- 图形样式不对。
- Magic Layers 漏拆文字。
- 需要新增文本框。
- 需要新增、删除或重排页面。

这些事项写入任务总结或 `manual_todos.md`，不要用不可靠方式绕过。

## 批量编辑 transaction

每批修改遵循：

```text
start-editing-transaction
-> perform-editing-operations
-> 展示修改页缩略图
-> 用户确认
-> commit-editing-transaction
```

如果用户不确认，调用 cancel 或明确说明草稿未保存。

批次建议：

- 默认每批 3 到 5 页。
- 复杂页每批 1 到 2 页。
- 只做全局简单错别字替换时可以跨页，但必须确认不会误伤其他语境。

操作选择：

- 局部错字优先 `find_and_replace_text`。
- 整个文本框内容错乱时使用 `replace_text`。
- 调字号、粗细、颜色、行高、对齐使用 `format_text`。
- 调位置使用 `position_element`。
- 调大小使用 `resize_element`。

响应式页面只使用 Canva 插件允许的操作。如果页面不支持样式、位置或尺寸操作，直接说明限制。

## 阶段外记录

如需记录 Canva 辅助编辑任务，写入：

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

## 可选 brief 命令

如果项目内调用 `/canva`，可先运行：

```bash
python3 scripts/pptctl.py create-canva-task-brief --run-dir <项目目录>
```

该命令只负责整理：

- 阶段1每页权威文案。
- 阶段2图片版 PDF 路径。
- 阶段2页面图路径。
- 阶段外 Canva 任务目录。

该命令不调用 Canva 插件，不上传文件，不修改阶段状态。

## Legacy 说明

旧执行器：

```text
scripts/runtime/canva_ai_layer_runner.mjs
```

只作为历史排障或用户明确要求浏览器自动点击时的 legacy 工具，不再作为 `/canva`、`/可画` 默认流程。使用 legacy 工具时，仍不能写阶段3状态，且遇到登录、验证码、付费弹窗、保存失败或页面结构不可识别时必须停下来。

## 完成汇报

Canva 辅助任务完成后汇报：

- Canva 设计标题或链接。
- 页数和处理页码范围。
- 已修正文案问题。
- 已调整样式问题。
- 未能处理、需要用户手动修的事项。
- 是否已 commit 保存。
- 如有阶段外记录，给出 `_state/工具任务/canva/<task_id>/` 路径。
