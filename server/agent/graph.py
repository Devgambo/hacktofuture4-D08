"""
LangGraph agent for autonomous CI failure investigation and fixing.

Graph:  parse_event → rsi_context_build → safety_precheck → memory_recall
                    → fetch_files → generate_fix → post_fix_safety_check
                    → [open_pr | END]

Models:
  generate_fix → GPT-4o              (coding_model_id)
  get_reasoning_llm exported for review_graph.py
"""

import difflib
import json
import logging
import re
from typing import Callable

import httpx

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from agent.prompts import SYSTEM_PROMPT, FIX_GENERATION_PROMPT, MEMORY_CONTEXT_SECTION
from config import get_settings
from rsi import db as rsi_db

logger = logging.getLogger("devops_agent.graph")

# Cap on how many files we'll fetch content for and pass to the LLM
MAX_FILES_TO_INVESTIGATE = 8


# ─────────────────────────────────────────────────────────
# LLM factories
# ─────────────────────────────────────────────────────────

def _openai_client(model_id: str, temperature: float, max_tokens: int) -> ChatOpenAI:
    settings = get_settings()
    return ChatOpenAI(
        model=model_id,
        api_key=settings.openai_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def get_coding_llm() -> ChatOpenAI:
    """GPT-4o — CI fix generation."""
    return _openai_client(get_settings().coding_model_id, temperature=0.2, max_tokens=4096)


def get_reasoning_llm() -> ChatOpenAI:
    """GPT-4o-mini — PR review. Exported for review_graph.py."""
    return _openai_client(get_settings().reasoning_model_id, temperature=0.6, max_tokens=8192)


def get_fast_llm() -> ChatOpenAI:
    """GPT-4o-mini — cheap/fast auxiliary tasks."""
    return _openai_client(get_settings().fast_model_id, temperature=0.1, max_tokens=1024)


# ─────────────────────────────────────────────────────────
# JSON extraction helpers
# ─────────────────────────────────────────────────────────

def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(raw: str) -> str:
    """Pull the first JSON object from an LLM response.

    Tries in order:
    1. ```json ... ``` fenced block
    2. ``` ... ``` fenced block
    3. Brace-matching walk — correctly skips braces inside quoted strings
       and escape sequences (handles embedded YAML / multiline values).
    4. Return text as-is and let the caller raise JSONDecodeError.
    """
    clean = _strip_think_tags(raw)
    if "```json" in clean:
        return clean.split("```json")[1].split("```")[0].strip()
    if "```" in clean:
        return clean.split("```")[1].split("```")[0].strip()

    start = clean.find("{")
    if start == -1:
        return clean.strip()

    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(clean[start:], start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return clean[start : i + 1].strip()

    return clean.strip()


def _to_str(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block if isinstance(block, str) else block.get("text", "")
            for block in content
        )
    return str(content)


# ─────────────────────────────────────────────────────────
# GitHub API helpers
# ─────────────────────────────────────────────────────────

_GH_API      = "https://api.github.com"
_GH_LOG_TAIL = 4_000   # chars to keep from each job log (errors appear at the tail)
_GH_MAX_JOBS = 2       # max failed jobs to fetch logs for


def _gh_headers(token: str) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _fetch_ci_logs(owner: str, repo: str, run_id: int, token: str) -> str:
    """Fetch real CI job output from GitHub Actions API.

    1. GET .../actions/runs/{run_id}/jobs  → find failed jobs
    2. GET .../actions/jobs/{job_id}/logs  → download log text
       (GitHub redirects to a signed URL — follow_redirects handles it)

    Strips the 29-char timestamp prefix GitHub prepends to every log line.
    Keeps the last 4 000 chars per job (errors always appear at the end).
    Returns "" on any failure — non-fatal.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            jobs_resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/actions/runs/{run_id}/jobs",
                headers=_gh_headers(token),
            )
            if jobs_resp.status_code != 200:
                logger.warning("[ci_logs] jobs list HTTP %d for run %d",
                               jobs_resp.status_code, run_id)
                return ""

            failed_jobs = [
                j for j in jobs_resp.json().get("jobs", [])
                if j.get("conclusion") in ("failure", "cancelled")
            ]
            if not failed_jobs:
                logger.info("[ci_logs] no failed jobs found for run %d", run_id)
                return ""

            logger.info("[ci_logs] %d failed job(s) in run %d: %s",
                        len(failed_jobs), run_id,
                        [j["name"] for j in failed_jobs[:_GH_MAX_JOBS]])

            parts: list[str] = []
            for job in failed_jobs[:_GH_MAX_JOBS]:
                log_resp = await client.get(
                    f"{_GH_API}/repos/{owner}/{repo}/actions/jobs/{job['id']}/logs",
                    headers=_gh_headers(token),
                )
                if log_resp.status_code != 200:
                    logger.warning("[ci_logs] logs HTTP %d for job %d",
                                   log_resp.status_code, job["id"])
                    continue

                lines = []
                for line in log_resp.text.splitlines():
                    # Strip "2024-01-01T00:00:00.0000000Z " prefix (29 chars)
                    if len(line) > 29 and line[4] == "-" and line[7] == "-":
                        line = line[29:]
                    lines.append(line)

                log_text = "\n".join(lines)
                if len(log_text) > _GH_LOG_TAIL:
                    log_text = "...[truncated]...\n" + log_text[-_GH_LOG_TAIL:]

                parts.append(f"=== Job: {job['name']} ===\n{log_text}")

            return "\n\n".join(parts)

    except Exception as exc:
        logger.warning("[ci_logs] fetch failed (non-fatal): %s", exc)
        return ""


async def _fetch_changed_files(
    owner: str,
    repo: str,
    branch: str,
    default_branch: str,
    head_sha: str,
    token: str,
) -> tuple[list[str], str]:
    """Return (changed_file_paths, combined_patch_diff) for the branch.

    Strategy:
    - branch != default_branch → compare API: {default}...{branch}
    - branch == default_branch → commit API: {head_sha}  (push to main)

    Returns ([], "") on any failure.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            if branch != default_branch:
                url = f"{_GH_API}/repos/{owner}/{repo}/compare/{default_branch}...{branch}"
            else:
                if not head_sha:
                    logger.warning("[changed_files] no head_sha for default branch push")
                    return [], ""
                url = f"{_GH_API}/repos/{owner}/{repo}/commits/{head_sha}"

            resp = await client.get(url, headers=_gh_headers(token))
            if resp.status_code != 200:
                logger.warning("[changed_files] GitHub API HTTP %d for %s", resp.status_code, url)
                return [], ""

            files = resp.json().get("files", [])
            changed = [f["filename"] for f in files if f.get("status") != "removed"]
            patch_parts = [
                f"--- {f['filename']}\n{f['patch']}"
                for f in files if f.get("patch")
            ]
            return changed, "\n\n".join(patch_parts)

    except Exception as exc:
        logger.warning("[changed_files] fetch failed: %s", exc)
        return [], ""


# ─────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────

class AgentState(TypedDict):
    github_event: dict
    error_logs: str                   # CI failure output (metadata + real job logs)
    repo_name: str                    # "owner/repo"
    branch: str                       # branch where CI failed
    github_token: str
    changed_files: list[str]          # files that actually changed on the branch
    files_to_investigate: list[str]   # changed files only (importers fetched on-demand)
    rsi_nav_map: dict                 # {file_path: {importers: [...], imports: [...]}}
    rsi_context: str                  # formatted RSI context (grows per context iteration)
    unsafe_files: list[str]           # files blocked by sensitivity check
    memory_context: str               # prior fix memories
    files_content: dict               # {path: content} fetched from GitHub (grows)
    pr_diff: str                      # raw patch from compare/commit API
    proposed_fix: dict                # LLM-generated fix (parsed JSON)
    final_pr_url: str
    status: str
    error: str
    retry_count: int
    context_iteration: int            # how many extra context rounds have run (max 3)
    need_more_context: bool           # set by request_context node
    requested_files: list[str]        # files LLM asked for in current iteration


# ─────────────────────────────────────────────────────────
# Graph nodes
# ─────────────────────────────────────────────────────────

async def parse_event(state: AgentState) -> dict:
    """Extract event fields and fetch real CI job logs from GitHub Actions."""
    payload      = state["github_event"]
    workflow_run = payload.get("workflow_run", {})
    repo         = payload.get("repository", {}).get("full_name", "")
    branch       = workflow_run.get("head_branch", "")

    logger.info("[parse_event] CI failure — repo=%s  branch=%s  workflow=%r",
                repo, branch, workflow_run.get("name", "unknown"))

    error_logs = (
        f"Workflow '{workflow_run.get('name', 'unknown')}' failed on branch '{branch}'.\n"
        f"Conclusion: {workflow_run.get('conclusion', 'unknown')}\n"
        f"Run URL: {workflow_run.get('html_url', '')}\n"
    )

    run_id = workflow_run.get("id")
    token  = state.get("github_token", "")

    if run_id and repo:
        owner, repo_name = repo.split("/", 1)
        ci_logs = await _fetch_ci_logs(owner, repo_name, int(run_id), token)
        if ci_logs:
            error_logs += f"\n--- CI Job Logs ---\n{ci_logs}\n"
            logger.info("[parse_event] CI logs fetched — %d chars total", len(ci_logs))
            # Show the actual error output so it's visible in server logs
            logger.info("[parse_event] CI log output:\n%s",
                        ci_logs if len(ci_logs) <= 800 else ci_logs[:800] + "\n...[truncated in log]")
        else:
            logger.warning("[parse_event] No CI logs fetched — LLM will work from metadata only")

    review_reasoning = workflow_run.get("_review_reasoning")
    if review_reasoning:
        error_logs += f"\n--- PR Review Quality Gate Failure ---\n{review_reasoning}\n"

    return {
        "repo_name":   repo,
        "branch":      branch,
        "error_logs":  error_logs,
        "status":      "parsed",
        "retry_count": 0,
    }


async def rsi_context_build(state: AgentState) -> dict:
    """Build the investigation context deterministically — no LLM.

    1. Fetch changed files via GitHub compare API (or commit API for pushes to main)
    2. Query RSI for each changed file:
       - file metadata  (role_tag, file_desc, language)
       - symbols        (what the file defines/exports)
       - direct imports (what the file depends on)
       - direct importers (which files break if this one changes)
       - sensitivity    (is it flagged as secrets/infra?)
    3. Build a structured rsi_context string for the fix-generation prompt
    4. files_to_investigate = changed_files + their direct importers (capped)
    5. Store pr_diff from compare patches so generate_fix has the raw diff
    """
    payload        = state["github_event"]
    workflow_run   = payload.get("workflow_run", {})
    repo           = state["repo_name"]
    branch         = state["branch"]
    default_branch = payload.get("repository", {}).get("default_branch", "main")
    head_sha       = workflow_run.get("head_sha", "")
    token          = state.get("github_token", "")
    owner, repo_name = repo.split("/", 1)

    # ── 1. Changed files + raw diff ─────────────────────────────────────
    changed_files, pr_diff = await _fetch_changed_files(
        owner, repo_name, branch, default_branch, head_sha, token
    )

    if changed_files:
        logger.info("[rsi] Changed files on '%s' (%d): %s",
                    branch, len(changed_files), changed_files)
    else:
        logger.warning("[rsi] Could not determine changed files for '%s' — context will be sparse",
                       branch)
        return {
            "changed_files":        [],
            "files_to_investigate": [],
            "rsi_context":          "No changed files detected from GitHub API.",
            "pr_diff":              "",
            "status":               "rsi_context_built",
            "retry_count":          0,
        }

    # ── 2. RSI queries ───────────────────────────────────────────────────
    logger.info("[rsi] Querying RSI for %d file(s)...", len(changed_files))

    metadata    = await rsi_db.get_file_metadata(repo, changed_files)
    symbols     = await rsi_db.get_file_symbols(repo, changed_files)
    imports     = await rsi_db.get_direct_imports(repo, changed_files)
    importers   = await rsi_db.get_importers(repo, changed_files)
    sensitivity = await rsi_db.check_sensitivity(repo, changed_files)

    in_index = len(metadata)
    logger.info("[rsi] RSI coverage: %d/%d changed files found in index",
                in_index, len(changed_files))
    if in_index < len(changed_files):
        missing = [f for f in changed_files if f not in metadata]
        logger.warning("[rsi] Not in RSI (repo may need re-indexing): %s", missing)

    # ── 3. Build rsi_context string + nav_map ───────────────────────────
    rsi_lines: list[str] = []
    rsi_nav_map: dict    = {}

    for fp in changed_files:
        meta     = metadata.get(fp, {})
        role     = meta.get("role_tag", "unknown — not in RSI")
        desc     = meta.get("file_desc", "")
        syms     = symbols.get(fp, [])
        deps     = imports.get(fp, [])
        imp_list = importers.get(fp, [])
        is_sens  = fp in sensitivity

        # Navigation map — importers/imports available for on-demand fetching
        rsi_nav_map[fp] = {"importers": imp_list, "imports": deps}

        header = f"### `{fp}`"
        if is_sens:
            reason = sensitivity[fp].get("sensitivity_reason", "sensitive")
            header += f"  ⚠️ SENSITIVE — {reason}"
        rsi_lines.append(header)
        rsi_lines.append(f"- Role: {role}")
        if desc:
            rsi_lines.append(f"- Description: {desc}")
        if syms:
            rsi_lines.append(f"- Symbols: {', '.join(syms[:10])}")
        if deps:
            rsi_lines.append(f"- Imports: {', '.join(deps[:5])}")
        if imp_list:
            rsi_lines.append(
                f"- Imported by {len(imp_list)} file(s): "
                + ", ".join(imp_list[:5])
                + (f" (+{len(imp_list) - 5} more)" if len(imp_list) > 5 else "")
            )
        rsi_lines.append("")

        logger.info("[rsi]  %-45s role=%-12s  symbols=%2d  importers=%2d  sensitive=%s",
                    fp, role, len(syms), len(imp_list), is_sens)
        if imp_list:
            logger.info("[rsi]    ↳ importers (available on-demand): %s", imp_list[:5])
        if deps:
            logger.info("[rsi]    ↳ imports: %s", deps[:5])

    rsi_context = "\n".join(rsi_lines) if rsi_lines else "No RSI data found for changed files."

    # ── 4. files_to_investigate = changed files only ─────────────────────
    # Importers and imports are listed in rsi_nav_map and fetched on-demand
    # by the request_context → fetch_requested_files loop.
    logger.info("[rsi] Initial investigation: %d changed file(s) — importers available on-demand",
                len(changed_files))

    return {
        "changed_files":        changed_files,
        "files_to_investigate": changed_files,
        "rsi_nav_map":          rsi_nav_map,
        "rsi_context":          rsi_context,
        "pr_diff":              pr_diff,
        "status":               "rsi_context_built",
        "retry_count":          0,
        "context_iteration":    0,
        "need_more_context":    False,
        "requested_files":      [],
    }


async def safety_precheck(state: AgentState) -> dict:
    """Remove sensitive files from the investigation set before fetching content."""
    files = state.get("files_to_investigate", [])
    if not files:
        return {"unsafe_files": [], "status": "safety_checked"}

    sensitive_info = await rsi_db.check_sensitivity(state["repo_name"], files)
    unsafe_files   = list(sensitive_info.keys())
    safe_files     = [f for f in files if f not in unsafe_files]

    if unsafe_files:
        logger.warning("[safety] Blocked %d sensitive file(s): %s",
                       len(unsafe_files),
                       {f: sensitive_info[f].get("sensitivity_reason", "") for f in unsafe_files})
    else:
        logger.info("[safety] All %d files cleared", len(files))

    return {
        "files_to_investigate": safe_files,
        "unsafe_files":         unsafe_files,
        "status":               "safety_checked",
    }


async def memory_recall(state: AgentState) -> dict:
    """Search agent memory for similar past fixes."""
    try:
        from memory.store import search_memory

        error_text = state.get("error_logs", "")
        if not error_text:
            return {"memory_context": "", "status": "memory_recall_skipped"}

        memories = await search_memory(error_text, top_k=3, threshold=0.60)
        if not memories:
            logger.info("[memory] No matching memories found")
            return {"memory_context": "", "status": "memory_recall_empty"}

        memory_strs = []
        for i, mem in enumerate(memories, 1):
            files_str = ", ".join(mem["files_changed"]) if mem["files_changed"] else "N/A"
            memory_strs.append(
                f"### Memory {i} (similarity: {mem['similarity']:.2f}, repo: {mem['repo_id']})\n"
                f"- **Error pattern:** {mem['error_signature']}\n"
                f"- **Root cause:** {mem['root_cause']}\n"
                f"- **Fix applied:** {mem['fix_summary']}\n"
                f"- **Files changed:** {files_str}\n"
                f"- **PR:** {mem['pr_url']}"
            )

        memory_context = MEMORY_CONTEXT_SECTION.format(memories="\n\n".join(memory_strs))
        logger.info("[memory] Injecting %d prior fix(es) — best similarity: %.3f",
                    len(memories), memories[0]["similarity"])
        return {"memory_context": memory_context, "status": "memory_recalled"}

    except Exception as e:
        logger.warning("[memory] Recall failed (non-fatal): %s", e)
        return {"memory_context": "", "status": "memory_recall_error"}


async def fetch_files(state: AgentState) -> dict:
    """Fetch raw file contents from GitHub API for the failing branch."""
    token = state.get("github_token", "")
    owner, repo_name = state["repo_name"].split("/", 1)
    branch = state["branch"]
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.v3.raw",
    }

    files_content: dict[str, str] = {}
    investigation_files = state["files_to_investigate"]
    logger.info("[fetch_files] Fetching %d file(s): %s", len(investigation_files), investigation_files)

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for file_path in investigation_files:
            url = f"{_GH_API}/repos/{owner}/{repo_name}/contents/{file_path}?ref={branch}"
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    files_content[file_path] = resp.text
                    logger.info("[fetch_files] ✓ %s (%d chars)", file_path, len(resp.text))
                else:
                    logger.warning("[fetch_files] ✗ %s — HTTP %d", file_path, resp.status_code)
            except Exception as e:
                logger.warning("[fetch_files] ✗ %s — %s", file_path, e)

    logger.info("[fetch_files] %d/%d files fetched successfully",
                len(files_content), len(investigation_files))
    return {"files_content": files_content, "status": "files_fetched"}


_MAX_CONTEXT_ITERATIONS = 3  # max extra fetch rounds before forcing generate_fix


async def request_context(state: AgentState) -> dict:
    """Ask GPT-4o-mini whether more file context is needed.

    Builds a navigation map of available importers/imports and asks the LLM
    to either declare it has enough context or name specific files it needs.
    Only paths present in the nav map are accepted — prevents hallucinations.
    """
    from agent.prompts import CONTEXT_REQUEST_PROMPT, CONTEXT_REQUEST_SYSTEM_PROMPT

    llm      = get_reasoning_llm()
    nav_map  = state.get("rsi_nav_map", {})

    # All paths reachable from current context (importers + imports of fetched files)
    all_nav_paths: set[str] = set()
    nav_lines: list[str]    = []
    already_fetched         = set(state.get("files_content", {}).keys())

    for fp, nav in nav_map.items():
        importers = [p for p in nav.get("importers", []) if p not in already_fetched]
        imports   = [p for p in nav.get("imports",   []) if p not in already_fetched]
        all_nav_paths.update(importers)
        all_nav_paths.update(imports)
        parts = []
        if importers:
            parts.append(f"importers (call this): {', '.join(importers[:6])}"
                         + (f" +{len(importers)-6} more" if len(importers) > 6 else ""))
        if imports:
            parts.append(f"imports (called by this): {', '.join(imports[:6])}"
                         + (f" +{len(imports)-6} more" if len(imports) > 6 else ""))
        if parts:
            nav_lines.append(f"- `{fp}`: " + " | ".join(parts))

    if not all_nav_paths:
        # Nothing left to offer — go straight to generate_fix
        logger.info("[request_context] No unfetched neighbours — skipping to generate_fix")
        return {"need_more_context": False, "requested_files": [], "status": "context_sufficient"}

    logger.info("[request_context] 🤔 Asking LLM if it needs more files. Available files to fetch: %s", list(all_nav_paths))
    nav_map_str  = "\n".join(nav_lines) if nav_lines else "No neighbours available."
    files_summary = "\n".join(
        f"- `{p}` ({len(c)} chars)" for p, c in state.get("files_content", {}).items()
    ) or "None yet."

    try:
        response = await llm.ainvoke([
            SystemMessage(content=CONTEXT_REQUEST_SYSTEM_PROMPT),
            HumanMessage(content=CONTEXT_REQUEST_PROMPT.format(
                nav_map_str  = nav_map_str,
                error_logs   = (state.get("error_logs", "") or "")[:3000],
                pr_diff      = (state.get("pr_diff",    "") or "")[:2000],
                rsi_context  = state.get("rsi_context", ""),
                files_summary= files_summary,
            ))
        ])

        raw      = _extract_json(_to_str(response.content))
        decision = json.loads(raw)
        need_more = bool(decision.get("need_more", False))
        requested = decision.get("files", [])
        reason    = decision.get("reason", "")

        # Validate — only allow paths in nav map, skip already-fetched
        valid   = [f for f in requested if f in all_nav_paths]
        invalid = [f for f in requested if f not in all_nav_paths]
        if invalid:
            logger.warning("[request_context] Rejected paths not in nav map: %s", invalid)

        logger.info("[request_context] 💡 LLM Reasoning: %s", reason)
        logger.info("[request_context] iter=%d  need_more=%s  requested=%s",
                    state.get("context_iteration", 0), need_more, valid)

        if valid:
            logger.info("[request_context] 📥 Will fetch %d new file(s): %s", len(valid), valid)
        else:
            logger.info("[request_context] ⏭️ LLM has enough context, proceeding to generation.")

        return {
            "need_more_context": need_more and bool(valid),
            "requested_files":   valid,
            "status":            "context_requested",
        }

    except Exception as exc:
        logger.warning("[request_context] Failed (proceeding without more context): %s", exc)
        return {"need_more_context": False, "requested_files": [], "status": "context_request_failed"}


async def fetch_requested_files(state: AgentState) -> dict:
    """Fetch the specific files the LLM asked for, add to context, expand nav map."""
    requested = state.get("requested_files", [])
    repo      = state["repo_name"]
    token     = state.get("github_token", "")
    branch    = state["branch"]
    owner, repo_name = repo.split("/", 1)

    # Inline sensitivity check — never fetch secrets/infra files
    sensitivity  = await rsi_db.check_sensitivity(repo, requested)
    safe_files   = [f for f in requested if f not in sensitivity]
    if sensitivity:
        logger.warning("[fetch_requested] Blocking sensitive files: %s", list(sensitivity.keys()))

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github.v3.raw"}
    new_files_content = dict(state.get("files_content", {}))

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        for fp in safe_files:
            if fp in new_files_content:
                continue
            url = f"{_GH_API}/repos/{owner}/{repo_name}/contents/{fp}?ref={branch}"
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    new_files_content[fp] = resp.text
                    logger.info("[fetch_requested] ✓ %s (%d chars)", fp, len(resp.text))
                else:
                    logger.warning("[fetch_requested] ✗ %s — HTTP %d", fp, resp.status_code)
            except Exception as e:
                logger.warning("[fetch_requested] ✗ %s — %s", fp, e)

    new_paths = [f for f in safe_files if f in new_files_content
                 and f not in (state.get("files_content") or {})]

    if not new_paths:
        return {
            "files_content":    new_files_content,
            "context_iteration": state.get("context_iteration", 0) + 1,
            "status":           "additional_context_fetched",
        }

    # RSI metadata for newly fetched files
    new_metadata  = await rsi_db.get_file_metadata(repo, new_paths)
    new_symbols   = await rsi_db.get_file_symbols(repo, new_paths)
    new_imports   = await rsi_db.get_direct_imports(repo, new_paths)
    new_importers = await rsi_db.get_importers(repo, new_paths)

    # Expand nav map so the LLM can chase further hops next iteration
    nav_map = dict(state.get("rsi_nav_map", {}))
    for fp in new_paths:
        nav_map[fp] = {
            "importers": new_importers.get(fp, []),
            "imports":   new_imports.get(fp, []),
        }

    # Append RSI context for new files
    extra_lines: list[str] = ["", "## Additional Context (fetched on request)"]
    for fp in new_paths:
        meta     = new_metadata.get(fp, {})
        role     = meta.get("role_tag", "unknown")
        desc     = meta.get("file_desc", "")
        syms     = new_symbols.get(fp, [])
        deps     = new_imports.get(fp, [])
        imp_list = new_importers.get(fp, [])
        extra_lines.append(f"### `{fp}`")
        extra_lines.append(f"- Role: {role}")
        if desc:
            extra_lines.append(f"- Description: {desc}")
        if syms:
            extra_lines.append(f"- Symbols: {', '.join(syms[:10])}")
        if deps:
            extra_lines.append(f"- Imports: {', '.join(deps[:5])}")
        if imp_list:
            extra_lines.append(f"- Imported by: {', '.join(imp_list[:5])}")
        extra_lines.append("")

    updated_rsi = state.get("rsi_context", "") + "\n".join(extra_lines)
    logger.info("[fetch_requested] Added %d file(s) to context (iter %d)",
                len(new_paths), state.get("context_iteration", 0) + 1)

    return {
        "files_content":    new_files_content,
        "rsi_context":      updated_rsi,
        "rsi_nav_map":      nav_map,
        "context_iteration": state.get("context_iteration", 0) + 1,
        "status":           "additional_context_fetched",
    }


async def generate_fix(state: AgentState) -> dict:
    """Generate the code fix with Qwen 2.5 Coder 32B.

    Context passed to the LLM:
      - repo_summary   (project overview from RSI)
      - rsi_context    (per-file role, symbols, imports, importers, sensitivity)
      - error_logs     (real CI job output)
      - pr_diff        (raw patch from compare API)
      - files_content  (current file contents on the failing branch)
      - memory_context (similar past fixes from agent memory)
    """
    llm = get_coding_llm()

    files_str = "\n\n".join(
        f"### {path}\n```\n{content}\n```"
        for path, content in state.get("files_content", {}).items()
    )

    rsi_context    = state.get("rsi_context", "No RSI context available.")
    memory_context = state.get("memory_context", "")

    repo_summary     = await rsi_db.get_repo_summary(state["repo_name"])
    repo_summary_str = repo_summary["description"] if repo_summary else "No repo summary available."

    logger.info(
        "[generate_fix] Context sizes — repo_summary=%d  rsi_context=%d  "
        "error_logs=%d  pr_diff=%d  files=%d  memory=%d chars",
        len(repo_summary_str), len(rsi_context),
        len(state.get("error_logs", "")),
        len(state.get("pr_diff", "")),
        len(files_str),
        len(memory_context),
    )
    logger.info("[generate_fix] Sending to %s...", get_settings().coding_model_id)

    response = await llm.ainvoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=FIX_GENERATION_PROMPT.format(
            repo_summary=repo_summary_str,
            rsi_context=rsi_context,
            error_logs=state.get("error_logs", ""),
            pr_diff=state.get("pr_diff", ""),
            files_content=files_str,
            memory_context=memory_context,
        )),
    ])

    raw = _to_str(response.content)
    try:
        fix = json.loads(_extract_json(raw))
    except json.JSONDecodeError:
        logger.error("[generate_fix] JSON parse failed. Raw (first 600 chars):\n%s", raw[:600])
        return {
            "proposed_fix": {},
            "status":       "fix_generation_failed",
            "error":        f"LLM did not return valid JSON. Raw: {raw[:500]}",
        }

    fixed_files = [f["path"] for f in fix.get("files", [])]
    logger.info("[generate_fix] Fix ready — pr_title=%r  files=%s",
                fix.get("pr_title", ""), fixed_files)

    return {"proposed_fix": fix, "status": "fix_generated"}


