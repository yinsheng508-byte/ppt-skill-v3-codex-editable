# AGENTS.md

## 范围

本文件适用于整个 `ppt-skill-v2` 目录。

这个目录是 PPT Skill v2 的 Skill 主包和设计实现区，不是某个具体 PPT 项目目录。不要把本目录直接当作 `run_dir`、项目输出目录或用户交付目录。

## 启动顺序

1. 把当前目录当作 Skill 根目录。
2. 先读 `SKILL.md`。
3. 根据任务类型按需读取：
   - 项目目录和恢复：`references/项目目录规范.md`
   - 阶段流程：`references/阶段流程.md`
   - 阶段切换：`references/主控决策协议.md`
   - 图片生成：`references/生图证据链.md`
   - 可编辑 PPT：`references/可编辑PPT路线.md`
   - 阶段3文字填字规划：`references/阶段3文字填字规划规范.md`
   - 阶段3插件主控和证据回写：`references/阶段3插件主控与可编辑PPT规范.md`
   - 质量审查：`references/质量审查标准.md`
   - 阶段4演讲稿输出：`references/阶段4演讲稿输出规范.md`
4. 只有用户明确要求维护 Skill 结构、文档、模板或工具时，才修改本目录。

## 防止误调用

- 不要因为进入本目录就启动 PPT 生成。
- 不要把 `ppt-skill-v2/` 当作具体 PPT 项目。
- 不要在 Skill 根目录下创建阶段0到阶段4的项目产物。
- 不要运行会生成图片、PPT、交付包或推进阶段的命令，除非用户明确要求生成具体 PPT。
- 任何具体 PPT/PPTX 生成、改造、审查、可编辑化或演讲稿输出，包括已有 PPTX 的“内容不变/内容不要大改/优化视觉/美化/升级/可编辑优化/先做一版”，都必须走 `SKILL.md` 定义的四阶段流程。
- 不要直接修改源 PPTX、不要直接生成可编辑 PPTX 交付、不要把通用 PPT 编辑结果包装成阶段3；除非用户明确说跳过本 Skill 流程或直接改文件。
- 不要让代码根据文件存在、状态字段或默认规则自行进入下一阶段。
- 不要使用 runner 式循环调度作为主控。
- 正式阶段2/阶段3图片默认先走 Codex 内置 `image_gen` 官方路线，也允许显式走 `openai_image_api` 中转 API 路线；图片记录必须有对应路线 evidence、结果 ID、图片 sha 和 batch manifest。中转 API 单个 batch/run 最多 6 并发，多个独立 batch 可同时执行；官方 `image_gen` 路线由主控按 packet 调用工具并逐张入账。
- 正式阶段2/阶段3图片优先目标尺寸为 16:9 `2048x1152`；尽量保留生成返回原始尺寸，不主动压缩或降采样。官方 `image_gen` 若返回低于 2K，入账 `size_warnings` 作为质量风险提示，由主控按实际清晰度决定继续、重试或切路线。
- 正式阶段3可编辑 PPT 记录必须有 provider evidence 和 tool call 证据。

## 项目恢复和进度定位

- 用户说继续、修改、确认、返工、看进度，或只给源 PPTX 路径时，先查看 `outputs/projects/` 下是否已有同名或近似项目。
- 定位项目后先读 `_state/project_state.json`、`_decisions/`、`阶段1_规划确认/`、`阶段2_图片版PPT/` 和 `阶段3_可编辑PPT/`，再判断下一步。
- 只相信用户确认、主控决策和 `_state` 记录；不要因为某个 PPTX、PDF 或图片文件存在就认定阶段已完成。
- 找不到已有项目时，先创建新的 `outputs/projects/<中文项目名>/` 并把源文件登记为阶段0资料，不要把源文件所在目录或 Skill 根目录当作 `run_dir`。

## 主控原则

- Skill 文档规范大模型。
- 大模型负责主控、判断、用户沟通、阶段确认和返工路由。
- 脚本和代码只做被明确交代的确定性执行动作。
- 阶段切换必须来自主控大模型的显式决策，不来自文件存在或本地脚本判断。

## 项目边界

具体 PPT 项目只能放在：

```text
outputs/projects/<中文项目名>/
```

项目目录必须使用中文阶段目录：

```text
阶段0_资料整理/
阶段1_规划确认/
阶段2_图片版PPT/
阶段3_可编辑PPT/
阶段4_演讲稿输出/
_state/
_decisions/
```

阶段目录只放用户可读、可确认、可交付的材料。JSON、packet、manifest、prompt 原稿、日志、校验报告、worker 输出、中间 brief 和素材索引全部放 `_state/`。主控决策 JSON 全部放 `_decisions/`。

## 修改本 Skill 时

- 保持 `SKILL.md` 简短，只放主控原则和 reference 路由。
- 详细规则放到 `references/`，文件名和正文尽量用中文。
- 开发任务卡、历史验收记录、已完成规划、测试源码、dev smoke、缓存和废弃文件放到 `docs/archive/`，不要放进正式 `references/` 或 Skill 根目录。
- 模板放到 `assets/templates/`，模板内容不能冒充正式阶段产物。
- 脚本只能作为被动执行器，不写自动推进或自主验收逻辑。
- 确定性 runtime 放在 `scripts/runtime/`，schema 契约放在 `scripts/schemas/`，不要再在 Skill 根目录新建 `runtime/` 或 `schemas/`。
- 改动后至少运行 Skill 校验。

## 验证

```bash
python3 /Users/yinxinhe/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
```
