# T3 Code maintenance brief

Work in the `siriponsri/vast-mcp-test` checkout. Read the README and implementation contract. Check the branch, remote, and pending changes before editing. [README](README.md) · [Implementation contract](docs/IMPLEMENTATION.md)

1. Keep one local stdio FastMCP server. Reuse the PTP v0.1.1 planner's verified offer filtering, ranking, and quote arithmetic. Keep `health`, `search_gpu_offers`, and `estimate_run_cost` working through real stdio before considering optional comparison tools.
2. Keep `uv sync --locked` and the PowerShell wizard working for the primary Codex account and Claude Code user scope. Preview changes and confirm them in the owner's terminal. Validate client CLI syntax through installed help and preserve unrelated MCP entries. Cover repeat install, paths with spaces or non-ASCII characters, rollback, doctor, and uninstall.
3. Keep live search blocked until the exact search-only grant and its provisioning are verified. Before any future credential flow, require a no-echo owner terminal prompt and a verified OS credential store. Put only a profile identifier in agent config. The owner can select or generate a personal SSH identity or skip SSH, and uploads only the public key. Keep private keys and sample course keys out of the integration.
4. Report `LOCAL_MOCK`, `CODEX_T3_UAT`, `CLAUDE_UAT`, `LIVE_SEARCH`, and `PAID_SMOKE` separately. Keep documentation in English. Verify stdio, redaction, allocation and transfer pricing, and actual Windows client behavior where available.
5. Keep rental, credit, destruction and SSH in the owner terminal or Vast Console. Publishing requires the owner's explicit authorization. [Verification receipt](docs/QA.md)
