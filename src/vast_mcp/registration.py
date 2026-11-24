import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from .clients import CLIENT_NAMES, Client, Launch, SetupError, home, read_config
from .profile import valid_profile


def state_path() -> Path:
    return home() / ".vast-mcp" / "registrations.json"


def decode_launch(data: dict | None) -> Launch | None:
    if data is None:
        return None
    launch = Launch(**data)
    if (not Path(launch.command).is_absolute() or not valid_profile(launch.profile)
            or launch.profile == "mock"):
        raise ValueError
    return launch


class Registration:
    def __init__(self, path: Path):
        self.path = path
        state = read_config(path)
        try:
            if state and state.get("version") != 1:
                raise ValueError
            owned = state.get("owned", {})
            pending = state.get("pending", {})
            if (set(owned) | set(pending)) - set(CLIENT_NAMES):
                raise ValueError
            self.owned = {name: decode_launch(launch) for name, launch in owned.items()}
            self.pending = {
                name: (decode_launch(before), decode_launch(after))
                for name, (before, after) in pending.items()
            }
        except (AttributeError, TypeError, ValueError):
            raise SetupError("Vast MCP registration receipt is invalid. Review it before editing clients.") from None

    def save(self) -> None:
        state = {
            "version": 1,
            "owned": {name: asdict(launch) for name, launch in self.owned.items() if launch},
            "pending": {
                name: [asdict(launch) if launch else None for launch in pair]
                for name, pair in self.pending.items()
            },
        }
        temporary = None
        try:
            with NamedTemporaryFile(dir=self.path.parent, delete=False, mode="w",
                                    encoding="utf-8") as stream:
                temporary = Path(stream.name)
                json.dump(state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def plan(self, clients: dict[str, Client], *, install: bool) -> dict:
        plan = {}
        command = str(Path(sys.executable).absolute())
        for name, client in clients.items():
            if install:
                client.check_shadow()
            current = client.entry()
            owned = self.owned.get(name)
            if current is not None and (owned is None or current != client.expected(owned)):
                raise SetupError(f"{name}: existing vast entry differs from the installer receipt.")
            before = owned if current is not None else None
            after = None
            if install:
                after = Launch(command, owned.profile if owned else f"mock-{uuid4().hex}")
            plan[name] = (before, after)
        return plan

    def apply(self, clients: dict[str, Client], plan: dict) -> None:
        previous_owned = self.owned.copy()
        self.pending = {name: pair for name, pair in plan.items() if pair[0] != pair[1]}
        self.save()
        try:
            for name, (before, after) in self.pending.items():
                clients[name].set_entry(before, after)
            for name, (_, after) in plan.items():
                self.owned[name] = after
            pending = self.pending
            self.pending = {}
            try:
                self.save()
            except BaseException:
                self.pending = pending
                raise
        except (Exception, KeyboardInterrupt):
            self.owned = previous_owned
            self.rollback(clients)
            raise SetupError("Registration stopped. Previous vast entries were restored.") from None

    def rollback(self, clients: dict[str, Client]) -> None:
        for name, (before, after) in reversed(list(self.pending.items())):
            client = clients[name]
            try:
                # Replacement may have removed the old entry before add failed.
                current = client.entry()
                source = None if current is None else after
                client.set_entry(source, before)
            except (SetupError, OSError):
                continue
            del self.pending[name]
            self.save()
        if self.pending:
            names = ", ".join(self.pending)
            raise SetupError(f"Rollback still pending for {names}. Run doctor and setup or uninstall to recover.")
