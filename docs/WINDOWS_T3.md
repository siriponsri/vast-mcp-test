# Windows path and account details

Open PowerShell in the trusted checkout. Quote paths with spaces or Thai characters when changing directory. Setup passes each argument separately and uses the absolute locked-venv Python executable. Native executables and standard npm CLI layouts are supported. For npm shims, setup resolves the installed JavaScript entry point and runs it with Node.

Codex setup targets the main `%USERPROFILE%\.codex` account. If `CODEX_HOME` points elsewhere, use the primary owner terminal. Use the default Claude Code profile with `CLAUDE_CONFIG_DIR` unset. The local stdio server starts directly through the client. Close other tools that might edit these client files while you apply a plan.

Setup prompts for SSH after client registration. Existing identities are checked by path and file metadata. For a new identity, local OpenSSH writes a uniquely named pair under `%USERPROFILE%\.ssh` and prompts for a passphrase. Use your own key. The wizard rejects recognized Week 03 example paths and names. It prints the companion public-key path for registration. Upload the `.pub` file in [Vast Console](https://cloud.vast.ai/manage-keys/).

See [T3 and Claude acceptance steps](T3_SETUP.md).
