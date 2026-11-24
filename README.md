<img src="docs/assets/logo.png" width="96" height="96" alt="Vast MCP logo">

# Vast MCP for Codex and Claude Code

An independent, Windows-first local stdio MCP. It uses the PTP v0.1.1 FastMCP server and shares its offer ranking and quote arithmetic. Every MCP offer in this release is synthetic. [Architecture](docs/IMPLEMENTATION.md#architecture)

## Set up from the owner’s PowerShell terminal

Open the checkout with Python 3.12, uv, and the Codex and Claude Code CLIs available on PATH.

~~~powershell
uv sync --locked
uv run --locked vast-mcp setup --clients codex,claude --dry-run
uv run --locked vast-mcp setup --clients codex,claude
uv run --locked vast-mcp doctor --offline
~~~

Setup previews the target files, actions, and launch command. Pick **mock** and confirm the plan. Setup edits the `vast` table in your primary `%USERPROFILE%\.codex\config.toml` and uses the Claude Code CLI for its default user scope. After registration, choose skip, select an existing personal SSH identity, or have OpenSSH generate a new one. Keep the private key on your machine and upload only its companion `.pub`. [Vast Console SSH keys](https://cloud.vast.ai/manage-keys/)

Open a fresh T3 session on the primary Codex account and a fresh Claude Code session. Ask each client to call `health` and `search_gpu_offers` on the `vast` server. See [Windows and client checks](docs/T3_SETUP.md).

| Tool | Result |
| --- | --- |
| `health` | Version, stdio transport, mock readiness, and live search status |
| `search_gpu_offers` | Bounded synthetic shortlist filtered by GPU, per-GPU VRAM in MiB, GPU count, disk GB, country, reliability, and hourly price including disk |
| `estimate_run_cost` | Synthetic compute, allocated disk, upload, and download charges. Pass the offer ID, the same disk allocation, hours, and transfer volumes in GB. Enter zero for a transfer direction you will not use. |

For example, `mock-101` with 40 GB of disk, 2 hours, 1 GB upload and 2 GB download totals **USD 0.588000**. With planned traffic and a missing directional rate, the tool returns a known subtotal and leaves the total unknown. Planned hours do not stop billing.

## Live search and owner operations

Live search returns `BLOCKED_UNVERIFIED_VAST_SEARCH_SCOPE`. The wizard accepts no API key and writes no credential for this release. Keep live quotes, rental, credit, lifecycle and SSH in the Console or a separate owner terminal. The supplied PTP owner CLI and its receipt logic remain available separately. [Vast Console](https://cloud.vast.ai/) · [Grant decision](docs/VAST_SEARCH_KEY.md) · [Owner runbook](docs/OPERATIONS.md)

## Repair or remove a registration

~~~powershell
uv run --locked vast-mcp uninstall --clients codex,claude --dry-run
uv run --locked vast-mcp uninstall --clients codex,claude
~~~

The installer matches the saved receipt before altering an entry. For an interrupted change, rerun setup or uninstall and confirm rollback when prompted. If the entry has been edited outside the installer, inspect it in the owning client. The installer will refuse to overwrite it. If you move the checkout, run `uv sync --locked` in the new location and confirm the replacement setup previews.

See [implementation details](docs/IMPLEMENTATION.md) and [test evidence](docs/QA.md). The local CLI launch and client registration flow draws on [RunPod MCP](https://github.com/runpod/runpod-mcp#run-locally-with-npx).
