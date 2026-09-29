# CodeBridge

CodeBridge is a local-first multi-role workflow with a VS Code control panel. Provider and model defaults are in `config.yaml`; OpenRouter credentials stay in `OPENROUTER_API_KEY` or the ignored `.env` file.

## Planning and execution

Start a plan in the CodeBridge panel. The researcher inspects the configured project and its guidance. The requirements analyst interviews you and pauses for answers until requirements are ready. The architect then creates a versioned plan. Type `ACCEPT` in the panel to approve it. Only an accepted plan can be executed.

The VS Code workspace folder becomes the workspace context. Set `codebridge.projectTarget` in workspace settings to choose the project directory CodeBridge should inspect and edit; when empty, it uses `paths.project_target` from `config.yaml`.

Use **Revise plan** with a reason when execution reveals a change. The new version waits for approval, while previous plan files remain in the run history under `runs/<run-id>/versions/`.

The panel can choose a provider and model for each role. With the YAML defaults, roles try their local Ollama model first and use the configured OpenRouter fallback if local inference fails. The implementer defaults to local-only. The OpenRouter key is shared across roles and is never written to run state.

Terminal approval is a workspace setting. **Prompt** is the default; approve a command by entering `y` in the panel. **Auto** runs bridge terminal commands without asking each time. Current execution uses this gate for the verifier's Podman build command.

## Skills and templates

Role skills and output templates live under `skills/` and `templates/`. CodeBridge also reads workspace `.agents/skills`, `.codex/skills`, `AGENTS.md`, and relevant project guidance. Extend role `skills`, `template`, `tools`, and provider/model entries in `config.yaml` to add reusable behavior.

## Current integration limits

The web research plugin is declared but disabled until a real search adapter is configured. The researcher uses local workspace evidence and records external questions; it does not claim to browse. The implementer edits accepted task files and the verifier returns bounded findings to it. The terminal approval path currently covers the bridge's verifier command; a general model-invoked terminal tool adapter remains to be added before agents can request arbitrary commands.

For command line use, run `python3 main.py plan "your goal"` from this directory. Planning prompts for each answer and for plan approval. Run `python3 main.py execute <run-id>` only after approval. `python3 main.py revise <run-id> "reason"` creates a new version for review.
