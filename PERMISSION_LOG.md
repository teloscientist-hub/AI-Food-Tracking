# Permission Log

This file tracks command approvals relevant to the `mml-food-tracking` project so we can decide which ones should become persistent auto-approvals.

Project-local policy files:
- `AUTO_PERMISSIONS.toml`
- `AGENTS.md`

These files tell future Codex sessions in this repo to check the local allowlist first before asking for approval. They do not override the Codex app’s built-in approval prompts by themselves.

Project-local edit rule:
- The user has preapproved creating and editing any file inside this project folder as needed for the work.
- This covers project files like HTML, CSS, JS, Python, tests, docs, and local policy files.
- This does not grant broader filesystem permissions outside the project root or override the Codex app’s sandbox rules.

Notes:
- Only narrow, scoped command prefixes should be auto-approved.
- Broad interpreters like `python3`, `python`, `bash`, or `zsh` should not be blanket-approved.
- This log is project-focused, not a full global history for every workspace.

## Status Key

- `approved`: already approved in Codex
- `candidate`: good candidate for persistent auto-approval
- `avoid`: too broad or risky for blanket approval

## Existing Project-Relevant Approvals

| Prefix / Command Pattern | Status | Notes |
| --- | --- | --- |
| `python3 -m venv .venv` | approved | Safe project bootstrap command. |
| `python3 -m pip install ...` | approved | Dependency installation for this repo. |
| `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port ...` | approved | Safe local app run pattern for this project. |
| `ls -la` | approved | Used while setting up the local project permission policy files. |
| `test -f AGENTS.md` | approved | Used to check whether the repo already had project agent instructions. |
| `sed -n ...` | approved | Used to inspect `PERMISSION_LOG.md`, `AGENTS.md`, and `~/.codex/config.toml` during permission setup. |
| `rg -n ...` | approved | Used to inspect Codex global state/config for any file-based approval storage. |
| `git add .` | approved | Useful but broad inside repo; still acceptable for this project. |
| `git add -A` | approved | Same caveat as `git add .`. |
| `git commit -m ...` | approved | Standard non-interactive commit flow. |
| `git push origin main` | approved | Safe for this repo once intentional. |
| `git push -u origin main` | approved | Safe initial upstream push. |
| `git remote add ...` | approved | Already used for this project. |
| `git remote set-url ...` | approved | Useful if remote changes. |
| `git branch --set-upstream-to=origin/main main` | approved | Harmless repo setup command. |
| `kill <pid>` | approved | Useful for restarting local dev server. |

## Commands We Should Usually Prefer For Auto-Approval

| Prefix / Command Pattern | Status | Notes |
| --- | --- | --- |
| `.venv/bin/pytest` | candidate | Ideal recurring test command for this project. |
| `.venv/bin/pytest tests/test_resolution.py` | candidate | Narrow recurring resolution test command. |
| `.venv/bin/pytest tests/test_off_client.py tests/test_resolution.py` | candidate | Useful for external lookup regression checks. |
| `.venv/bin/pytest tests/test_web_submit.py` | candidate | Useful for submit/redirect regression checks. |
| `.venv/bin/pytest tests/test_picker_foods.py` | candidate | Useful for picker/library ordering checks. |
| `git push origin <branch>` | candidate | Useful once branch workflow expands beyond `main`. |
| `lsof -t -iTCP:8000 -sTCP:LISTEN` | candidate | Safe helper for restarting the local dev server. |
| `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000` | approved | Local app server run command already used repeatedly. |
| `git fetch` | approved | Already approved globally; safe and useful. |

## Commands To Avoid Blanket Approval

| Prefix / Command Pattern | Status | Notes |
| --- | --- | --- |
| `python3` | avoid | Too broad; allows arbitrary Python execution. |
| `python` | avoid | Too broad. |
| `bash` | avoid | Too broad. |
| `zsh` | avoid | Too broad. |
| `/bin/zsh -lc ...` | avoid | Too broad as a persistent approval. |

## Future Requests

Append new permission requests here as they come up:

| Date | Command / Prefix | Requested For | Outcome | Notes |
| --- | --- | --- | --- | --- |
| 2026-04-24 | `.venv/bin/pytest` | Run project test suite | pending | Recommend adding as a persistent approval if not already approved. |
| 2026-04-24 | `lsof -t -iTCP:8000 -sTCP:LISTEN` | Check active dev server PID before restart | pending | Good narrow local-server helper. |
| 2026-04-24 | `.venv/bin/pytest tests/test_resolution.py` | Resolution/ranking verification | pending | Narrow recurring test command. |
| 2026-04-24 | `.venv/bin/pytest tests/test_off_client.py tests/test_resolution.py` | OFF + resolver verification | pending | Useful when tuning external sources. |
| 2026-04-25 | `.venv/bin/pytest tests/test_web_submit.py` | Review submit / blank-input verification | pending | Useful targeted web regression command. |
| 2026-04-25 | `.venv/bin/pytest tests/test_picker_foods.py` | Picker/library ordering verification | pending | Useful targeted picker regression command. |
| 2026-05-02 | `ls -la` | Inspect project root before creating local permission policy files | approved | Used to place `AUTO_PERMISSIONS.toml` and `AGENTS.md` correctly. |
| 2026-05-02 | `test -f AGENTS.md` | Check whether project already had agent instructions | approved | Confirmed no existing file before creation. |
| 2026-05-02 | `sed -n ...` | Inspect `PERMISSION_LOG.md`, `AGENTS.md`, and `~/.codex/config.toml` | approved | Used to build the project-local permission policy. |
| 2026-05-02 | `rg -n ...` | Search Codex config/global state for approval records | approved | Confirmed there is no user-editable global auto-approval file. |
| 2026-05-02 | Project file create/edit within repo root | Create and edit any project file needed for the work | approved | User preapproved creating and editing files anywhere inside the project folder. |

## Recommended Auto-Approve Set

These are the narrow prefixes most worth approving for this project:

| Prefix / Command Pattern | Why |
| --- | --- |
| `.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000` | Start the local FastAPI app. |
| `.venv/bin/pytest` | Run tests in the project venv. |
| `kill <pid>` | Stop a stale local dev server. |
| `lsof -t -iTCP:8000 -sTCP:LISTEN` | Find the dev server PID safely. |
| `git add .` | Stage project changes. |
| `git add -A` | Stage project changes including deletions. |
| `git commit -m ...` | Create non-interactive commits. |
| `git push origin main` | Push the main branch. |
| `git push -u origin main` | Initial upstream push. |
| `git remote add ...` | Set the repo remote. |
| `git remote set-url ...` | Update the repo remote. |
| `git branch --set-upstream-to=origin/main main` | Keep local branch tracking configured. |

## Limits

- I did not find a user-editable Codex “auto-approve commands” file in `~/.codex`.
- The actual persistent approval list appears to be managed by the Codex app/UI rather than a plain local config file we can safely patch here.
- This log plus `AUTO_PERMISSIONS.toml` are therefore the project-side source of truth for what should be added in the UI.
