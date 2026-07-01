import os
import time
import httpx
from crewai import Agent, Task, Crew, Process, LLM
from markdown_it import MarkdownIt
from mdit_py_plugins.tasklists import tasklists_plugin

# --- Core Infrastructure Parameters ---
VIKUNJA_API_URL = os.getenv("VIKUNJA_API_URL")
VIKUNJA_BEARER_TOKEN = os.getenv("VIKUNJA_BEARER_TOKEN")
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "nemoclaw")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "NA")

# Comma-separated list of names to watch (Default: crewai,crewai-test)
TARGET_PROJECT_CONFIG = os.getenv("TARGET_PROJECT_NAMES", "crewai,crewai-test")
TARGET_PROJECT_NAMES = [name.strip() for name in TARGET_PROJECT_CONFIG.split(",") if name.strip()]

print(f"[CrewAI Daemon] Initializing cluster worker targeting model: {LOCAL_LLM_MODEL}")
print(f"[CrewAI Daemon] Base URL: {LOCAL_LLM_BASE_URL}")
print(f"[CrewAI Daemon] Listening on target projects configuration: {TARGET_PROJECT_NAMES}")

headers = {
    "Authorization": f"Bearer {VIKUNJA_BEARER_TOKEN}",
    "Content-Type": "application/json"
}


def display_api_telemetry_banner():
    """Queries and outputs version schemas from the running Vikunja service instance
    to streamline cross-version developer support and debugging.
    """
    print("=" * 70)
    print("[Telemetry Router] Gathering target API environment metadata...")
    print(f" -> Base Endpoint target: {VIKUNJA_API_URL}")

    # Clean up string manipulation to identify base server root /info route
    base_root = VIKUNJA_API_URL.split("/api/v1")[0] if "/api/v1" in VIKUNJA_API_URL else VIKUNJA_API_URL
    info_url = f"{base_root}/api/v1/info"

    try:
        with httpx.Client(timeout=5.0) as client:
            response = client.get(info_url, headers=headers)
            if response.status_code == 200:
                info_data = response.json()
                version = info_data.get("version", "Unknown Microversion")
                frontend = info_data.get("frontend_url", "N/A")
                auth_kind = info_data.get("auth", {}).get("local", {}).get("enabled", True)

                print(f" -> Vikunja Core Engine Version: \033[92m{version}\033[0m")
                print(f" -> Connected Workspace View: {frontend}")
                print(f" -> Active Feature Matrix: [Kanban Decoupling=True, REST-v1=Active]")
            else:
                # Alternate fallback route check
                alt_res = client.get(f"{base_root}/version")
                if alt_res.status_code == 200:
                    print(f" -> Vikunja Core Engine Version: \033[92m{alt_res.text.strip()}\033[0m")
                else:
                    print(f" -> Telemetry Alert: Server responded with status code {response.status_code}")
    except Exception as telemetry_err:
        print(f" -> Connection Warning: Telemetry engine could not query API versions: {telemetry_err}")
    print("=" * 70 + "\n")


def resolve_project_ids() -> list:
    """Discovers project IDs matching the targeted list names, auto-creating any that are missing."""
    resolved_ids = []
    try:
        with httpx.Client(timeout=10.0) as client:
            # 1. Fetch current projects
            response = client.get(f"{VIKUNJA_API_URL}/projects", headers=headers)
            existing_projects = {}
            if response.status_code == 200:
                for proj in response.json() or []:
                    existing_projects[proj.get("title", "").strip().lower()] = proj.get("id")

            # 2. Iterate through expected target names
            for target in TARGET_PROJECT_NAMES:
                tgt_lower = target.lower()
                if tgt_lower in existing_projects:
                    print(f"[CrewAI Daemon] Found target project '{target}' (ID: {existing_projects[tgt_lower]})")
                    resolved_ids.append(existing_projects[tgt_lower])
                else:
                    # Provision missing target project space dynamically
                    print(f"[Project Setup] Provisioning missing required workspace: '{target}'")
                    payload = {"title": target}
                    create_res = client.put(f"{VIKUNJA_API_URL}/projects", headers=headers, json=payload)
                    if create_res.status_code in [200, 201]:
                        new_id = create_res.json().get("id")
                        print(f"[Project Setup] -> Success! Created '{target}' (ID: {new_id})")
                        resolved_ids.append(new_id)
                    else:
                        print(f"[Project Setup] -> Critical Error creating tracking list '{target}': {create_res.text}")
    except Exception as e:
        print(f"[Project Setup] Critical workspace auto-discovery error: {e}")

    return resolved_ids


