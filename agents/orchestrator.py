import os
import json
from agents.providers import chat
from agents.planner import run_planning_phase


def evaluate_workspace_dependencies(next_task, config, checklist_path):
    """
    Leverages the cloud engine to inspect if the upcoming task requires files or tools
    that haven't been created yet. If missing layers are caught, it automatically
    re-routes execution back to the Planner to inject prerequisite milestones
    directly ahead of this task in checklist.md.
    """
    # Scan existing directory landscape to give the orchestrator spatial visibility
    workspace_files = []
    project_target = config["paths"]["project_target"]
    for root, _, files in os.walk(project_target):
        for file in files:
            workspace_files.append(os.path.relpath(os.path.join(root, file), project_target))

    evaluation_prompt = (
        f"Upcoming Task Objective: {next_task['name']}\n"
        f"Target Destination Path: {next_task['target_file']}\n"
        f"Scope Parameter Data: {next_task['scope']}\n\n"
        f"Active files currently existing on disk: {json.dumps(workspace_files)}\n\n"
        "CRITICAL INSTRUCTION:\n"
        "Evaluate if this task requires helper modules, database models, scrapers, or styles "
        "that are completely missing from the existing files list. "
        "Reply with EXACTLY 'OK' if the workspace is ready. "
        "If a tool layer is missing, reply with an architectural description of what needs to be built first."
    )

    try:
        decision, _, _ = chat(config, "architect", [
            {"role": "system", "content": "You are the CodeBridge orchestrator. Reply exactly OK if the task can proceed. Otherwise describe only the missing prerequisite layer."},
            {"role": "user", "content": evaluation_prompt},
        ])
        decision = decision.strip()
        if decision.startswith("OK"):
            return True
        print(f"⚠️ Orchestration pivot: prerequisite needed: {decision}")
        run_planning_phase(
            f"Prerequisite required before building {next_task['name']}: {decision}",
            config,
            checklist_path,
            append_mode=True,
            before_task=next_task['name']
        )
        return False
    except Exception as e:
        print(f"⚠️ Orchestrator evaluation loop timeout bypass: {str(e)}")
        return True  # Fall back safely to linear execution if network delays occur


def parse_next_task(checklist_path):
    """
    Reads the checklist file line by line to locate the first uncompleted task,
    handling variable whitespace indents and parsing metrics cleanly.
    """
    if not os.path.exists(checklist_path):
        print("❌ Error: Master checklist.md state file is missing.")
        return None

    with open(checklist_path, "r") as f:
        lines = f.readlines()

    for line in lines:
        stripped_line = line.strip()
        
        # Robust match: catches the line even if it is indented or contains spaces
        if stripped_line.startswith("- [ ]") or stripped_line.startswith("[ ]"):
            try:
                # Normalize line syntax hooks
                cleaned_line = stripped_line.replace("- [ ]", "").replace("[ ]", "").strip()
                
                # Split along our predefined absolute piping boundaries
                parts = cleaned_line.split(" | ")
                if len(parts) < 3:
                    continue  # Malformed line, skip it safely
                    
                task_name = parts[0].strip()
                target_file = parts[1].replace("Target File:", "").strip()
                scope_details = parts[2].replace("Scope:", "").strip()
                
                # Formulate the comprehensive execution instruction string for the local coder
                instruction = (
                    f"Write the complete programmatic implementation code for the following task: '{task_name}'.\n"
                    f"Target File Location: {target_file}\n"
                    f"Scope requirements to satisfy: {scope_details}\n"
                    f"Ensure you output pure raw syntax code only, matching standard English constraints."
                )
                
                return {
                    "name": task_name,
                    "target_file": target_file,
                    "scope": scope_details,
                    "instruction": instruction
                }
            except Exception as e:
                # Fallback to catch indexing hitch errors
                continue
                
    return None
