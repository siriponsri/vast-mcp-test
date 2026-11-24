# Verification receipt

## Windows checkout integration

Test environment: Windows PowerShell, uv 0.12.19, CPython 3.12.14, FastMCP 3.4.11, MCP SDK 1.30.0, Codex CLI 0.172.0 through its installed npm layout, and native Claude Code CLI 2.1.292.

The final Windows run passed all 30 tests with native CLI integration enabled.

| Gate | Result | Evidence |
| --- | --- | --- |
| LOCAL_MOCK | PASS | Locked sync, real subprocess stdio initialize and tools/list, all three mock calls, fixture filtering, allocated disk and transfer arithmetic, and fake-secret redaction. The baseline owner lifecycle tests use HTTP fixtures. |
| WINDOWS_CLI_INTEGRATION | PASS | Fresh locked environment under a path containing Thai and spaces. Temporary profiles exercised dry-run, install, unchanged repeat, and uninstall with unrelated MCP entries preserved. Codex CLI found the exact entry. Claude Code reported Connected. Doctor called all three tools using both saved commands. |
| CODEX_T3_UAT | NOT_RUN | Fresh primary-account T3 session tool calls require owner setup. The Codex CLI check confirms registration in the temporary profile. |
| CLAUDE_UAT | NOT_RUN | The native CLI connection passed in the temporary profile. Tool invocation in an interactive owner Claude Code session is pending. |
| LIVE_SEARCH | BLOCKED | `BLOCKED_UNVERIFIED_VAST_SEARCH_SCOPE`. Verified that the wizard and doctor gate report it before requesting credentials. |
| PAID_SMOKE | NOT_RUN | No live provider calls, credit additions, rental, SSH session, or destruction. |

Rollback after a partial write, interrupted replacement recovery, same-name collision, missing CLI, non-TTY refusal, and credential redaction were exercised with temporary configs or test doubles. Windows CLI integration used scripted wizard responses and actual client binaries. Interactive SSH key generation was not exercised.

Run the standard suite with `uv run --locked pytest -q`. Opt in to native Windows CLI integration from PowerShell when both client CLIs are installed.

```powershell
$env:VAST_MCP_WINDOWS_UAT = '1'
try { uv run --locked pytest -q }
finally { Remove-Item Env:VAST_MCP_WINDOWS_UAT }
```

## Supplied PTP v0.1.1 baseline

- Python 3.12 and PrefectHQ FastMCP 3.4.11, official MCP Python client 1.30.0, httpx 0.28.1.
- `python -m unittest discover -s tests -v`: **13 passed**. The actual stdio exchange initialized, listed only one read-only search tool, produced a bounded missing-key response, and denied an unregistered mutation tool.
- `httpx.MockTransport` exercised official endpoint shapes with fake credentials/data only: on-demand search/create/status/connection/stop/destroy; exact quote drift and expiry; offer cap and local eligibility; noninteractive refusal; read-only adapter rejects create; no redirect or vendor body leakage; server commit followed by client timeout reconciles one exact label on page 2 with no duplicate rent; wrong label refusal; price drift and local SSH address refusal; destroy with no positive acknowledgment, incomplete list, or proven complete absence behave differently.
- The single-lease guarantee is local to the shared SQLite receipt database and the cooperative operational environment. Vast has no on-demand conditional purchase price cap in the documented request. Manual owner confirmation, same account, and independent console access during cleanup are assumptions.
- Real Vast API, real GPU availability, provider permission semantics, readiness over SSH, billing/teardown time, and the active Windows T3 profile **NOT_RUN**. The read-only Windows preflight reported no configured Vast key in the inspected standard locations. No keys were read by the starter tests; no charge, provider change, or PTP job.

- The supplied v0.1.1 baseline changed documentation and its package version. Its Vast key scope was `BLOCKED_UNVERIFIED_VAST_SEARCH_SCOPE`. Provider credentials and live endpoints were outside its verification.
