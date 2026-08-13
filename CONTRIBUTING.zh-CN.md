[English](CONTRIBUTING.md) | **简体中文**

# Contributing

感谢你参与 Enterprise Agent Platform。

## 开始之前

1. 先通过 Issue 说明问题、使用场景和预期行为。
2. 一个 Pull Request 只处理一个清晰、可验证的主题。
3. 不要提交密钥、真实账号、生产数据、内部地址或未经授权的素材。
4. 涉及接口、权限、租户、计费或状态逻辑时，请同步说明影响面并补充测试。

## 本地验证

- Java：运行受影响 Maven 模块的测试。
- Python：在 `dianlian-ai-runtime` 中先运行 `uv sync --frozen --group deerflow-h0`，再运行 `uv run python -m pytest`。
- Web：在 `dianlian-web` 中依次运行 `npm test`、`npm run build` 和 `npm run test:sites`。

请在 Pull Request 中写明实际执行的检查和仍未覆盖的风险。
