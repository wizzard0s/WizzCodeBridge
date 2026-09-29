"""Persistent planning runs, requirements interviews, and immutable plan versions."""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from agents.providers import chat


def _paths(config):
    base = Path(__file__).resolve().parent
    workspace = Path(config["paths"]["workspace_root"]).resolve()
    project = Path(config["paths"]["project_target"]).resolve()
    runs_value = Path(config.get("paths", {}).get("runs", "runs"))
    runs = runs_value if runs_value.is_absolute() else base / runs_value
    return base, workspace, project, runs


def _workspace_brief(config):
    base, workspace, project, _ = _paths(config)
    files = []
    for root, dirs, names in os.walk(project):
        dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "venv", "__pycache__"}]
        for name in names:
            rel = os.path.relpath(os.path.join(root, name), project)
            files.append(rel)
    files = files[:1500]
    guidance = []
    for parent in (workspace, project):
        for name in ("AGENTS.md", "README.md", "pyproject.toml", "package.json", "requirements.txt",
                     "Dockerfile", "Containerfile", "compose.yaml", "docker-compose.yml"):
            path = parent / name
            if path.is_file():
                try:
                    guidance.append(f"\n--- {path} ---\n{path.read_text(errors='replace')[:12000]}")
                except OSError:
                    pass
    for name in ("AGENTS.md", "SKILL.md"):
        for path in project.rglob(name):
            if any(part in {"node_modules", ".git", ".venv", "venv"} for part in path.parts):
                continue
            try:
                guidance.append(f"\n--- {path} ---\n{path.read_text(errors='replace')[:10000]}")
            except OSError:
                pass
    return f"Workspace: {workspace}\nProject: {project}\nProject files (first 1500):\n" + "\n".join(files) + "\nGuidance and stack files:" + "\n".join(guidance)


def _skill_text(config, role):
    base, workspace, project, _ = _paths(config)
    candidates = [workspace / ".agents/skills", workspace / ".codex/skills", project / "skills",
                  base / "skills"]
    role_config = config.get("roles", {}).get(role, {})
    selected = set(role_config.get("skills", []))
    chunks = []
    for directory in candidates:
        if not directory.is_dir():
            continue
        for path in directory.rglob("SKILL.md"):
            if selected and path.parent.name not in selected and path.stem not in selected:
                continue
            try:
                chunks.append(f"\n--- Skill: {path} ---\n{path.read_text(errors='replace')[:12000]}")
            except OSError:
                pass
    template = role_config.get("template")
    if template:
        for directory in (base / "templates", workspace / "templates", project / "templates"):
            path = directory / template
            if path.is_file():
                chunks.append(f"\n--- Role template: {path} ---\n{path.read_text(errors='replace')[:12000]}")
                break
    return "\n".join(chunks)


def _json_result(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise ValueError("The model did not return the required JSON response. Try again or change its role model.")


def _load(run_path):
    state_path = run_path / "state.json"
    if not state_path.is_file():
        raise ValueError(f"Planning run not found: {run_path.name}")
    return json.loads(state_path.read_text()), state_path


def _save(state, state_path):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def _run_prompt(state, config):
    system = (
        "You are the CodeBridge Requirements Analyst. Interview the user thoroughly before planning. "
        "Ask all important, non-redundant questions together, including behavior, users, constraints, "
        "scope, integrations, data, security, deployment, and acceptance criteria when relevant. "
        "If the user says they do not know, explain practical choices, use workspace evidence, and "
        "ask what is still necessary; do not silently invent high-impact decisions. Research facts only "
        "when an enabled research tool is actually available. Return ONLY JSON with either "
        "{\"status\":\"needs_input\",\"questions\":[...],\"known\":[...],\"assumptions\":[...]} "
        "or {\"status\":\"ready\",\"requirements\":\"...\",\"acceptance_criteria\":[...]," 
        "\"assumptions\":[...],\"open_unknowns\":[...]}. Be complete and specific."
    ) + "\n\nFollow the loaded requirements skill and role template:\n" + _skill_text(config, "requirements")
    if state.get("requirements"):
        system += "\nThe interview appears complete. Return ready unless a consequential gap remains."
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": "Original request:\n" + state["goal"] +
                 "\n\nEnvironment discovery:\n" + state["workspace_brief"] +
                 "\n\nResearcher findings:\n" + json.dumps(state.get("research", {}), ensure_ascii=False) +
                 "\n\nConversation so far:\n" + "\n".join(state["conversation"])}]
    answer, provider, model = chat(config, "requirements", messages)
    state["last_model"] = {"provider": provider, "model": model, "role": "requirements"}
    return _json_result(answer)


def start_run(goal, config):
    _, _, _, runs = _paths(config)
    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_path = runs / run_id
    run_path.mkdir(parents=True, exist_ok=False)
    state = {"id": run_id, "goal": goal, "status": "interview", "created_at": datetime.now().isoformat(),
             "workspace_brief": _workspace_brief(config), "conversation": [], "versions": [],
             "accepted_version": None, "requirements": None}
    research_system = (
        "You are CodeBridge's researcher. Use the supplied workspace evidence and loaded research skill. "
        "Return ONLY JSON: {\"workspace_facts\":[...],\"relevant_files\":[...],\"stack_observations\":[...],"
        "\"external_questions\":[...]}. Do not claim web searches or external facts unless an actual web research "
        "tool is available and was used. Keep assumptions distinct from observed workspace facts.\n\n" +
        _skill_text(config, "researcher")
    )
    research_answer, research_provider, research_model = chat(config, "researcher", [
        {"role": "system", "content": research_system},
        {"role": "user", "content": "Request:\n" + goal + "\n\nWorkspace evidence:\n" + state["workspace_brief"]},
    ])
    state["research"] = _json_result(research_answer)
    state["research_model"] = {"provider": research_provider, "model": research_model}
    result = _run_prompt(state, config)
    state["conversation"].append("Analyst: " + json.dumps(result, ensure_ascii=False))
    if result.get("status") == "ready":
        state["requirements"] = result
        state["status"] = "requirements_ready"
    else:
        state["status"] = "needs_input"
    _save(state, run_path / "state.json")
    return state, result


