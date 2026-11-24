# Test on Windows with T3 and Claude Code

Run the README commands in the owner’s PowerShell session. Complete the plan confirmation using **mock**. If a CLI is missing, setup can register the available client and returns a nonzero status to flag the missing one. Rerun setup for that client after installing its CLI.

## T3 and the primary Codex account

1. Run `codex mcp get vast` to inspect the saved entry. Confirm the Python executable is the trusted checkout’s locked venv.
2. Open a new T3 Codex session on the account that uses `%USERPROFILE%\.codex`. If a running account has cached MCP configuration, restart it after its current work finishes.
3. Ask T3 to call the registered server’s `health` and `search_gpu_offers`, then estimate the first result. Verify `mode: mock`, `source: synthetic`, and the live-search gate. [Test prompt](T3_SMOKE_PROMPT.md)

## Claude Code

1. Open a new Claude Code session in the checkout.
2. Use `/mcp` in Claude Code, or inspect the server from PowerShell with `claude mcp get vast`.
3. Ask Claude Code to call the same three tools and check the returned values.

Record the actual tool response for each interactive client. Doctor runs its own MCP client against the registered command, and Codex CLI get inspects saved configuration. Claude Code can report a successful connection before an agent executes a tool. The installer uses user scope. A project-local entry with the same name can shadow it in another checkout. Claude Desktop uses a separate configuration.

See the setup references for each client. [Windows path and account details](WINDOWS_T3.md) · [Codex MCP documentation](https://developers.openai.com/codex/mcp) · [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp)