def get_kanban_bucket_map(project_id: int) -> tuple:
    """Looks up the manual Kanban View for the project, returning (view_id, bucket_map)."""
    bucket_map = {}
    kanban_view_id = None
    try:
        with httpx.Client(timeout=10.0) as client:
            # 1. Fetch the project views to locate the Kanban view
            views_res = client.get(f"{VIKUNJA_API_URL}/projects/{project_id}/views", headers=headers)
            if views_res.status_code != 200:
                return None, bucket_map

            for view in views_res.json() or []:
                if view.get("view_kind") == "kanban":
                    kanban_view_id = view.get("id")
                    break

            if not kanban_view_id:
                return None, bucket_map

            # 2. Fetch the operational buckets bound to that specific Kanban View
            buckets_res = client.get(f"{VIKUNJA_API_URL}/projects/{project_id}/views/{kanban_view_id}/buckets",
                                     headers=headers)
            if buckets_res.status_code == 200:
                for bucket in buckets_res.json() or []:
                    title_clean = bucket.get("title", "").strip().lower()
                    bucket_map[title_clean] = bucket.get("id")
    except Exception as e:
        print(f"[Bucket Linker Warning] Failed to dynamically trace project buckets: {e}")
    return kanban_view_id, bucket_map


def move_task_bucket(project_id: int, view_id: int, task_id: int, bucket_id: int):
    """Bypasses the legacy task fields and assigns the task to the correct
    Kanban view column directly.
    """
    if not (project_id and view_id and bucket_id):
        return

    # Modern View-Scoped Kanban Router Route
    view_bucket_url = f"{VIKUNJA_API_URL}/projects/{project_id}/views/{view_id}/buckets/tasks"

    # Try the standard relation format first
    payload = {
        "task_id": int(task_id),
        "bucket_id": int(bucket_id)
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(view_bucket_url, headers=headers, json=payload)

            # If the endpoint wants bucket_id in the URL path instead of payload:
            if response.status_code == 400:
                alt_url = f"{VIKUNJA_API_URL}/projects/{project_id}/views/{view_id}/buckets/{bucket_id}/tasks"
                response = client.post(alt_url, headers=headers, json={"task_id": int(task_id)})

            print(f"[State Machine API] Kanban View Position Status: {response.status_code}")

    except Exception as e:
        print(f"[State Update Error] Kanban routing exception: {e}")


def fetch_next_kanban_task(project_ids: list) -> dict:
    """Queries for an open task belonging to the monitored target group that does not already have an execution comment."""
    try:
        with httpx.Client(timeout=10.0) as client:
            for p_id in project_ids:
                url = f"{VIKUNJA_API_URL}/projects/{p_id}/tasks?filter=done = false"
                response = client.get(url, headers=headers)
                if response.status_code == 200:
                    tasks = response.json() or []
                    for t in tasks:
                        t_id = t.get("id")

                        # Verify whether an execution result comment already exists on this item
                        comments_res = client.get(f"{VIKUNJA_API_URL}/tasks/{t_id}/comments", headers=headers)
                        has_result = False
                        if comments_res.status_code == 200:
                            for c in comments_res.json() or []:
                                if "### [Agent Execution Result]" in c.get("comment", ""):
                                    has_result = True
                                    break

                        if not has_result:
                            return t
    except Exception as e:
        print(f"[Polling Warning] Connectivity delay scanning queues: {e}")
    return None


def convert_markdown_to_vikunja_html(markdown_text: str) -> str:
    """Converts markdown to standard HTML matching CommonMark conventions
    and line-break treatments used by the frontend rich-text Tiptap editor.
    """
    md = MarkdownIt("commonmark", {"html": True, "breaks": True})
    md.use(tasklists_plugin)
    return md.render(markdown_text).strip()


def post_resolution_to_vikunja(task_id: int, agent_output: str, task_description: str = ""):
    """Persists the agent result to task comments by pre-rendering Markdown to HTML for Vikunja compatibility."""
    task_url = f"{VIKUNJA_API_URL}/tasks/{task_id}"

    # Payload to resolve the task state itself
    payload = {
        "done": True,
        "description": task_description
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            # Safely grab raw text if it's a CrewAI object, otherwise cast to string
            if hasattr(agent_output, "raw"):
                raw_text = agent_output.raw
            else:
                raw_text = str(agent_output)

            # Clean up trailing spaces/newlines safely
            clean_output = raw_text.strip()

            # 1. Build the distinct Markdown stream
            comment_markdown = f"### [Agent Execution Result]\n\n{clean_output}"

            # 2. Translate Markdown to native Tiptap-aligned HTML structure
            comment_body = convert_markdown_to_vikunja_html(comment_markdown)

            # use PUT to create a new comment entry resource
            comment_url = f"{VIKUNJA_API_URL}/tasks/{task_id}/comments"
            comment_res = client.put(comment_url, headers=headers, json={"comment": comment_body})

            if comment_res.status_code not in [200, 201]:
                print(f"[API Error] Failed to post comment payload: {comment_res.text}", flush=True)
                return

            # Best Practice Addition: Attach text if it exceeds 8KB (keep attachment as raw Markdown)
            if len(clean_output) > 8000:
                print(f"[CrewAI Daemon] Solution payload is large ({len(clean_output)} chars). Saving attachment...", flush=True)
                files = {"files": (f"solution_task_{task_id}.md", clean_output.encode("utf-8"), "text/markdown")}
                attach_headers = {"Authorization": f"Bearer {VIKUNJA_BEARER_TOKEN}"}
                client.put(f"{VIKUNJA_API_URL}/tasks/{task_id}/attachments", headers=attach_headers, files=files)

            # Mark the `done` status of the task itself
            res = client.post(task_url, headers=headers, json=payload)
            if res.status_code == 200:
                print(f"[CrewAI Daemon] Successfully saved final results to comments stream and marked Task #{task_id} complete! 🎉", flush=True)
            else:
                print(f"[CrewAI Daemon Error] Failed closing out task resolution state: {res.text}", flush=True)

    except Exception as e:
        print(f"[Execution Storage Crash] Exception saving context properties: {e}", flush=True)


def execute_crewai_workflow(task_title: str, task_description: str) -> str:
    """Drives the local vLLM pipeline using CrewAI's native standard LLM adapter config wrapper class."""

    # Native CrewAI LLM implementation wrapper to prevent ModuleNotFoundErrors inside containers
    local_llm_service = LLM(
        model=f"hosted_vllm/{LOCAL_LLM_MODEL}",
        base_url=LOCAL_LLM_BASE_URL,
        api_key=LOCAL_LLM_API_KEY,
        temperature=0.2
    )

    analyst_agent = Agent(
        role="Senior Lead Systems Automation Architect",
        goal="Provide pristine architectural recommendations and deployment actions.",
        backstory="An automated expert software daemon operating inside local computing infrastructure clusters.",
        verbose=True,
        allow_delegation=False,
        llm=local_llm_service
    )

    execution_task = Task(
        description=f"Process this work item:\nTitle: {task_title}\nContext: {task_description}",
        expected_output="A definitive step-by-step resolution strategy or operational log output.",
        agent=analyst_agent
    )

    crew = Crew(
        agents=[analyst_agent],
        tasks=[execution_task],
        process=Process.sequential
    )

    return crew.kickoff()


# --- Main Runtime Daemon Loop ---
if __name__ == "__main__":
    # 1. Run environment inspection telemetry banner
    display_api_telemetry_banner()

    print("[CrewAI Daemon] Dynamic multi-workspace initialization sequence started...")

    # Establish dynamic runtime target cache mapping
    active_project_ids = resolve_project_ids()

    # Simple sanity safety guard check
    if not active_project_ids:
        print("[CrewAI Daemon Warning] No target projects successfully mapped or created. Retrying setup in 30s...")
        time.sleep(30)
        os._exit(1)

    print("[CrewAI Daemon] Worker group successfully online. Entering continuous polling sequence...")
    while True:
        target_task = fetch_next_kanban_task(active_project_ids)

        if target_task:
            t_id = target_task["id"]
            t_title = target_task["title"]
            t_desc = target_task.get("description", "")
            p_id = target_task.get("project_id")

            print(f"\n[CrewAI Daemon] Claiming Task #{t_id}: '{t_title}' (Project: #{p_id})")

            # Unpack both view_id and bucket mappings
            view_id, buckets = get_kanban_bucket_map(p_id)
            todo_bucket_id = buckets.get("to-do") or buckets.get("todo")
            doing_bucket_id = buckets.get("doing") or buckets.get("in progress") or buckets.get("in-progress")

            # Initialize pipeline execution wrapper with safety boundaries
            is_successfully_completed = False
            try:
                # Progress State: Move task instantly into 'Doing'
                if doing_bucket_id:
                    print(f"[State Machine] Moving Task #{t_id} to 'Doing' bucket...")
                    move_task_bucket(p_id, view_id, t_id, doing_bucket_id)

                # Process text compilation against local inference endpoints
                result = execute_crewai_workflow(t_title, t_desc)

                # Persist responses to comments and resolve task context
                post_resolution_to_vikunja(t_id, result, task_description=t_desc)
                is_successfully_completed = True

            except Exception as loop_error:
                print(f"\n[CRITICAL RUNTIME ERROR] Worker crashed during execution turn: {loop_error}")

            finally:
                # CRASH HANDLER/ROLLBACK: If processing broke or the engine caught a SIGTERM termination signature,
                # shift the task cleanly back out into 'To-Do' so it can safely retry on container revival.
                if not is_successfully_completed:
                    if todo_bucket_id:
                        print(f"[State Rollback] Reverting task #{t_id} position back into 'To-Do' bucket...")
                        move_task_bucket(p_id, view_id, t_id, todo_bucket_id)
                    else:
                        print(
                            f"[State Rollback Warning] Cannot reset task #{t_id} position; no matching 'To-Do' bucket was mapped.")

        time.sleep(10)