def answer_run(run_id, answer, config):
    _, _, _, runs = _paths(config)
    run_path = runs / run_id
    state, state_path = _load(run_path)
    if state["status"] not in {"needs_input", "interview"}:
        raise ValueError(f"Run is not waiting for interview input (status: {state['status']})")
    state["conversation"].append("User: " + answer)
    result = _run_prompt(state, config)
    state["conversation"].append("Analyst: " + json.dumps(result, ensure_ascii=False))
    if result.get("status") == "ready":
        state["requirements"] = result
        state["status"] = "requirements_ready"
    else:
        state["status"] = "needs_input"
    _save(state, state_path)
    return state, result


def create_plan(run_id, config):
    _, _, _, runs = _paths(config)
    run_path = runs / run_id
    state, state_path = _load(run_path)
    if state["status"] != "requirements_ready":
        raise ValueError("Complete the requirements interview before asking the architect to plan.")
    system = ("You are CodeBridge's software architect. Use the requirements and discovered workspace stack, "
              "architecture, existing skills and templates. Return ONLY JSON: {\"plan\":\"Markdown plan\", "
              "\"risks\":[...],\"execution_tasks\":[{\"title\":\"...\",\"target\":\"relative/path\","
              "\"acceptance\":[\"...\"]}]}. Tasks must be ordered, concrete, and respect existing project conventions.")
    context = _skill_text(config, "architect")
    prior_plans = []
    for item in state["versions"]:
        try:
            prior_plans.append(f"\n--- Previous plan {item['id']} ({item['status']}) ---\n" +
                               Path(item["path"]).read_text(errors="replace")[:16000])
        except (OSError, KeyError):
            continue
    user = "Goal:\n" + state["goal"] + "\nRequirements:\n" + json.dumps(state["requirements"], ensure_ascii=False) + \
           "\nResearcher findings:\n" + json.dumps(state.get("research", {}), ensure_ascii=False) + \
           "\nEnvironment:\n" + state["workspace_brief"] + "\nRelevant skills/templates:\n" + context + \
           "\nPrior plan history and revision context:\n" + "\n".join(prior_plans)
    answer, provider, model = chat(config, "architect", [{"role": "system", "content": system},
                                                          {"role": "user", "content": user}])
    result = _json_result(answer)
    version = len(state["versions"]) + 1
    version_id = f"v{version:03d}"
    plan_doc = (f"# Plan {version_id}\n\nRun: {run_id}\n\n## Goal\n{state['goal']}\n\n"
                f"## Requirements\n{state['requirements'].get('requirements', '')}\n\n"
                f"## Plan\n{result.get('plan', '')}\n\n## Risks\n" +
                "\n".join(f"- {item}" for item in result.get("risks", [])) + "\n\n## Tasks\n" +
                "\n".join(f"{i}. {task.get('title')} — `{task.get('target')}`\n" +
                         "   " + "; ".join(task.get("acceptance", []))
                         for i, task in enumerate(result.get("execution_tasks", []), 1)) + "\n")
    plan_path = run_path / "versions" / f"{version_id}.md"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(plan_doc)
    state["versions"].append({"id": version_id, "path": str(plan_path), "status": "pending_approval",
                              "created_at": datetime.now().isoformat(), "provider": provider, "model": model,
                              "tasks": result.get("execution_tasks", [])})
    state["status"] = "plan_pending_approval"
    _save(state, state_path)
    return state, plan_doc


def accept_plan(run_id, config):
    _, _, _, runs = _paths(config)
    run_path = runs / run_id
    state, state_path = _load(run_path)
    if state["status"] != "plan_pending_approval" or not state["versions"]:
        raise ValueError("There is no plan awaiting approval.")
    latest = state["versions"][-1]
    latest["status"] = "accepted"
    state["accepted_version"] = latest["id"]
    state["status"] = "plan_accepted"
    project = Path(config["paths"]["project_target"]).resolve()
    checklist = []
    for task in latest.get("tasks", []):
        target = Path(task.get("target", "N/A"))
        if not target.is_absolute() and str(target) != "N/A":
            target = project / target
        scope = "; ".join(task.get("acceptance", []))
        title = task.get("title", "Implementation task")
        checklist.append(f"- [ ] {title} | Target File: {target} | Scope: {scope}")
    (run_path / "checklist.md").write_text(
        f"# Accepted plan {latest['id']} — run {run_id}\n\n" + "\n".join(checklist) + "\n"
    )
    _save(state, state_path)
    return state


def revise_plan(run_id, reason, config):
    """Keep prior versions and draft a new one after execution reveals a change."""
    _, _, _, runs = _paths(config)
    run_path = runs / run_id
    state, state_path = _load(run_path)
    if state["status"] not in {"plan_accepted", "plan_pending_approval"}:
        raise ValueError("Only an accepted or pending plan can be revised.")
    if state["versions"]:
        state["versions"][-1]["status"] = "superseded" if state["status"] == "plan_accepted" else "rejected_for_revision"
    state["requirements"]["revision_request"] = reason
    state["requirements"]["requirements"] += "\n\nPlan revision requested: " + reason
    state["status"] = "requirements_ready"
    _save(state, state_path)
    return create_plan(run_id, config)
