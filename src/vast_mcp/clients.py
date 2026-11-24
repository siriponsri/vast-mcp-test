import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

import tomlkit

SERVER = "vast"
CLIENT_NAMES = ("codex", "claude")


class SetupError(Exception):
    pass


def home() -> Path:
    return Path.home().resolve()


def config_path(name: str) -> Path:
    if name == "codex":
        main_home = home() / ".codex"
        override = os.environ.get("CODEX_HOME")
        if override and (not Path(override).is_absolute()
                         or Path(override).resolve() != main_home.resolve()):
            raise SetupError("CODEX_HOME differs from the primary ~/.codex. Use the owner terminal.")
        return main_home / "config.toml"
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        raise SetupError("CLAUDE_CONFIG_DIR is set. Use the default Claude Code owner terminal.")
    return home() / ".claude.json"


def child_environment() -> dict[str, str]:
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith("VAST_")}


def cli_prefix(name: str) -> list[str]:
    if os.name != "nt":
        executable = shutil.which(name)
        if executable:
            return [str(Path(executable).absolute())]
    else:
        # Resolve official npm entry points directly, avoiding cmd.exe and
        # shell interpolation when forwarding arbitrary Windows paths.
        packages = {
            "codex": ("@openai", "codex", "bin", "codex.js"),
            "claude": ("@anthropic-ai", "claude-code", "cli.js"),
        }
        for directory in os.get_exec_path():
            base = Path(directory.strip('"')).absolute()
            native = base / f"{name}.exe"
            if native.is_file():
                return [str(native)]
            shim = base / f"{name}.cmd"
            entry_point = base.joinpath("node_modules", *packages[name])
            if (shim.is_file() or (base / f"{name}.ps1").is_file()) and entry_point.is_file():
                local_node = base / "node.exe"
                node = str(local_node) if local_node.is_file() else shutil.which("node.exe")
                if node:
                    return [node, str(entry_point)]
    raise SetupError(f"{name}: supported CLI executable not found on PATH.")


def read_config(path: Path, *, toml: bool = False) -> dict:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError):
        raise SetupError("Unable to read a client configuration.") from None
    try:
        parsed = tomllib.loads(raw) if toml else json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except ValueError:
        pass
    raise SetupError("Client configuration could not be parsed safely.")


def server_entry(config: dict, key: str) -> dict | None:
    entries = config.get(key, {})
    if not isinstance(entries, dict):
        raise SetupError("Unexpected MCP configuration layout.")
    entry = entries.get(SERVER)
    if SERVER in entries and not isinstance(entry, dict):
        raise SetupError("Existing vast entry has an unexpected layout.")
    return entry


@dataclass(frozen=True)
class Launch:
    command: str
    profile: str

    @property
    def args(self) -> list[str]:
        return ["-I", "-m", "vast_mcp", "serve", "--profile", self.profile]


@dataclass
class Client:
    name: str
    path: Path
    prefix: list[str]

    @classmethod
    def connect(cls, name: str) -> "Client":
        return cls(name, config_path(name), cli_prefix(name))

    def verify_help(self) -> None:
        if self.name == "codex":
            supported = "--json" in self.run("get", "--help")
        else:
            add_help = self.run("add", "--help")
            remove_help = self.run("remove", "--help")
            supported = ("<name>" in add_help and "<name>" in remove_help
                         and "--transport" in add_help and "--scope" in add_help
                         and "--scope" in remove_help)
        if not supported:
            raise SetupError(f"{self.name}: installed mcp --help did not confirm supported syntax.")

    def run(self, *args: str) -> str:
        env = child_environment()
        if self.name == "codex":
            env["CODEX_HOME"] = str(self.path.parent)
        try:
            completed = subprocess.run(
                [*self.prefix, "mcp", *args], env=env, shell=False, timeout=30,
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.TimeoutExpired):
            raise SetupError(f"{self.name}: CLI action {args[0]} failed to complete.") from None
        if completed.returncode:
            raise SetupError(f"{self.name}: CLI action {args[0]} returned {completed.returncode}.")
        return completed.stdout

    def entry(self) -> dict | None:
        codex = self.name == "codex"
        config = read_config(self.path, toml=codex)
        return server_entry(config, "mcp_servers" if codex else "mcpServers")

    def check_shadow(self) -> None:
        if self.name == "codex":
            return
        projects = read_config(self.path).get("projects", {})
        if not isinstance(projects, dict):
            raise SetupError("Claude Code project configuration has an unexpected layout.")
        directory = Path.cwd().resolve()
        ancestors = {directory, *directory.parents}
        for location, project in projects.items():
            if Path(location).resolve() in ancestors and isinstance(project, dict):
                if server_entry(project, "mcpServers") is not None:
                    raise SetupError("Claude Code has a same-name local project entry.")
        for location in ancestors:
            if server_entry(read_config(location / ".mcp.json"), "mcpServers") is not None:
                raise SetupError("Claude Code has a same-name project entry in .mcp.json.")

    def expected(self, launch: Launch | None) -> dict | None:
        if launch is None:
            return None
        entry = {"command": launch.command, "args": launch.args}
        if self.name == "claude":
            entry.update(type="stdio", env={})
        return entry

    def set_entry(self, before: Launch | None, after: Launch | None) -> None:
        current = self.entry()
        if current == self.expected(after):
            return
        if current != self.expected(before):
            raise SetupError(f"{self.name}: vast entry changed or belongs to another installation.")
        if self.name == "codex":
            self.write_codex(before, after)
            if self.entry() != self.expected(after):
                raise SetupError("codex: could not verify the resulting vast entry.")
            return
        if before:
            self.run("remove", "--scope", "user", SERVER)
            if self.entry() is not None:
                raise SetupError(f"{self.name}: could not confirm removal of the vast entry.")
        if after:
            self.run("add", "--transport", "stdio", "--scope", "user",
                     SERVER, "--", after.command, *after.args)
            if self.entry() != self.expected(after):
                raise SetupError(f"{self.name}: could not verify the new vast entry.")

    def write_codex(self, before: Launch | None, after: Launch | None) -> None:
        # Codex CLI normalizes unrelated MCP entries when it rewrites config.toml.
        # Preserve their fields and formatting by changing just the managed table.
        self.path.parent.mkdir(mode=0o700, exist_ok=True)
        if self.path.is_symlink() or self.path.parent.is_symlink():
            raise SetupError("codex: use a primary config path without symlinks.")
        original = read_bytes(self.path)
        try:
            document = tomlkit.parse(original.decode("utf-8-sig"))
        except (ValueError, UnicodeError):
            raise SetupError("codex: config.toml could not be edited safely.") from None
        if server_entry(document.unwrap(), "mcp_servers") != self.expected(before):
            raise SetupError("codex: vast entry changed after the plan.")
        entries = document.setdefault("mcp_servers", tomlkit.table())
        if after is None:
            del entries[SERVER]
        else:
            entries[SERVER] = self.expected(after)
        modified = tomlkit.dumps(document).encode(
            "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
        )
        with NamedTemporaryFile(dir=self.path.parent, delete=False, mode="wb") as stream:
            temp = Path(stream.name)
            try:
                stream.write(modified)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                stream.close()
                temp.unlink(missing_ok=True)
                raise
        try:
            if read_bytes(self.path) != original:
                raise SetupError("codex: configuration changed during setup. Rerun to review a new plan.")
            temp.replace(self.path)
        finally:
            temp.unlink(missing_ok=True)


def read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""