def _normalize_whitespace(text: str) -> str:
    """Normalize line endings and trailing whitespace for fuzzy matching."""
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))


def _find_best_occurrence(text: str, old_text: str, hint_line: int) -> int | None:
    """Find the start index of old_text in text, using hint_line to disambiguate duplicates.
    
    Returns the str index of the best occurrence, or None if not found.
    """
    positions: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = text.find(old_text, start)
        if idx == -1:
            break
        line_num = text[:idx].count("\n") + 1
        positions.append((idx, line_num))
        start = idx + 1

    if not positions:
        return None
    if len(positions) == 1:
        return positions[0][0]

    best = min(positions, key=lambda p: abs(p[1] - hint_line))
    logger.info("[apply_fix] Disambiguated %d occurrences — picked line %d (hint was %d)",
                len(positions), best[1], hint_line)
    return best[0]


def _find_fuzzy(
    text: str,
    old_text: str,
    hint_line: int,
    threshold: float = 0.82,
) -> tuple[int, int] | None:
    """Fuzzy-match old_text inside text using difflib line-window sliding.

    Slides a window of len(old_text_lines) over the file lines within
    ±search_radius of hint_line and picks the window with the highest
    SequenceMatcher ratio.  Returns (char_start, char_end) of that window
    in the original *text* string, or None if the best ratio is below
    threshold.  char_end points to the character immediately after the
    last char of the matched block (not including the trailing newline
    that separates it from the next line).
    """
    file_lines = text.split("\n")
    old_lines  = old_text.split("\n")
    n_old      = len(old_lines)

    if n_old == 0 or not file_lines:
        return None

    search_radius = max(n_old * 2, 20)
    lo = max(0, hint_line - 1 - search_radius)
    hi = min(len(file_lines), hint_line - 1 + search_radius + n_old)

    old_joined  = "\n".join(old_lines)
    best_ratio  = 0.0
    best_start  = -1

    for i in range(lo, max(lo + 1, hi - n_old + 1)):
        window = "\n".join(file_lines[i : i + n_old])
        ratio  = difflib.SequenceMatcher(None, window, old_joined, autojunk=False).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i

    if best_ratio < threshold or best_start == -1:
        logger.debug("[apply_fix] Fuzzy ratio %.3f below threshold %.2f — no match", best_ratio, threshold)
        return None

    logger.info("[apply_fix] Fuzzy matched at line %d with ratio %.3f", best_start + 1, best_ratio)
    matched_block = "\n".join(file_lines[best_start : best_start + n_old])
    char_start    = sum(len(line) + 1 for line in file_lines[:best_start])
    char_end      = char_start + len(matched_block)
    return (char_start, char_end)


