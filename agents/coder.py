"""Implementation role backed by the configured provider and local-first router."""
import re
from pathlib import Path

from agents.providers import chat


def execute_local_code_write(prompt, file_context, config):
    role = config.get("roles", {}).get("implementer", {})
    base = Path(__file__).resolve().parents[1]
    instructions = []
    for directory in (base / "skills", Path(config["paths"]["project_target"]) / "skills",
                      Path(config["paths"]["workspace_root"]) / ".agents/skills",
                      Path(config["paths"]["workspace_root"]) / ".codex/skills"):
        for skill in role.get("skills", []):
            path = directory / skill / "SKILL.md"
            if path.is_file():
                instructions.append(path.read_text(errors="replace")[:12000])
    template = role.get("template")
    if template:
        for directory in (base / "templates", Path(config["paths"]["project_target"]) / "templates"):
            path = directory / template
            if path.is_file():
                instructions.append(path.read_text(errors="replace")[:12000])
                break
    system = (
        "You are CodeBridge's implementation role. Implement only the accepted task using provided "
        "workspace context and instructions. Return the complete contents of the requested target file "
        "as raw code, without markdown fences or commentary. Do not invent successful checks.\n\n" +
        "\n\n".join(instructions)
    )
    answer, _, _ = chat(config, "implementer", [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Workspace context:\n{file_context}\n\nAccepted task:\n{prompt}"},
    ], temperature=0.05)
    match = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*\n(.*?)```", answer, re.DOTALL)
    return (match.group(1) if match else answer).strip()
