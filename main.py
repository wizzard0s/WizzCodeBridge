import os
import sys
import json
import yaml
from dotenv import load_dotenv
from agents.planner import run_planning_phase
from agents.orchestrator import parse_next_task, evaluate_workspace_dependencies
from agents.coder import execute_local_code_write
from agents.verifier import run_validation_tests, review_implementation
from workflow import start_run, answer_run, create_plan, accept_plan, revise_plan

def load_system_config():
    """Dynamically reads paths, keys, and model parameters at runtime."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
    if not os.path.exists(config_path):
        print(f"❌ Critical Error: Configuration file missing at {config_path}")
        print("💡 Tip: Run your utility script to re-generate the baseline structure.")
        sys.exit(1)

    # Load OPENROUTER_API_KEY (and any other secrets) from .env into the
    # environment without overriding vars already set in the shell.
    load_dotenv(os.path.join(os.path.dirname(config_path), ".env"))

    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    config["paths"]["workspace_root"] = os.environ.get(
        "CODEBRIDGE_WORKSPACE_ROOT", config["paths"]["workspace_root"]
    )
    config["paths"]["project_target"] = os.environ.get(
        "CODEBRIDGE_PROJECT_TARGET", config["paths"]["project_target"]
    )
    # Keep provider credentials out of configuration and run records.
    config["workflow"]["terminal_approval"] = os.environ.get(
        "CODEBRIDGE_TERMINAL_APPROVAL", config.get("workflow", {}).get("terminal_approval", "prompt")
    ).lower()
    for role_name, role in config.get("roles", {}).items():
        prefix = "CODEBRIDGE_ROLE_" + role_name.upper()
        role["provider"] = os.environ.get(prefix + "_PROVIDER", role.get("provider", "ollama"))
        role["model"] = os.environ.get(prefix + "_MODEL", role.get("model", ""))
    return config


def _print_questions(result):
    print("\nRequirements analyst needs your input:")
    for i, question in enumerate(result.get("questions", []), 1):
        print(f"{i}. {question}")
    if result.get("assumptions"):
        print("Current assumptions:")
        for item in result["assumptions"]:
            print(f"- {item}")


def run_interactive_plan(goal, config):
    """Interview until ready, draft an immutable plan version, and wait for approval."""
    state, result = start_run(goal, config)
    run_id = state["id"]
    print(f"CodeBridge run: {run_id}")
    print("\nResearcher workspace findings:")
    print(json.dumps(state.get("research", {}), ensure_ascii=False, indent=2))
    while state["status"] == "needs_input":
        _print_questions(result)
        answer = input("Your answer (you can say 'I don't know'): ").strip()
        state, result = answer_run(run_id, answer, config)
    print("\nRequirements are ready:")
    print(json.dumps(state["requirements"], ensure_ascii=False, indent=2))
    print("\nArchitect is preparing a plan from the discovered workspace and requirements...")
    state, plan_doc = create_plan(run_id, config)
    print("\n" + plan_doc)
    print(f"\nPlan {state['versions'][-1]['id']} is saved and awaiting your approval.")
    decision = input("Type ACCEPT to approve this plan, or press Enter to leave it pending: ").strip()
    if decision.upper() == "ACCEPT":
        state = accept_plan(run_id, config)
        print(f"Accepted {state['accepted_version']}. Run ID: {run_id}")
    else:
        print(f"Plan remains pending. Review it in {state['versions'][-1]['path']}; run ID: {run_id}")


def approve_terminal_command(command, config):
    if config.get("workflow", {}).get("terminal_approval", "prompt") == "auto":
        return True
    print(f"\nTerminal command requires approval:\n  {command}")
    return input("Run this command? [y/N] ").strip().lower() in {"y", "yes"}

def update_checklist_status(checklist_path, task_name, new_status):
    """Updates the state engine markdown task markers dynamically."""
    if not os.path.exists(checklist_path):
        return
        
    with open(checklist_path, "r") as f:
        lines = f.readlines()
        
    with open(checklist_path, "w") as f:
        for line in lines:
            if task_name in line:
                if new_status == "IP":
                    line = line.replace("[ ]", "[IP]")
                elif new_status == "X":
                    line = line.replace("[IP]", "[X]").replace("[ ]", "[X]")
                elif new_status == " ":
                    line = line.replace("[IP]", "[ ]")
            f.write(line)

def main():
    # 1. Load context configuration properties safely
    config = load_system_config()
    checklist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checklist.md")
    
    print("====================================================")
    print("🚀 CodeBridge Multi-Role Workflow Active")
    print("====================================================")

    # 2. Command Line Router Switch
    if len(sys.argv) < 2:
        print("\n🤖 Available Commands:")
        print("  python3 main.py plan \"your goal\"  <- Interview, plan, and request approval")
        print("  python3 main.py execute <run-id>   <- Execute an accepted plan")
        print("  python3 main.py revise <run-id> \"reason\" <- Create a new plan version")
        sys.exit(0)
        
    mode = sys.argv[1].lower()

    # Planning interview, environment discovery, and versioned plan approval
    if mode == "plan":
        if len(sys.argv) < 3:
            print("❌ Error: Please provide an engineering task objective prompt string.")
            sys.exit(1)
        user_prompt = sys.argv[2]
        try:
            run_interactive_plan(user_prompt, config)
        except (RuntimeError, ValueError) as error:
            print(f"Planning stopped: {error}")
            sys.exit(1)

    elif mode == "accept" and len(sys.argv) >= 3:
        state = accept_plan(sys.argv[2], config)
        print(f"Accepted plan {state['accepted_version']} for run {state['id']}.")

    elif mode == "revise" and len(sys.argv) >= 4:
        state, plan_doc = revise_plan(sys.argv[2], " ".join(sys.argv[3:]), config)
        print(plan_doc)
        print(f"Plan {state['versions'][-1]['id']} awaits approval. Run: {state['id']}")
        if input("Type ACCEPT to approve this new version, or press Enter to keep it pending: ").strip().upper() == "ACCEPT":
            state = accept_plan(sys.argv[2], config)
            print(f"Accepted {state['accepted_version']}. Run ID: {state['id']}")

    # PHASE 2: ISOLATED LOCAL STEP LOOPS
    elif mode == "execute":
        if len(sys.argv) < 3:
            print("❌ Provide a run ID with an accepted plan.")
            sys.exit(1)
        run_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs", sys.argv[2])
        checklist_path = os.path.join(run_dir, "checklist.md")
        state_path = os.path.join(run_dir, "state.json")
        run_state = {}
        if os.path.isfile(state_path):
            with open(state_path, "r") as state_file:
                run_state = json.load(state_file)
        if run_state.get("status") != "plan_accepted" or not os.path.isfile(checklist_path):
            print(f"❌ Run {sys.argv[2]} has no currently accepted plan to execute.")
            sys.exit(1)
        print("\n💼 Inspecting master state checklist for remaining subtasks...")
        
        while True:
            # Call orchestrator to parse the next uncompleted task item
            next_task = parse_next_task(checklist_path)
            
            if not next_task:
                print("\n🎉 All milestones successfully implemented and verified! CodeBridge stopping.")
                break
                
            print(f"\n⚡ Next Milestone Identified: '{next_task['name']}'")
            print(f"📂 Component Working Path: {next_task['target_file']}")

            project_root = os.path.realpath(config["paths"]["project_target"])
            target_path = os.path.realpath(next_task["target_file"])
            if os.path.commonpath([project_root, target_path]) != project_root:
                print(f"❌ Refusing to write outside the configured project: {target_path}")
                sys.exit(1)
            
            # Set state status to In Progress
            update_checklist_status(checklist_path, next_task['name'], "IP")
            
            # 🔥 NEW ARCHITECTURAL CONTEXT CHECK
            # Verify if workspace dependencies are satisfied before letting the local model write code
            is_workspace_ready = evaluate_workspace_dependencies(next_task, config, checklist_path)
            if not is_workspace_ready:
                print("📋 Checklist state engine successfully patched with new tools. Restarting orchestration loop.")
                # Reset item status back to open so it runs after its new dependencies are complete
                update_checklist_status(checklist_path, next_task['name'], " ")
                continue  # Loops back instantly to parse the newly injected items first!
            
            # Invoke Local Coder with context filtration parameters
            print("💻 Assigning implementation task to its configured model...")
            existing = "(file does not exist yet)"
            if os.path.isfile(target_path):
                with open(target_path, "r", errors="replace") as target_file:
                    existing = target_file.read()[:30000]
            guidance = []
            for guidance_path in (os.path.join(config["paths"]["workspace_root"], "AGENTS.md"),
                                  os.path.join(project_root, "AGENTS.md")):
                if os.path.isfile(guidance_path):
                    with open(guidance_path, "r", errors="replace") as guidance_file:
                        guidance.append(f"--- {guidance_path} ---\n{guidance_file.read()[:12000]}")
            current = os.path.dirname(target_path)
            while os.path.commonpath([project_root, current]) == project_root:
                guidance_path = os.path.join(current, "AGENTS.md")
                if guidance_path not in (os.path.join(config["paths"]["workspace_root"], "AGENTS.md"),
                                         os.path.join(project_root, "AGENTS.md")) and os.path.isfile(guidance_path):
                    with open(guidance_path, "r", errors="replace") as guidance_file:
                        guidance.append(f"--- {guidance_path} ---\n{guidance_file.read()[:12000]}")
                if current == project_root:
                    break
                current = os.path.dirname(current)
            file_context = (
                f"Project root: {project_root}\nTarget File Location: {target_path}\n"
                f"Scope Constraints: {next_task['scope']}\n\nWorkspace guidance:\n" +
                "\n".join(guidance) + f"\n\nCurrent target file contents:\n{existing}"
            )
            generated_code = execute_local_code_write(next_task['instruction'], file_context, config)
            
            if not generated_code:
                print("❌ Coder execution failed. Aborting pipeline loop.")
                sys.exit(1)
                
            max_retries = int(config.get("workflow", {}).get("max_retries", 3))
            for attempt in range(max_retries + 1):
                print(f"💾 Writing implementation attempt {attempt + 1} to {target_path}...")
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, "w") as target_file:
                    target_file.write(generated_code)

                print("🧪 Running configured validation and verifier review...")
                test_passed, error_log = run_validation_tests(
                    config["paths"]["project_target"],
                    approval_callback=lambda command: approve_terminal_command(command, config)
                )
                if error_log == "Terminal command declined by user.":
                    print("⏸️ Terminal command was declined. Task remains open for later resumption.")
                    update_checklist_status(checklist_path, next_task['name'], " ")
                    sys.exit(0)
                evidence = f"Validation passed: {test_passed}\nValidation output: {error_log}"
                review = review_implementation(next_task["instruction"], generated_code, config, evidence)
                status = review.get("status", "needs_changes")
                findings = review.get("findings", [])
                if test_passed and status == "pass":
                    print("✅ Verifier passed. Milestone fully resolved.")
                    update_checklist_status(checklist_path, next_task['name'], "X")
                    break
                details = "\n".join(str(item) for item in findings) or error_log
                print(f"Verifier status: {status}\n{details}")
                if status == "blocked" or attempt >= max_retries:
                    update_checklist_status(checklist_path, next_task['name'], " ")
                    print("🛑 Task paused for plan revision or user guidance.")
                    sys.exit(1)

                print("↩️ Returning verifier findings to the implementer for a bounded correction pass.")
                retry_context = file_context + f"\n\nVerifier findings from attempt {attempt + 1}:\n{details}"
                generated_code = execute_local_code_write(
                    next_task["instruction"] + "\n\nCorrect these verifier findings:\n" + details,
                    retry_context,
                    config,
                )
                if not generated_code:
                    update_checklist_status(checklist_path, next_task['name'], " ")
                    print("Implementer failed during correction; task remains open.")
                    sys.exit(1)

    else:
        print(f"❌ Unknown action keyword identifier: {mode}")

if __name__ == "__main__":
    main()
