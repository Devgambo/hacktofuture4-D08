import json
import logging
from typing_extensions import TypedDict
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage

from .graph import get_reasoning_llm, _extract_json, _to_str
from cd_providers import get_cd_adapter, CDFailureContext
from .prompts import CD_DIAGNOSIS_SYSTEM_PROMPT, CD_DIAGNOSIS_PROMPT

logger = logging.getLogger("devops_agent.cd_diagnosis")

class CDDiagnosisState(TypedDict):
    failure_context: dict       # Represents CDFailureContext dict
    diagnosis: dict             # LLM-generated report
    alert_sent: bool
    status: str
    error: str

async def parse_failure(state: CDDiagnosisState) -> dict:
    """Normalize and validate the webhook payload into CDFailureContext format"""
    logger.info("Parsing CD failure context ...")
    return {"status": "parsed"}

async def enrich_context(state: CDDiagnosisState) -> dict:
    """Use the selected cloud adapter to enrich the failure context"""
    failure_dict = state.get("failure_context", {})
    provider_name = failure_dict.get("provider", "custom")
    logger.info(f"Enriching CD context with provider: {provider_name}")
    
    ctx = CDFailureContext(
        job_id=failure_dict.get("job_id", ""),
        repo=failure_dict.get("repo", "unknown/repo"),
        service=failure_dict.get("service", "unknown"),
        environment=failure_dict.get("environment", "unknown"),
        status=failure_dict.get("status", "failed"),
        error_message=failure_dict.get("error_message", "Unknown error"),
        provider=provider_name,
        deployment_id=failure_dict.get("deployment_id", ""),
        timestamp=failure_dict.get("timestamp", ""),
        commit_sha=failure_dict.get("commit_sha", ""),
        branch=failure_dict.get("branch", ""),
        error_logs=failure_dict.get("error_logs", ""),
        resource_info=failure_dict.get("resource_info", {}),
        provider_config=failure_dict.get("provider_config", {}),
        enriched_logs="",
        enriched_metrics={},
        enriched_events=[],
    )
    
    adapter = get_cd_adapter(provider_name)
    enriched_ctx = await adapter.enrich(ctx)
    
    # Store enriched data back into state dict
    return {"failure_context": enriched_ctx.__dict__, "status": "enriched"}

async def generate_diagnosis(state: CDDiagnosisState) -> dict:
    """Generate structured root cause analysis via LLM"""
    logger.info("Generating CD diagnosis via LLM ...")
    llm = get_reasoning_llm()
    ctx = state.get("failure_context", {})
    
    try:
        response = await llm.ainvoke([
            SystemMessage(content=CD_DIAGNOSIS_SYSTEM_PROMPT),
            HumanMessage(content=CD_DIAGNOSIS_PROMPT.format(
                repo=ctx.get("repo", ""),
                service=ctx.get("service", ""),
                environment=ctx.get("environment", ""),
                error_message=ctx.get("error_message", ""),
                error_logs=ctx.get("error_logs", "") + "\n" + ctx.get("enriched_logs", ""),
                enriched_metrics=json.dumps(ctx.get("enriched_metrics", {})),
                enriched_events=json.dumps(ctx.get("enriched_events", [])),
            )),
        ])

        raw = _extract_json(_to_str(response.content))
        try:
            diagnosis = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[cd_diagnosis] JSON parse failed — using fallback")
            diagnosis = {
                "root_cause": "Failed to parse analysis.",
                "severity": "high",
                "affected_components": [ctx.get("service", "unknown")],
                "immediate_actions": [],
                "recommended_fix": "Review raw logs.",
                "prevent_recurrence": "",
                "resource_analysis": None
            }
            
        logger.info(f"[cd_diagnosis] Generated severity: {diagnosis.get('severity')}")
        return {"diagnosis": diagnosis, "status": "diagnosis_generated"}

    except Exception as exc:
        logger.exception("[cd_diagnosis] LLM call failed")
        return {"error": str(exc), "status": "diagnosis_failed"}

async def send_alert(state: CDDiagnosisState) -> dict:
    """Mark as ready for alerting (actual alert is handled in main.py)"""
    logger.info("CD Diagnosis complete, ready for alerting.")
    return {"status": "alert_ready"}


def build_cd_graph() -> StateGraph:
    graph = StateGraph(CDDiagnosisState)

    graph.add_node("parse_failure",      parse_failure)
    graph.add_node("enrich_context",     enrich_context)
    graph.add_node("generate_diagnosis", generate_diagnosis)
    graph.add_node("send_alert",         send_alert)

    graph.set_entry_point("parse_failure")

    graph.add_edge("parse_failure",      "enrich_context")
    graph.add_edge("enrich_context",     "generate_diagnosis")
    graph.add_edge("generate_diagnosis", "send_alert")
    graph.add_edge("send_alert",         END)

    return graph

cd_agent_graph = build_cd_graph().compile()

async def run_cd_diagnosis(payload: dict) -> dict:
    initial_state: CDDiagnosisState = {
        "failure_context": payload,
        "diagnosis": {},
        "alert_sent": False,
        "status": "starting",
        "error": ""
    }
    
    final_state: dict = {}
    async for step in cd_agent_graph.astream(initial_state):
        node_name = list(step.keys())[0]
        node_output = step[node_name]
        logger.info("── cd step: %-22s  status=%s", node_name, node_output.get("status", ""))
        final_state = {**final_state, **node_output}

    return final_state
