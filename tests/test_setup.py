import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from vast_mcp import BLOCKED
from vast_mcp import cli, clients, ssh
from vast_mcp.clients import Client, Launch, SetupError
from vast_mcp.registration import Registration


@pytest.fixture
def fake_clients(tmp_path, monkeypatch):
    config = {name: {"other": {"command": "unrelated"}} for name in clients.CLIENT_NAMES}
    calls = []
    failures = set()
    targets = {name: Client(name, tmp_path / name, ["fake"]) for name in clients.CLIENT_NAMES}
    monkeypatch.setattr(cli, "config_path", lambda name: targets[name].path)
    monkeypatch.setattr(Client, "connect", lambda name: targets[name])
    monkeypatch.setattr(Client, "check_shadow", lambda self: None)
    monkeypatch.setattr(Client, "entry", lambda self: config[self.name].get("vast"))
    monkeypatch.setattr(cli, "state_path", lambda: tmp_path / "state" / "receipt.json")

    def run(self, action, *args):
        name = self.name
        calls.append((name, action, *args))
        if args == ("--help",):
            return "<NAME> -- <COMMAND> <name> --scope --transport --json"
        if action == "add":
            launch = Launch(args[args.index("--") + 1], args[-1])
            config[name]["vast"] = self.expected(launch)
        elif action == "remove":
            config[name].pop("vast")
        if (name, action) in failures:
            raise SetupError("Simulated failure after changing config.")
        return ""

    monkeypatch.setattr(Client, "run", run)

    def write_codex(self, before, after):
        if after:
            config[self.name]["vast"] = self.expected(after)
        else:
            config[self.name].pop("vast")

    monkeypatch.setattr(Client, "write_codex", write_codex)
    return SimpleNamespace(config=config, calls=calls, targets=targets, failures=failures)


def answers(monkeypatch, *values):
    replies = iter(values)
    monkeypatch.setattr(cli, "require_terminal", lambda: None)
    monkeypatch.setattr("builtins.input", lambda prompt: next(replies))


def test_dry_run_install_repeat_and_scoped_uninstall(fake_clients, monkeypatch, capsys, tmp_path):
    names = ["codex", "claude"]
    python = str(tmp_path / "พื้นที่ ทดสอบ" / "python.exe")
    monkeypatch.setattr(sys, "executable", python)
    assert cli.configure(names, install=True, dry_run=True) == 0
    assert not cli.state_path().exists()
    assert not fake_clients.calls
    assert python in capsys.readouterr().out
    answers(monkeypatch, "", "y", "")
    assert cli.configure(names, install=True, dry_run=False) == 0
    original_calls = fake_clients.calls.copy()
    answers(monkeypatch, "", "")
    assert cli.configure(names, install=True, dry_run=False) == 0
    assert fake_clients.calls == original_calls
    assert fake_clients.config["claude"]["vast"]["command"] == python
    answers(monkeypatch, "y")
    assert cli.configure(["claude"], install=False, dry_run=False) == 0
    assert set(fake_clients.config["claude"]) == {"other"}
    assert set(fake_clients.config["codex"]) == {"vast", "other"}


def test_failure_after_write_rolls_back_both(fake_clients, monkeypatch):
    fake_clients.failures.add(("claude", "add"))
    answers(monkeypatch, "", "y")
    with pytest.raises(SetupError, match="Previous vast entries were restored"):
        cli.configure(["codex", "claude"], install=True, dry_run=False)
    assert all(set(config) == {"other"} for config in fake_clients.config.values())
    assert Registration(cli.state_path()).pending == {}


def test_recovers_interrupted_replacement(fake_clients, monkeypatch, tmp_path):
    answers(monkeypatch, "", "y", "")
    cli.configure(["codex"], install=True, dry_run=False)
    receipt = Registration(cli.state_path())
    old = receipt.owned["codex"]
    receipt.pending["codex"] = (old, Launch(str(tmp_path / "new.exe"), old.profile))
    receipt.save()
    del fake_clients.config["codex"]["vast"]
    monkeypatch.setattr(sys, "executable", str(tmp_path / "workspace with spaces" / "python.exe"))
    answers(monkeypatch, "y", "", "n")
    assert cli.configure(["codex"], install=True, dry_run=False) == 0
    assert fake_clients.config["codex"]["vast"]["command"] == old.command
    assert Registration(cli.state_path()).pending == {}


def test_live_stops_before_consent_or_credentials(fake_clients, monkeypatch, capsys):
    answers(monkeypatch, "l")
    assert cli.configure(["codex"], install=True, dry_run=False) == 2
    assert BLOCKED in capsys.readouterr().out
    assert not cli.state_path().exists()
    assert [call[1:] for call in fake_clients.calls] == [("get", "--help")]


def test_unknown_entry_and_missing_cli(fake_clients, monkeypatch):
    fake_clients.config["claude"]["vast"] = {"command": "foreign"}
    with pytest.raises(SetupError, match="differs from the installer receipt"):
        cli.configure(["codex", "claude"], install=True, dry_run=True)
    monkeypatch.setattr(Client, "connect", lambda name: fake_clients.targets[name]
                        if name == "codex" else (_ for _ in ()).throw(SetupError("Unavailable")))
    answers(monkeypatch, "", "y", "")
    assert cli.configure(["codex", "claude"], install=True, dry_run=False) == 1
    assert fake_clients.config["claude"]["vast"]["command"] == "foreign"
    assert "vast" in fake_clients.config["codex"]


def test_scope_and_secret_redaction(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(clients, "home", lambda: tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "other-account"))
    with pytest.raises(SetupError, match="primary"):
        clients.config_path("codex")
    canary = f"FAKE_{uuid4().hex}"
    monkeypatch.setenv("VAST_API_KEY", canary)

    def run(args, **options):
        assert canary not in str(args)
        assert canary not in options["env"].values()
        return SimpleNamespace(returncode=1, stdout=canary, stderr=canary)

    monkeypatch.setattr(clients.subprocess, "run", run)
    with pytest.raises(SetupError) as failure:
        Client("codex", tmp_path / ".codex/config.toml", ["fake"]).run("add")
    assert canary not in str(failure.value) + capsys.readouterr().err


def test_codex_preserves_unrelated_mcp_table(tmp_path):
    path = tmp_path / ".codex" / "config.toml"
    path.parent.mkdir()
    other = b'[mcp_servers.other]\r\ncommand = "other" # owned elsewhere\r\nargs = []\r\n'
    path.write_bytes(other)
    client = Client("codex", path, [])
    launch = Launch(str(tmp_path / "พื้นที่ ทดสอบ" / "python.exe"), f"mock-{uuid4().hex}")
    client.set_entry(None, launch)
    assert other in path.read_bytes()
    client.set_entry(launch, None)
    assert other in path.read_bytes()


def test_piped_setup_is_rejected_before_writing_receipt(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "state_path", lambda: tmp_path / "state.json")
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SetupError, match="owner PowerShell"):
        cli.configure(["codex"], install=True, dry_run=False)
    assert not list(tmp_path.iterdir())


def test_ssh_uses_path_metadata_only(tmp_path, monkeypatch):
    identity = tmp_path / "กุญแจ ส่วนตัว"
    identity.touch()
    public = identity.with_name(identity.name + ".pub")
    public.touch()
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("SSH key opened"))
    assert ssh.existing_public_key(f'"{identity}"') == public
    with pytest.raises(SetupError, match="Week 03"):
        ssh.existing_public_key(str(tmp_path / "Devtool_SSH" / "devtoolSSH"))