async def apply_fix(state: AgentState) -> dict:
    """Patch original files using the LLM's search-and-replace changes."""
    fix = state.get("proposed_fix", {})
    files_content = state.get("files_content", {})
    patched_files = []

    for file_fix in fix.get("files", []):
        path = file_fix["path"]

        if file_fix.get("new_file"):
            patched_files.append({
                "path": path,
                "content": file_fix.get("content", ""),
                "explanation": file_fix.get("explanation", ""),
            })
            continue

        original = files_content.get(path, "")
        if not original:
            logger.warning("[apply_fix] No original content for %s — skipping", path)
            continue

        patched = original
        changes_applied = 0

        for change in file_fix.get("changes", []):
            old_text  = change.get("old_text", "")
            new_text  = change.get("new_text", "")
            hint_line = change.get("line", 1)

            idx       = _find_best_occurrence(patched, old_text, hint_line)
            match_end = idx + len(old_text) if idx is not None else None

            if idx is None:
                # Fallback 1: whitespace normalization
                norm_patched = _normalize_whitespace(patched)
                norm_old     = _normalize_whitespace(old_text)
                idx_norm     = _find_best_occurrence(norm_patched, norm_old, hint_line)
                if idx_norm is not None:
                    logger.info("[apply_fix] Matched after whitespace normalization in %s", path)
                    patched   = norm_patched
                    idx       = idx_norm
                    match_end = idx + len(norm_old)

            if idx is None:
                # Fallback 2: fuzzy difflib matching (handles == vs ===, quote style, etc.)
                fuzzy = _find_fuzzy(patched, old_text, hint_line)
                if fuzzy is not None:
                    logger.info("[apply_fix] Matched via fuzzy fallback in %s", path)
                    idx, match_end = fuzzy

            if idx is not None and match_end is not None:
                patched = patched[:idx] + new_text + patched[match_end:]
                changes_applied += 1
            else:
                logger.warning("[apply_fix] ✗ old_text not found in %s: %r", path, old_text[:120])

        if changes_applied > 0:
            logger.info("[apply_fix] ✓ %s — %d/%d changes applied",
                        path, changes_applied, len(file_fix.get("changes", [])))
            patched_files.append({
                "path": path,
                "content": patched,
                "explanation": file_fix.get("explanation", ""),
            })
        else:
            logger.warning("[apply_fix] ✗ %s — no changes could be applied, dropping file", path)

    updated_fix = {**fix, "files": patched_files}
    return {"proposed_fix": updated_fix, "status": "fix_applied"}


