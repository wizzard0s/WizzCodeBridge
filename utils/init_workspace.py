"""Create missing CodeBridge state and extension directories without replacing user files."""
from pathlib import Path


def initialize_workspace():
    bridge_root = Path(__file__).resolve().parents[1]
    for name in ("agents", "runs", "skills", "templates"):
        (bridge_root / name).mkdir(parents=True, exist_ok=True)
    checklist = bridge_root / "checklist.md"
    if not checklist.exists():
        checklist.write_text("# CodeBridge Master Task Checklist\n\n")
    print(f"CodeBridge directories are ready at {bridge_root}")
    print("Existing config, skills, plans, and agent files were left intact.")


if __name__ == "__main__":
    initialize_workspace()
