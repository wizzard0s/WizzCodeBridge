"""Checklist planning helper used by the dependency handoff path."""
import os
import re

from agents.providers import chat


def _insert_tasks_before(checklist_path, before_task_name, new_tasks_text):
    if not os.path.exists(checklist_path):
        with open(checklist_path, "w") as output:
            output.write(f"# CodeBridge Master Task Checklist\n\n{new_tasks_text}\n")
        return
    with open(checklist_path, "r") as source:
        lines = source.readlines()
    insertion_index = None
    if before_task_name:
        for index, line in enumerate(lines):
            if line.strip().startswith("- [") and before_task_name in line:
                insertion_index = index
                break
    new_lines = [f"{line}\n" for line in new_tasks_text.strip().splitlines()]
    if insertion_index is None:
        lines.extend(["\n"] + new_lines + ["\n"])
    else:
        lines[insertion_index:insertion_index] = new_lines + ["\n"]
    with open(checklist_path, "w") as output:
        output.writelines(lines)


def run_planning_phase(user_input, config, checklist_path, append_mode=False, before_task=None):
    """Use the shared local-first architect route to add ordered checklist tasks."""
    existing_tasks = ""
    if append_mode and os.path.exists(checklist_path):
        with open(checklist_path, "r") as source:
            existing_tasks = source.read()
    system_prompt = (
        "You are the CodeBridge architect. Return only Markdown task lines in this exact format: "
        "- [ ] Task Name | Target File: relative/path | Scope: acceptance requirements. "
        "Do not add prose or code fences."
    )
    if append_mode:
        system_prompt += (
            " Output only new prerequisite tasks that are absent from this active checklist:\n" + existing_tasks
        )
    try:
        raw, _, _ = chat(config, "architect", [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ])
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", raw.strip(), flags=re.I)
        if append_mode:
            _insert_tasks_before(checklist_path, before_task, cleaned)
        else:
            with open(checklist_path, "w") as output:
                output.write(f"# CodeBridge Master Task Checklist\n\n{cleaned}\n")
    except Exception as error:
        print(f"Could not ask the configured architect model to plan: {error}")