async def post_fix_safety_check(state: AgentState) -> dict:
    """Strip any sensitive files from the LLM's proposed fix before opening a PR."""
    fix            = state.get("proposed_fix", {})
    proposed_files = [f["path"] for f in fix.get("files", [])]

    if not proposed_files:
        return {"status": "post_fix_safety_passed"}

    sensitive_info = await rsi_db.check_sensitivity(state["repo_name"], proposed_files)
    if not sensitive_info:
        return {"status": "post_fix_safety_passed"}

    blocked = list(sensitive_info.keys())
    logger.warning("[post_fix_safety] Stripping %d sensitive file(s): %s",
                   len(blocked),
                   {p: sensitive_info[p].get("sensitivity_reason", "") for p in blocked})

    clean_files = [f for f in fix.get("files", []) if f["path"] not in blocked]
    return {
        "proposed_fix": {**fix, "files": clean_files},
        "unsafe_files": state.get("unsafe_files", []) + blocked,
        "status":       "post_fix_safety_checked",
    }


async def open_pr(state: AgentState) -> dict:
    """Push the fix branch and open a PR via GitHub MCP tools."""
    from agent.tools import get_github_tools

    fix = state.get("proposed_fix", {})

    if not fix.get("files"):
        return {
            "final_pr_url": "",
            "status":       "pr_skipped",
            "error":        "No files in proposed fix — cannot open PR.",
        }

    token = state.get("github_token")
    tools = await get_github_tools(github_token=token)
    owner, repo = state["repo_name"].split("/")
    fix_branch  = f"devops-agent/fix-{state['branch']}"
    tool_map    = {t.name: t for t in tools}

    # ── 1. Create branch ────────────────────────────────────────────────
    create_branch = tool_map.get("create_branch")
    if create_branch:
        try:
            await create_branch.ainvoke({
                "owner": owner, "repo": repo,
                "branch": fix_branch, "from_branch": state["branch"],
            })
        except Exception as e:
            err_msg = str(e)
            if "already exist" not in err_msg.lower():
                logger.warning("[open_pr] Branch creation failed: %s", e)
                return {"final_pr_url": "", "status": "branch_creation_failed", "error": err_msg}

    # ── 2. Push files (batch preferred, per-file fallback) ───────────────
    push_files_tool  = tool_map.get("push_files")
    single_file_tool = tool_map.get("create_or_update_file")
    read_file        = tool_map.get("get_file_contents") or tool_map.get("read_file")
    files_pushed     = False

    if push_files_tool:
        try:
            await push_files_tool.ainvoke({
                "owner": owner, "repo": repo, "branch": fix_branch,
                "files": [{"path": f["path"], "content": f["content"]} for f in fix["files"]],
                "message": fix.get("pr_title", "fix: auto-fix by DevOps Agent"),
            })
            files_pushed = True
            logger.info("[open_pr] Pushed %d file(s) via push_files", len(fix["files"]))
        except Exception as e:
            logger.warning("[open_pr] Batch push failed — falling back to per-file: %s", e)

    if not files_pushed and single_file_tool:
        for file_info in fix["files"]:
            try:
                file_sha = None
                if read_file:
                    try:
                        file_data = await read_file.ainvoke({
                            "owner": owner, "repo": repo,
                            "path": file_info["path"], "branch": fix_branch,
                        })
                        if isinstance(file_data, str) and '"sha":' in file_data:
                            file_sha = json.loads(file_data).get("sha")
                        elif isinstance(file_data, dict):
                            file_sha = file_data.get("sha")
                    except Exception:
                        pass

                payload = {
                    "owner": owner, "repo": repo, "branch": fix_branch,
                    "path":    file_info["path"],
                    "content": file_info["content"],
                    "message": f"fix: {file_info.get('explanation', 'auto-fix by DevOps Agent')}",
                }
                if file_sha:
                    payload["sha"] = file_sha
                await single_file_tool.ainvoke(payload)
                files_pushed = True
                logger.info("[open_pr] Pushed %s", file_info["path"])
            except Exception as e:
                logger.warning("[open_pr] Failed to push %s: %s", file_info["path"], e)

    if not files_pushed:
        return {"final_pr_url": "", "status": "pr_failed",
                "error": "Failed to push any files to the fix branch"}

    # ── 3. Open PR ───────────────────────────────────────────────────────
    create_pr = tool_map.get("create_pull_request")
    pr_url    = ""
    if create_pr:
        try:
            result = await create_pr.ainvoke({
                "owner": owner, "repo": repo,
                "title": fix.get("pr_title", f"fix: auto-fix for {state['branch']}"),
                "body":  fix.get("pr_description", "Automated fix by DevOps Agent"),
                "head":  fix_branch,
                "base":  state["branch"],
            })
            pr_url = str(result)
        except Exception as e:
            logger.warning("[open_pr] PR creation failed: %s", e)
            return {"final_pr_url": "", "status": "pr_failed",
                    "error": f"PR creation failed: {e}"}

    if not pr_url or pr_url.startswith("<error"):
        return {"final_pr_url": "", "status": "pr_failed",
                "error": pr_url or "No PR URL returned"}

    logger.info("[open_pr] PR opened: %s", pr_url)

    # Persist so _handle_merged_fix_pr can recover context after restart
    try:
        await rsi_db.store_fix_job(
            repo_id=state["repo_name"],
            pr_url=pr_url,
            error_logs=state.get("error_logs", ""),
        )
    except Exception as e:
        logger.warning("[open_pr] Failed to persist fix job (non-fatal): %s", e)

    return {"final_pr_url": pr_url, "status": "pr_opened"}


