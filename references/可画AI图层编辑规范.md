# 可画 AI 图层编辑规范（Legacy）

本文件只保留旧版浏览器自动点击 `AI图层` 的路由边界，不再作为 `/canva`、`/可画` 默认流程。

默认 Canva 辅助编辑任务请读取 `Canva辅助编辑任务规范.md`：

```text
插件导入 PPT/PDF 或用户手动上传
-> 用户手动 Magic Layers
-> 回传 Canva 链接
-> Codex 使用 Canva 插件批量修正文案和样式
```

旧浏览器路线仅在用户明确要求“用浏览器控制 Canva/可画自动点击 AI 图层”时使用。即使使用旧路线，也只处理 Canva 页面内后处理动作，不属于阶段3正式可编辑 PPTX 路线，不写入 `_state/阶段3/`、阶段3交付 manifest 或阶段切换决策。

历史排障线索保留在：

- `scripts/runtime/canva_ai_layer_runner.mjs`
- `docs/archive/2026-08/可画AI图层浏览器旧路线说明.md`

遇到登录、验证码、权限不足、付费弹窗、保存失败、页面结构不可识别或浏览器控制不稳定时，先停下来汇报，不切换成默认流程。
