#!/usr/bin/env python3
"""
langgraph_router/main.py

Stateful Supervisor Gateway with enhanced logging and performance tuning.
"""

import time
import logging
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.security import APIKeyHeader
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from typing import TypedDict, Annotated, Literal
import os
import uvicorn

# ========================= LOGGING SETUP =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("langgraph_router")
logger.setLevel(logging.INFO)


# --- Define Stateful Schema ---
class SupervisorState(TypedDict):
    task_id: int
    project_id: int
    title: str
    description: str
    complexity: Literal["low", "medium", "high"]
    routing_target: Literal["fast_path", "crewai_heavy", "blocked"]
    blueprint: str
    rejection_reason: str
    start_time: float = 0.0


# --- Output Schemas for LLM Structured Outputs ---
class TaskAnalysis(BaseModel):
    complexity: Literal["low", "medium", "high"] = Field(
        description="Assessment of task scope and execution dependencies."
    )
    routing_target: Literal["fast_path", "crewai_heavy", "blocked"] = Field(
        description="Determines execution pathway. 'fast_path' for simple text/docs, 'crewai_heavy' for code changes/testing."
    )
    analysis_reasoning: str = Field(
        description="Justification for chosen complexity and routing path."
    )


class ExecutionBlueprint(BaseModel):
    blueprint_markdown: str = Field(
        description="Strict step-by-step markdown plan targeting ONLY the files mentioned."
    )


# --- Configuration & LLM Binding ---
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://localhost:8000/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "nemoclaw")
API_KEY = os.getenv("LOCAL_LLM_API_KEY", "mock-key")

shared_llm = ChatOpenAI(
    model=LOCAL_LLM_MODEL,
    base_url=LOCAL_LLM_BASE_URL,
    api_key=API_KEY,
    temperature=0.0,      # More deterministic
    max_tokens=1024,
)


# --- Graph Nodes with Timing ---
def analyze_task_node(state: SupervisorState) -> dict:
    """Classifies task complexity and routes to the appropriate pipeline."""
    start = time.time()
    logger.info(f"[Analyze] Starting analysis for Task {state.get('task_id')}")

    analyzer_llm = shared_llm.with_structured_output(TaskAnalysis)

    prompt = f"""Quick analysis only:
Title: {state["title"]}
Description: {state["description"]}

Classify:
- "fast_path" = pure docs/text
- "crewai_heavy" = code, tests, Ansible changes
- "blocked" = missing context"""

    try:
        analysis = analyzer_llm.invoke(prompt)
        result = {
            "complexity": analysis.complexity,
            "routing_target": analysis.routing_target,
        }
    except Exception as e:
        logger.warning(f"[Analyze] LLM failed: {e}")
        result = {"complexity": "medium", "routing_target": "crewai_heavy"}

    duration = time.time() - start
    logger.info(f"[Analyze] Completed in {duration:.2f}s → {result['routing_target']}")
    return result


def generate_blueprint_node(state: SupervisorState) -> dict:
    """Generates a structured execution blueprint for the targeted files."""
    start = time.time()
    logger.info(f"[Blueprint] Generating for Task {state.get('task_id')}")

    blueprint_llm = shared_llm.with_structured_output(ExecutionBlueprint)

    prompt = f"""Create concise execution plan:
Title: {state["title"]}
Description: {state["description"]}

Output ONLY clear Markdown steps. Be brief."""

    try:
        bp = blueprint_llm.invoke(prompt)
        result = {"blueprint": bp.blueprint_markdown}
    except Exception as e:
        logger.warning(f"[Blueprint] LLM failed: {e}")
        result = {"blueprint": "Proceed with standard CrewAI implementation."}

    duration = time.time() - start
    logger.info(f"[Blueprint] Completed in {duration:.2f}s")
    return result


def finalize_fast_path_node(state: SupervisorState) -> dict:
    """Handles fast-path routing by drafting direct solutions immediately."""
    logger.info(f"[FastPath] Finalizing Task {state.get('task_id')}")
    return {
        "blueprint": f"### FAST-PATH\n{state.get('blueprint', '')}\nNo heavy agents needed."
    }


# --- Conditional Edges ---
def route_after_analysis(
    state: SupervisorState,
) -> Literal["generate_blueprint_node", "__end__"]:
    if state["routing_target"] == "blocked":
        return "__end__"
    return "generate_blueprint_node"


def route_after_blueprint(
    state: SupervisorState,
) -> Literal["finalize_fast_path_node", "__end__"]:
    if state["routing_target"] == "fast_path":
        return "finalize_fast_path_node"
    return "__end__"


# --- Build Graph ---
workflow = StateGraph(SupervisorState)

workflow.add_node("analyze_task_node", analyze_task_node)
workflow.add_node("generate_blueprint_node", generate_blueprint_node)
workflow.add_node("finalize_fast_path_node", finalize_fast_path_node)

workflow.add_edge(START, "analyze_task_node")
workflow.add_conditional_edges("analyze_task_node", route_after_analysis)
workflow.add_conditional_edges("generate_blueprint_node", route_after_blueprint)
workflow.add_edge("finalize_fast_path_node", END)

app_graph = workflow.compile()

# --- FastAPI Router Deployment ---
app = FastAPI(title="LangGraph Supervisor Router")
api_key_header = APIKeyHeader(name="X-Agent-Secret", auto_error=True)
ROUTER_API_KEY = os.getenv("LANGGRAPH_API_KEY", "secure-secret")


def verify_token(x_agent_secret: str = Header(None)):
    if not x_agent_secret or x_agent_secret != ROUTER_API_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")


@app.post("/v1/orchestrate")
async def orchestrate_task(payload: dict, _=Depends(verify_token)):
    start_total = time.time()
    logger.info(f"[Orchestrate] Received Task {payload.get('task_id')}")

    initial_state: SupervisorState = {
        "task_id": payload.get("task_id"),
        "project_id": payload.get("project_id"),
        "title": payload.get("title", ""),
        "description": payload.get("description", ""),
        "complexity": "low",
        "routing_target": "crewai_heavy",
        "blueprint": "",
        "rejection_reason": "",
        "start_time": start_total,
    }

    try:
        result = await app_graph.ainvoke(initial_state)
        duration = time.time() - start_total
        logger.info(f"[Orchestrate] Completed in {duration:.2f}s → {result.get('routing_target')}")

        return {
            "routing": result.get("routing_target", "crewai_heavy"),
            "complexity": result.get("complexity"),
            "blueprint": result.get("blueprint", ""),
            "summary": f"Processed in {duration:.1f}s",
        }
    except Exception as e:
        logger.error(f"[Orchestrate] Failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