# ─────────────────────────────────────────────────────────
# Conditional edges
# ─────────────────────────────────────────────────────────

def should_fetch_more_context(state: AgentState) -> str:
    """Loop back to fetch more context if LLM asked for it and we haven't hit the cap."""
    if (
        state.get("need_more_context")
        and state.get("requested_files")
        and state.get("context_iteration", 0) < _MAX_CONTEXT_ITERATIONS
    ):
        return "fetch_requested_files"
    return "generate_fix"


def should_open_pr(state: AgentState) -> str:
    """Skip open_pr if post_fix_safety_check left no files to push."""
    fix = state.get("proposed_fix", {})
    if not fix or not fix.get("files"):
        return END
    return "open_pr"


# ─────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("parse_event",           parse_event)
    graph.add_node("rsi_context_build",     rsi_context_build)
    graph.add_node("safety_precheck",       safety_precheck)
    graph.add_node("memory_recall",         memory_recall)
    graph.add_node("fetch_files",           fetch_files)
    graph.add_node("request_context",       request_context)
    graph.add_node("fetch_requested_files", fetch_requested_files)
    graph.add_node("generate_fix",          generate_fix)
    graph.add_node("apply_fix",             apply_fix)
    graph.add_node("post_fix_safety_check", post_fix_safety_check)
    graph.add_node("open_pr",               open_pr)

    graph.set_entry_point("parse_event")

    graph.add_edge("parse_event",           "rsi_context_build")
    graph.add_edge("rsi_context_build",     "safety_precheck")
    graph.add_edge("safety_precheck",       "memory_recall")
    graph.add_edge("memory_recall",         "fetch_files")
    graph.add_edge("fetch_files",           "request_context")
    # Loop: request_context → fetch_requested_files → request_context (up to 3×)
    graph.add_conditional_edges("request_context", should_fetch_more_context)
    graph.add_edge("fetch_requested_files", "request_context")
    graph.add_edge("generate_fix",          "apply_fix")
    graph.add_edge("apply_fix",             "post_fix_safety_check")
    graph.add_conditional_edges("post_fix_safety_check", should_open_pr)
    graph.add_edge("open_pr",              END)

    return graph


