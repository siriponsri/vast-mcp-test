import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from .clients import SetupError, child_environment, home


def existing_public_key(value: str) -> Path:
    requested = Path(value.strip().strip('"')).expanduser()
    if not value.strip() or requested.suffix.lower() == ".pub":
        raise SetupError("Enter the path of your personal SSH identity, without .pub.")
    identity = requested.resolve()
    public = identity.with_name(identity.name + ".pub")
    for path in (requested, identity, public.resolve()):
        if any(part.casefold() in {"devtoolssh", "devtoolssh.pub", "devtool_ssh",
                                  "01_vastai_skill"} for part in path.parts):
            raise SetupError("Choose your own SSH identity. The Week 03 example is shared.")
    if not identity.is_file() or not public.is_file():
        raise SetupError("The personal identity and its companion .pub file must both exist.")
    return public


def generate_public_key() -> Path:
    executable = shutil.which("ssh-keygen.exe" if os.name == "nt" else "ssh-keygen")
    if executable is None:
        raise SetupError("OpenSSH ssh-keygen is unavailable. Install it or select an existing identity.")
    folder = home() / ".ssh"
    folder.mkdir(mode=0o700, exist_ok=True)
    identity = folder / f"vast-personal-{uuid4().hex}"
    print("OpenSSH will ask for a passphrase. Use a strong passphrase for your personal key.",
          flush=True)
    result = subprocess.run(
        [executable, "-q", "-t", "ed25519", "-f", str(identity), "-C", "vast-personal"],
        env=child_environment(), shell=False,
    )
    public = identity.with_name(identity.name + ".pub")
    if result.returncode or not public.is_file():
        raise SetupError("OpenSSH could not confirm key generation. Check your .ssh directory.")
    return public


def choose_ssh() -> None:
    while True:
        choice = input("Owner SSH identity [s]kip / [e]xisting / [g]enerate (s): ").strip().lower()
        if choice in {"", "s", "skip"}:
            return
        try:
            if choice in {"e", "existing"}:
                print("Choose a personal key you control. Shared or copied course keys are unsafe.")
                public = existing_public_key(input("Personal identity path: "))
            elif choice in {"g", "generate"}:
                public = generate_public_key()
            else:
                print("Choose s, e, or g.")
                continue
        except (SetupError, OSError, ValueError) as error:
            print(str(error) if isinstance(error, SetupError) else "Unable to use that SSH path.")
            continue
        print(f"Upload only this public key in Vast Console → Keys → SSH Keys: {public}")
        return
