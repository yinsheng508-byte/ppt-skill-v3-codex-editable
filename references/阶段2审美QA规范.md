# 阶段2审美QA规范

## 目标

阶段2审美 QA 用于主控大模型在提交用户确认前做轻量检查和返工记录。它不是自动视觉评分系统，不替代用户确认，也不让 runtime 判断“高级感”。

记录文件：

```text
_state/阶段2/visual_qa/stage2_aesthetic_review.json
```

## review scope

`review_scope` 可取：

- `cover_options`：四张封面候选。
- `trial_first5`：阶段2B试样，默认3页，最多5页，可追加关键复杂页；名称沿用历史目录。
- `full_image_deck`：完整阶段2图片版。

## 建议结构

```json
{
  "schema_version": "1.0",
  "overall_status": "pass | needs_rework",
  "review_scope": "cover_options | trial_first5 | full_image_deck",
  "checks": {
    "visual_system_consistency": "pass | needs_rework",
    "text_readability": "pass | needs_rework",
    "content_text_accuracy": "pass | needs_rework",
    "page_role_fit": "pass | needs_rework",
    "image_relevance": "pass | needs_rework",
    "no_fake_text_or_placeholders": "pass | needs_rework",
    "density_and_hierarchy": "pass | needs_rework",
    "page_number_policy": "pass | needs_rework",
    "header_position_consistency": "pass | needs_rework",
    "section_intro_consistency": "pass | needs_rework"
  },
  "slide_findings": [],
  "rework_recommendation": {
    "target": "stage2_design_plan | stage2_cover | stage2_prompt | selected_slides | none",
    "reason": ""
  }
}
```

## 检查口径

只抓明显问题：

- 中文乱码、伪字、英文占位、拼音、lorem ipsum。
- 页内文字读不清。
- 阶段2图片内容和 `final_visible_text` 不一致。
- 模型删掉、改写或新增了关键数字、单位、专业术语、结论。
- 风格没有继承用户选中的封面方向。
- 已选封面候选如果要直接转正，必须检查中文文字、构图完整性、内容一致性和证据链；有明显问题时不得为省 token 强行复用。
- 图片只是装饰，和页面主题无关。
- 页面角色和版式不匹配。
- 页面过满、过空或层级不清。
- 同一套 PPT 媒介混乱或连续多页重复卡片墙。
- 用户未明确要求时，页面出现可见页码。
- 用户明确要求页码时，页码位置、样式或显示范围不统一。
- 普通内页顶部小标题位置、字号、颜色、装饰或对齐方式随页漂移。
- 多个模块介绍页没有使用同一结构，例如编号形状、标题位置、分隔线、人物位置或背景节奏随机变化。

## 返工路由

- 封面候选整体不合适：`stage2_cover`。
- 已选封面候选风格可用但画面本身不可直接交付：`stage2_cover` 或对应封面 prompt。
- 试样显示视觉系统抽象错误：`stage2_design_plan`。
- 未请求却生成了可见页码，或请求后页码系统不统一：`stage2_design_plan` 或对应页 `stage2_prompt`。
- 顶部小标题或模块介绍页出现系统性漂移：`stage2_design_plan`，并修订 `deck_style.json`、`layout_intent.json` 和共享 prompt 片段。
- 某些页文字不清或构图跑偏：`stage2_prompt` 或 `selected_slides`。
- 完整图片版只有轻微可接受问题：`none`，但要在 findings 里说明残余风险。

试样失败时，默认返工阶段2设计规划和提示词：

```text
_state/阶段2/deck_style.json
_state/阶段2/layout_intent.json
_state/阶段2/final_prompts/
_state/阶段2/trial_first5/prompts/
```

不得默认修改：

- `阶段1_规划确认/页面规划.md`
- `_state/阶段1/content.json`
- `_state/阶段1/slide_prompt_briefs.json`

只有用户明确要求改内容、页数或页面任务时，才回到阶段1。

## 禁止事项

- 不做像素级自动评分。
- 不要求每页完美。
- 不因轻微对齐差异阻断用户确认。
- 不让 runtime 自动判断审美。
- 不把试样确认当成最终图片版 PDF 确认。
