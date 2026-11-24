import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from filelock import FileLock, Timeout

from . import BLOCKED, CONSOLE, VERSION
from .clients import CLIENT_NAMES, Client, Launch, SetupError, child_environment, config_path
from .registration import Registration, state_path
from .profile import TOOL_NAMES, valid_profile
from .ssh import choose_ssh


def parse_clients(value: str) -> list[str]:
    names = value.split(",")
    if len(set(names)) != len(names) or any(name not in CLIENT_NAMES for name in names):
        raise argparse.ArgumentTypeError("Choose codex, claude, or codex,claude.")
    return names


def require_terminal() -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise SetupError("Open the owner PowerShell terminal for interactive setup or uninstall.")


def blocked_search() -> None:
    print(f"{BLOCKED}\nSearch live offers in Vast Console: {CONSOLE}")


def show_plan(clients: dict[str, Client], plan: dict, *, install: bool) -> None:
    print(f"Workspace: {Path.cwd()}")
    for name, (before, after) in plan.items():
        scope = "Primary Codex" if name == "codex" else "Claude Code user"
        action = "keep" if before == after else (
            "replace" if before and after else "add" if after else "remove"
        )
        print(f"{scope}: {action} vast in {clients[name].path}")
        launch = after if install else before
        if launch:
            print(f"  {subprocess.list2cmdline([launch.command, *launch.args])}")


def recover(receipt: Registration, *, dry_run: bool) -> bool:
    if not receipt.pending:
        return True
    names = ", ".join(receipt.pending)
    print(f"Pending rollback for vast in: {names}")
    if dry_run:
        return False
    if input("Restore the previous vast registrations? [y/N] ").strip().lower() != "y":
        return False
    clients = {name: Client.connect(name) for name in receipt.pending}
    for client in clients.values():
        client.verify_help()
    receipt.rollback(clients)
    return True


def configure(names: list[str], *, install: bool, dry_run: bool) -> int:
    path = state_path()
    if dry_run:
        return configure_locked(Registration(path), names, install=install, dry_run=True)
    require_terminal()
    path.parent.mkdir(mode=0o700, exist_ok=True)
    try:
        with FileLock(str(path.with_suffix(".lock")), timeout=0):
            return configure_locked(Registration(path), names, install=install, dry_run=False)
    except Timeout:
        raise SetupError("Another Vast MCP installer is running.") from None


def configure_locked(receipt: Registration, names: list[str], *, install: bool, dry_run: bool) -> int:
    if not recover(receipt, dry_run=dry_run):
        return 1
    clients = {}
    missing = []
    for name in names:
        path = config_path(name)
        try:
            clients[name] = Client.connect(name)
        except SetupError as error:
            if not install and (name in receipt.owned or path.exists()):
                raise
            print(error)
            missing.append(name)
    if not clients:
        print("No selected CLI is available.")
        return 1
    plan = receipt.plan(clients, install=install)
    show_plan(clients, plan, install=install)
    if dry_run:
        return int(bool(missing))
    changes = [clients[name] for name, (before, after) in plan.items() if before != after]
    for client in changes:
        client.verify_help()
    if install:
        choice = input("Mode [m]ock / [l]ive search (m): ").strip().lower()
        if choice in {"live", "live search", "l"}:
            blocked_search()
            return 2
        if choice not in {"", "m", "mock"}:
            raise SetupError("Select mock or live search.")
    if changes:
        if input("Apply the displayed changes? [y/N] ").strip().lower() != "y":
            print("Registration declined.")
            return 0
        receipt.apply(clients, plan)
        print("Vast MCP registrations updated.")
    else:
        print("Vast MCP registrations are already up to date.")
    if install:
        choose_ssh()
    return int(bool(missing))


