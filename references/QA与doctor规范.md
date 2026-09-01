# QA 与 doctor 规范

本文件定义 PPT Skill 的质量检查分层。它不替代 `质量审查标准.md` 的详细检查项，而是说明哪些检查由 runtime 执行、哪些由主控判断、哪些必须由用户确认。

## 分层

- Schema 校验：检查 JSON 结构、字段类型、必填字段和枚举值。
- Doctor：检查项目目录、状态、阶段资产、正式路线证据、stale/legacy 产物和硬失败。
- 阶段 QA：记录阶段2审美 QA、阶段3坐标复刻 QA、native render check、阶段4讲稿生成检查、K12 教案设计检查等专项结果。
- 质量画像：提供主控判断辅助，例如密集页、warning、推荐抽查页和 QA 覆盖缺口。
- 主控判断：审美、叙事、资料取舍、返工层级、风险接受和用户沟通。
- 用户确认：阶段1、阶段2封面风格、阶段2图片版 PDF、阶段3坐标复刻、阶段3可编辑 PPT 等固定确认点。

## Doctor 职责

Doctor 是项目一致性和硬失败检查器，不是自动执行器，也不是审美裁判。

Doctor 应用于：

- 恢复已有项目时。
- 准备进入用户确认点前。
- 阶段2图片版 PDF、阶段3可编辑 PPT、阶段4 DOCX/PDF 生成后。
- 状态、目录、决策或 evidence 之间出现不一致时。
- 长任务中断后需要判断能否续做时。

Doctor 发现硬问题时，不能继续推进阶段或交付；先修复记录、补证据、返工或汇报阻断。

## 阶段 QA 职责

- 阶段2审美 QA 关注视觉系统一致性、中文文字、页面角色、信息密度、伪字、页码和模块结构统一。
- 阶段3坐标 QA 关注文字对象覆盖、坐标复刻、PPT 原生可编辑对象、render review 和高风险页抽查。
- Native render check 用于阶段3高风险页或关键页，不要求替代全量 execution report。
- 阶段4 QA 关注讲稿内容一致、DOCX/PDF 可打开、中文字体、PDF 可选择、无截断重叠和 manifest 可追溯。
- K12 教案自审关注 K12 条件、阶段1和教材材料追溯、目标-活动-评价对应、课时安排、学科专项、安全提示、教学反思边界和教案 Word/PDF 表格质量。内容质量由主控模型判断，runtime 只保留可确定的底线检查。页数本身不进入硬失败，也不生成低页数提示；PDF 页数只作为排版结果记录，内容是否偏薄由主控按教师使用场景判断。

阶段 QA 记录是证据，不是阶段切换本身；阶段切换仍需主控 decision 和必要的用户确认。

可使用 `create-stage2-visual-qa-draft` 和 `create-stage3-qa-draft` 生成 QA 草稿。草稿默认 `needs_rework`，只把 doctor、quality profile、coordinate plan、execution/report 线索列出来；主控必须补充真实审美/视觉判断后，才能用 `record-stage2-visual-qa` 或 `record-coordinate-stage3-qa` 正式入账。

K12 教案自审可以写入 `_state/阶段4/lesson_plan_qa.json`，也可以只体现在主控检查记录和 `教案生成说明.md` 中。该文件保留为兼容路径，语义是“主控自审记录”，不是复杂评分表。阶段4完成前，必须已经生成教案 Markdown、DOCX、PDF 和 `lesson_plan_manifest.json`，且不存在硬问题。`pass_with_warnings` 可以完成阶段4，但生成说明应列出 warning 和需教师课前调整的事项；`fail` 或明确阻断项不能完成阶段4。

## 质量画像职责

质量画像只帮助主控发现风险，不直接判定通过或失败。

主控使用质量画像时，应判断：

- 推荐高风险页是否已覆盖。
- 未覆盖页是否有理由。
- warning 是否需要返工、接受或转入用户确认说明。
- native style probe 建议是否影响当前交付风险。

## 硬失败与主控判断

硬失败的详细清单以 `质量审查标准.md` 为准。一般包括缺用户确认、缺正式路线 evidence、目录污染、源图和 hash 不一致、OCR 被当内容来源、可编辑 PPT 不可编辑、交付物缺失等。

K12 教案设计的硬失败还包括：K12 条件无法确认却强行生成完成、缺少足以判断 K12 的学段/学科/课题依据、缺阶段1内容资产或锁定稿来源、实验活动缺安全提示、教案 DOCX/PDF 缺失或不可打开、教师可见文档出现内部字段或未知占位。课时、教材版本、班级等无法确认时通常作为 warning 或教师课前调整项，不应在教师可见文档中硬写。教案页数多少都不单独构成硬失败，项目一致性检查不因页数目标替主控判定内容质量。

主控判断包括审美、表达、信息密度、页面是否太花或太空、复杂页是否需要拆分、讲稿是否自然和专业风险是否需要补充调研。

Runtime 可以拦截硬失败；不能替主控接受审美风险，也不能替用户确认。

## 执行建议

常用验证命令：

```bash
python3 scripts/pptctl.py doctor --run-dir <项目目录>
python3 scripts/pptctl.py validate-stage1 --run-dir <项目目录>
python3 scripts/pptctl.py validate-style-templates
PYTHONPATH=scripts/runtime python3 -m unittest discover -s tests
```

具体 PPT 项目验收时，优先顺序是：schema 或命令校验、doctor、阶段专项 QA、主控视觉/内容复核、用户确认。

## 与其他规则的关系

- `核心不变量.md` 定义不可违反的跨阶段红线。
- `恢复与防漂移协议.md` 定义什么时候检查、如何恢复、如何停下来。
- `质量审查标准.md` 定义详细检查项和阶段口径。
- 阶段2、阶段3、阶段4的专题 reference 定义各自 QA 产物如何生成和入账。
