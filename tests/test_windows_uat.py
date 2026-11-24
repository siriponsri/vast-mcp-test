import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("VAST_MCP_WINDOWS_UAT") != "1",
    reason="Opt into native Windows CLI integration in temporary profiles",
)
def test_native_clients_and_unicode_checkout(tmp_path):
    root = Path(__file__).resolve().parents[1]
    workspace = tmp_path / "โฟลเดอร์ ทดสอบ Vast"
    workspace.mkdir()
    for name in ("pyproject.toml", "uv.lock", ".python-version", "README.md"):
        shutil.copy2(root / name, workspace / name)
    for name in ("src", "ptp_vast_mcp"):
        shutil.copytree(root / name, workspace / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))

    owner = tmp_path / "ผู้ใช้ ทดสอบ"
    owner.mkdir()
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("VAST_", "CLAUDE_", "CODEX_", "ANTHROPIC_", "UV_"))
           and key.upper() != "VIRTUAL_ENV"}
    env.update({
        "USERPROFILE": str(owner), "HOME": str(owner),
        "LOCALAPPDATA": str(owner / "AppData" / "Local"),
        "APPDATA": str(owner / "AppData" / "Roaming"),
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    subprocess.run(["uv", "sync", "--locked"], cwd=workspace, env=env, check=True, timeout=120)
    python = workspace / ".venv" / "Scripts" / "python.exe"
    scenario = """
import builtins
import json
from pathlib import Path
from vast_mcp import cli
from vast_mcp.clients import Client, read_config

owner = Path.home()
codex = Client.connect("codex")
claude = Client.connect("claude")
assert codex.path.parent.parent == owner and claude.path.parent == owner
codex.path.parent.mkdir()
other = {"command": "unrelated-never-launched", "args": []}
codex.path.write_text('[mcp_servers.other]\\ncommand = "unrelated-never-launched"\\nargs = []\\n',
                      encoding="utf-8")
claude.path.write_text(json.dumps({"mcpServers": {"other": other}}), encoding="utf-8")
before = [client.path.read_bytes() for client in (codex, claude)]
names = ["codex", "claude"]
assert cli.configure(names, install=True, dry_run=True) == 0
assert before == [client.path.read_bytes() for client in (codex, claude)]

def answer(*values):
    choices = iter(values)
    builtins.input = lambda _: next(choices)

cli.require_terminal = lambda: None
answer("", "y", "")
assert cli.configure(names, install=True, dry_run=False) == 0
after = [client.path.read_bytes() for client in (codex, claude)]
answer("", "")
assert cli.configure(names, install=True, dry_run=False) == 0
assert after == [client.path.read_bytes() for client in (codex, claude)]
assert cli.doctor(names) == 0
print("Codex CLI get recognizes vast:", bool(json.loads(codex.run("get", "vast", "--json"))))
status = claude.run("get", "vast")
assert "Connected" in status
print("Claude Code native MCP health check: Connected")
answer("y")
assert cli.configure(names, install=False, dry_run=False) == 0
assert codex.entry() is None and claude.entry() is None
assert read_config(codex.path, toml=True)["mcp_servers"]["other"] == other
assert read_config(claude.path)["mcpServers"]["other"] == other
"""
    subprocess.run([str(python), "-c", scenario], cwd=workspace, env=env,
                   check=True, timeout=150)