async def protocol_probe(launch: Launch) -> None:
    from fastmcp import Client as McpClient
    from fastmcp.client.transports import StdioTransport

    transport = StdioTransport(command=launch.command, args=launch.args,
                               env=child_environment(), keep_alive=False)
    async with asyncio.timeout(30), McpClient(transport, timeout=10) as client:
        names = {tool.name for tool in await client.list_tools()}
        if names != TOOL_NAMES:
            raise SetupError("Unexpected MCP tool list.")
        health = (await client.call_tool("health", {})).data
        if health["mode"] != "mock" or health["live_search"] != BLOCKED:
            raise SetupError("Unexpected MCP health response.")
        search = (await client.call_tool("search_gpu_offers", {"limit": 1, "disk_gb": 40})).data
        offer = search["offers"][0]
        if search["source"] != "synthetic" or offer["offer_id"] != "mock-101":
            raise SetupError("Unexpected synthetic offer.")
        estimate = (await client.call_tool("estimate_run_cost", {
            "offer_id": offer["offer_id"], "disk_gb": offer["disk_gb"], "hours": "2",
            "upload_to_host_gb": "1", "download_from_host_gb": "2",
        })).data
        if estimate["estimated_total_usd"] != "0.588000":
            raise SetupError("Unexpected synthetic estimate.")


def doctor(names: list[str]) -> int:
    receipt = Registration(state_path())
    failed = bool(receipt.pending)
    if receipt.pending:
        print(f"ROLLBACK_PENDING: {', '.join(receipt.pending)}")
    targets = {"LOCAL_MOCK": Launch(str(Path(sys.executable).absolute()), "mock")}
    for name in names:
        try:
            client = Client(name, config_path(name), [])
            current = client.entry()
            owned = receipt.owned.get(name)
            client.check_shadow()
            if current is None:
                print(f"{name}: {'MISSING_OWNED_ENTRY' if owned else 'NOT_REGISTERED'}")
                failed |= bool(owned)
            elif owned and current == client.expected(owned):
                targets[f"{name} registered command"] = owned
            else:
                print(f"{name}: UNOWNED_OR_MODIFIED")
                failed = True
        except SetupError as error:
            print(error)
            failed = True
    for label, launch in targets.items():
        try:
            asyncio.run(protocol_probe(launch))
        except Exception:
            print(f"{label}: FAIL (stdio probe)")
            failed = True
        else:
            print(f"{label}: PASS (stdio initialize, tools/list, mock calls)")
    blocked_search()
    return int(failed)


class CliParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.exit(2, f"{self.prog}: invalid command or arguments. See --help.\n")


def parser() -> argparse.ArgumentParser:
    root = CliParser(prog="vast-mcp")
    root.add_argument("--version", action="version", version=VERSION)
    commands = root.add_subparsers(dest="action", required=True)
    for action in ("setup", "uninstall", "doctor"):
        command = commands.add_parser(action)
        command.add_argument("--clients", type=parse_clients, default=list(CLIENT_NAMES))
        if action == "doctor":
            modes = command.add_mutually_exclusive_group()
            modes.add_argument("--offline", action="store_true", help="Run the default mock probe.")
            modes.add_argument("--live-search", action="store_true")
        else:
            command.add_argument("--dry-run", action="store_true")
    server = commands.add_parser("serve")
    server.add_argument("--profile", default="mock")
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.action == "serve":
            if not valid_profile(args.profile):
                raise SetupError("Unknown profile. Use mock or a profile issued by setup.")
            from ptp_vast_mcp.mcp_server import main as serve

            serve()
            return 0
        if args.action == "doctor":
            if args.live_search:
                blocked_search()
                return 2
            return doctor(args.clients)
        return configure(args.clients, install=args.action == "setup", dry_run=args.dry_run)
    except SetupError as error:
        print(error, file=sys.stderr)
    except (KeyboardInterrupt, EOFError):
        print("Cancelled. Use doctor to inspect registrations.", file=sys.stderr)
    except OSError:
        print("A local file or process operation failed. Use doctor to inspect registrations.",
              file=sys.stderr)
    return 1
