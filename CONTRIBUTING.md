# 贡献指南

感谢你对 Portfolio Monitor 的关注！欢迎各种形式的贡献。

## 🐛 提 Issue

- 搜索已有 Issue，避免重复
- Bug 报告请包含：复现步骤、期望行为、实际行为、运行环境
- 功能建议请说明使用场景

## 🔀 提 PR

1. **Fork** 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m "feat: 描述你的改动"`
4. 推送分支：`git push origin feature/your-feature`
5. 发起 **Pull Request** 到 `main` 分支

### PR 规范

- 一个 PR 只做一件事
- 简要描述改动内容和原因
- 确保 Docker 构建能通过（CI 会自动检查）

## 📝 代码规范

### Python（后端）

- 格式化：[Black](https://github.com/psf/black)
- Lint：[Ruff](https://github.com/astral-sh/ruff)
- 类型提示：推荐使用

```bash
black backend/
ruff check backend/
```

### Vue（前端）

- 遵循 [Vue 官方风格指南](https://cn.vuejs.org/style-guide/)
- 组件命名使用 PascalCase

## 💬 交流

有任何问题，欢迎在 Issue 中讨论。
