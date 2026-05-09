# Project Agent Instructions

This project uses a local permission policy file:

- `AUTO_PERMISSIONS.toml`
- `PERMISSION_LOG.md`

## Required permission workflow

For any future Codex session in this project:

1. Read `AUTO_PERMISSIONS.toml` before requesting escalation.
2. If a requested command matches a listed approved prefix, treat it as user-preapproved project policy.
3. Within the project root, creating and editing project files is preapproved by the user. Do not ask again just because the file is HTML, CSS, JS, Python, tests, docs, or another project file under this repo.
4. If the Codex app itself still prompts anyway, explain briefly that the local policy allows it but the app-level approval is still required.
5. If a new permission is requested and the user approves it, update:
   - `PERMISSION_LOG.md`
   - `AUTO_PERMISSIONS.toml`
6. Do not treat broad interpreters like `python3`, `bash`, `zsh`, or `/bin/zsh -lc ...` as blanket-approved unless the user explicitly says so and the app also persists that approval.

## Important limitation

`AUTO_PERMISSIONS.toml` is a project-local policy file that Codex should read and follow.
It does **not** by itself override the Codex app’s native approval system.
If the app does not already have a matching persisted prefix approval, Codex may still need to ask the user.