agent_graph = build_graph().compile()


# ─────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────

async def run_agent(
    payload: dict,
    job_id: str,
    emit_event: Callable | None = None,
    github_token: str = "",
) -> dict:
    initial_state: AgentState = {
        "github_event":         payload,
        "error_logs":           "",
        "repo_name":            "",
        "branch":               "",
        "github_token":         github_token,
        "changed_files":        [],
        "files_to_investigate": [],
        "rsi_nav_map":          {},
        "rsi_context":          "",
        "unsafe_files":         [],
        "memory_context":       "",
        "files_content":        {},
        "pr_diff":              "",
        "proposed_fix":         {},
        "final_pr_url":         "",
        "status":               "starting",
        "error":                "",
        "retry_count":          0,
        "context_iteration":    0,
        "need_more_context":    False,
        "requested_files":      [],
    }

    if emit_event:
        emit_event("agent_step", {"job_id": job_id, "step": "starting",
                                  "detail": "Parsing CI webhook payload"})

    final_state: dict = {}
    async for step in agent_graph.astream(initial_state):
        node_name   = list(step.keys())[0]
        node_output = step[node_name]
        logger.info("── step: %-22s  status=%s", node_name, node_output.get("status", ""))

        if emit_event:
            emit_event("agent_step", {
                "job_id": job_id,
                "step":   node_name,
                "status": node_output.get("status", ""),
                "detail": _step_description(node_name),
            })
        final_state = {**final_state, **node_output}

    return final_state or {}


def _step_description(node: str) -> str:
    return {
        "parse_event":           "Fetching CI job logs from GitHub Actions",
        "rsi_context_build":     "RSI: role, symbols, direct importers/imports for changed files",
        "safety_precheck":       "Sensitivity check — gating secrets/infra files",
        "memory_recall":         "Searching agent memory for similar past fixes",
        "fetch_files":           "Fetching changed file contents from GitHub",
        "request_context":       "LLM deciding if additional file context is needed",
        "fetch_requested_files": "Fetching additional files requested by LLM",
        "generate_fix":          "Generating fix with GPT-4o",
        "apply_fix":             "Patching original files with LLM's search-and-replace changes",
        "post_fix_safety_check": "Post-generation safety check",
        "open_pr":               "Pushing fix branch and opening Pull Request",
    }.get(node, node)
