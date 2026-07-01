import os
import time
import sys
import httpx
import urllib3


def load_env_file():
    """Finds and loads environment variables from test_agent_pipeline.env if it exists."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(script_dir, "test_agent_pipeline.env")

    if os.path.exists(env_path):
        print(f"[Env Loader] Found configuration file at: {env_path}")
        with open(env_path, "r") as f:
            for line in f:
                # Clean up whitespace and skip comments or empty lines
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Split at the first '=' to handle values containing '=' characters safely
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Set the environment variable if not already set externally
                    if key and not os.getenv(key):
                        os.environ[key] = value


# --- Execute Environment Bootstrapping ---
load_env_file()

# --- Test Environment Configuration ---
VIKUNJA_API_URL = os.getenv("VIKUNJA_API_URL", "https://kanban.admin.johnson.int/api/v1")
VIKUNJA_BEARER_TOKEN = os.getenv("VIKUNJA_BEARER_TOKEN")
TEST_PROJECT_NAME = os.getenv("VIKUNJA_TEST_PROJECT_NAME", "crewai-test")
SSL_CERT_FILE = os.getenv("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
SSL_VERIFY = os.getenv("SSL_VERIFY", False)

if not os.path.exists(SSL_CERT_FILE):
    SSL_VERIFY = False

if not VIKUNJA_BEARER_TOKEN:
    print(
        "[Test Error] Missing VIKUNJA_BEARER_TOKEN. Define it in your shell or test_agent_pipeline.env.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {VIKUNJA_BEARER_TOKEN}",
    "Content-Type": "application/json"
}

# The benchmark description payload injected to verify zero regression drops during worker execution
EXPECTED_DESCRIPTION = (
    "Review our current dynamic infrastructure. Formulate a quick python log-rotation script "
    "template that outputs to standard json format for vector ingestion. Target host: gpu01."
)


def resolve_test_project() -> int:
    """Finds the ID of the testing project workspace."""
    print(f"\n[0/3] Checking for existence of project workspace '{TEST_PROJECT_NAME}'...")
    try:
        with httpx.Client(timeout=10.0, verify=SSL_VERIFY) as client:
            res = client.get(f"{VIKUNJA_API_URL}/projects", headers=HEADERS)
            if res.status_code != 200:
                print(f"[CRITICAL] Project retrieval failed with status {res.status_code}: {res.text}")
                sys.exit(1)

            for project in res.json() or []:
                if project.get("title") == TEST_PROJECT_NAME:
                    p_id = project.get("id")
                    print(f" -> Found workspace. Target project ID: {p_id}")
                    return p_id

            print(f"[CRITICAL] Could not locate project named '{TEST_PROJECT_NAME}' inside Vikunja database.")
            sys.exit(1)
    except Exception as e:
        print(f"[CRITICAL] Exception reached while connecting to Vikunja: {e}")
        sys.exit(1)


def inject_test_task(project_id: int) -> int:
    """Injects a standard structured automation testing item with a concrete description."""
    print(f"\n[1/3] Injecting validation task directly into Dynamic Project #{project_id}...")
    task_payload = {
        "title": "[Integration Test] Optimize Cluster Traefik Logs Routing",
        "description": EXPECTED_DESCRIPTION
    }

    try:
        with httpx.Client(timeout=10.0, verify=SSL_VERIFY) as client:
            res = client.put(f"{VIKUNJA_API_URL}/projects/{project_id}/tasks", headers=HEADERS, json=task_payload)
            if res.status_code != 201 and res.status_code != 200:
                print(f"[CRITICAL] Task creation failed status {res.status_code}: {res.text}")
                sys.exit(1)

            task_id = res.json().get("id")
            print(f" -> Success! Created Test Task #{task_id}: '{task_payload['title']}'")
            return task_id
    except Exception as e:
        print(f"[CRITICAL] Exception caught during item injection: {e}")
        sys.exit(1)


def monitor_agent_execution(task_id: int, max_retries: int = 12, delay: int = 15) -> bool:
    """Monitors workflow progress while actively enforcing description invariance rules."""
    print(f"\n[2/3] Monitoring pipeline execution for Task #{task_id} Activity stream...")
    print(f"      Will poll every {delay}s up to {max_retries} times (Total timeout: {max_retries * delay}s).")

    # Switched to monitor the Comments activity route per Kanban architectural best practices
    task_url = f"{VIKUNJA_API_URL}/tasks/{task_id}"
    comments_url = f"{VIKUNJA_API_URL}/tasks/{task_id}/comments"

    for attempt in range(1, max_retries + 1):
        time.sleep(delay)
        try:
            with httpx.Client(timeout=10.0, verify=SSL_VERIFY) as client:
                task_res = client.get(task_url, headers=HEADERS)
                if task_res.status_code == 200:
                    task_data = task_res.json()
                    is_done = task_data.get("done", False)
                    current_description = task_data.get("description", "")

                    # --- CRITICAL REGRESSION GUARD CHECK ---
                    if not current_description:
                        print(
                            f"\n[❌ REGRESSION DETECTED] Task #{task_id} description was WIPED OUT (empty) on check #{attempt}!")
                        sys.exit(1)
                    elif current_description.strip() != EXPECTED_DESCRIPTION.strip():
                        print(f"\n[❌ REGRESSION DETECTED] Task description altered unexpectedly!")
                        print(f"Expected: {EXPECTED_DESCRIPTION}")
                        print(f"Found:    {current_description}")
                        sys.exit(1)

                    print(f" -> Check #{attempt}: Done Status = {is_done} (Description Intact ✅)")

                    # Check for resolution comment completion signatures
                    c_res = client.get(comments_url, headers=HEADERS)
                    if c_res.status_code == 200:
                        for c_obj in c_res.json() or []:
                            comment_text = c_obj.get("comment", "")

                            if "### [Agent Execution Result]" in comment_text or is_done:
                                print(f"\n[3/3] TARGET MET! Agent appended the activity resolution comment.")
                                print("=" * 60)

                                raw_result = comment_text.split("### [Agent Execution Result]")[-1].strip()
                                print(raw_result[:1500])
                                print("=" * 60)
                                return True
        except SystemExit:
            sys.exit(1)
        except Exception as e:
            print(f" -> Connection warning on attempt #{attempt}: {e}")

    return False


if __name__ == "__main__":
    start_time = time.time()

    # Disable annoying self-signed certificate warnings in isolated cluster environment logs
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # Resolve project dynamically
    target_id = resolve_test_project()

    # Inject and run test
    created_id = inject_test_task(target_id)
    success = monitor_agent_execution(created_id)

    # 3. Assert Success / Failure
    elapsed = round(time.time() - start_time, 2)
    if success:
        print(f"\n[TEST PASSED] Dynamic pipeline verified successfully in {elapsed}s! 🎉\n")
        sys.exit(0)
    else:
        print(f"\n[TEST FAILED] Pipeline timed out after {elapsed}s. Check container logs using:")
        print("    docker-compose logs --tail=100 crewai-workers langgraph-router\n")
        sys.exit(1)
