"""
LangGraph agent for PR code review.

Graph:  fetch_pr_files → rsi_enrich → fetch_file_contents
      → generate_review → post_review_comment

- fetch_pr_files:      GitHub API — changed files list + patches + PR head SHA
- rsi_enrich:          RSI queries — role, symbols, imports, blast radius
- fetch_file_contents: GitHub API — full file content at PR head SHA
- generate_review:     GPT-4o-mini — scored JSON review
- post_review_comment: Format and post scored comment to PR

Also exports run_pr_fix() for the Telegram-triggered "Request Fix" flow.
"""

import base64
import json
import logging
import re
from typing import Callable

import httpx

from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from agent.prompts import PR_REVIEW_SYSTEM_PROMPT, PR_REVIEW_PROMPT
from agent.graph import get_reasoning_llm, _extract_json, _to_str
from rsi import db as rsi_db

logger = logging.getLogger("devops_agent.review")

_GH_API         = "https://api.github.com"
_MAX_FILES_FETCH = 10   # cap on file content fetches


# ─────────────────────────────────────────────────────────
# Score helpers
# ─────────────────────────────────────────────────────────

def _score_label(score: int) -> str:
    if score < 30:  return "Critical"
    if score < 50:  return "Needs Work"
    if score < 70:  return "Fair"
    if score < 90:  return "Good"
    return "Excellent"


def _score_emoji(label: str) -> str:
    return {"Critical": "🔴", "Needs Work": "🟠", "Fair": "🟡",
            "Good": "🟢", "Excellent": "⭐"}.get(label, "⚪")


# ─────────────────────────────────────────────────────────
# Diff helpers
# ─────────────────────────────────────────────────────────

def _extract_changed_line_ranges(patch: str) -> list[tuple[int, int]]:
    """Parse unified-diff hunk headers → (start, end) line ranges in the new file."""
    ranges = []
    for line in patch.split("\n"):
        m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
        if m:
            start = int(m.group(1))
            count = int(m.group(2)) if m.group(2) is not None else 1
            ranges.append((start, start + count - 1))
    return ranges


def _gh_headers(token: str) -> dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


# ─────────────────────────────────────────────────────────
# State
# ─────────────────────────────────────────────────────────

class ReviewState(TypedDict):
    repo_name:            str
    pr_number:            int
    pr_branch:            str          # source branch of the PR (set by fetch_pr_files)
    pr_head_sha:          str          # head commit SHA (for content fetching)
    github_token:         str
    changed_files:        list[dict]   # [{path, status, patch}]
    files_content:        dict         # {path: full_file_content}
    repo_summary:         dict
    rsi_context:          dict         # {file_path: {role, symbols, sensitivity, ...}}
    rsi_context_str:      str          # flat string version for fix-agent use
    import_graph_context: str
    review_result:        dict
    comment_url:          str
    status:               str
    error:                str


# ─────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────

async def fetch_pr_files(state: ReviewState) -> dict:
    """Fetch PR changed files via GitHub API (not MCP).

    Gets:
    - pr_head_sha   — head commit SHA for content fetching
    - pr_branch     — source branch name
    - changed_files — [{path, status, patch}] list
    """
    owner, repo = state["repo_name"].split("/")
    pr_number   = state["pr_number"]
    token       = state["github_token"]

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            # PR metadata — head SHA + branch
            pr_resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/pulls/{pr_number}",
                headers=_gh_headers(token),
            )
            if pr_resp.status_code != 200:
                logger.warning("[review] PR metadata HTTP %d for #%d", pr_resp.status_code, pr_number)
                return {"error": f"GitHub API {pr_resp.status_code}", "status": "failed_fetch"}

            pr_data     = pr_resp.json()
            pr_head_sha = pr_data.get("head", {}).get("sha", "")
            pr_branch   = pr_data.get("head", {}).get("ref", "")

            # Changed files
            files_resp = await client.get(
                f"{_GH_API}/repos/{owner}/{repo}/pulls/{pr_number}/files",
                headers=_gh_headers(token),
                params={"per_page": 100},
            )
            if files_resp.status_code != 200:
                logger.warning("[review] PR files HTTP %d for #%d", files_resp.status_code, pr_number)
                return {"error": f"GitHub API {files_resp.status_code}", "status": "failed_fetch"}

            changed_files = [
                {"path": f["filename"], "status": f["status"], "patch": f.get("patch", "")}
                for f in files_resp.json()
            ]

        logger.info("[review] PR #%d — branch=%s  sha=%s  %d changed file(s)",
                    pr_number, pr_branch, pr_head_sha[:8], len(changed_files))
        for f in changed_files:
            logger.info("[review]  %-45s (%s)  patch=%d chars",
                        f["path"], f["status"], len(f.get("patch", "")))

        return {
            "changed_files": changed_files,
            "pr_head_sha":   pr_head_sha,
            "pr_branch":     pr_branch,
            "status":        "pr_files_fetched",
        }

    except Exception as exc:
        logger.exception("[review] fetch_pr_files failed")
        return {"error": str(exc), "status": "failed_fetch"}


async def rsi_enrich(state: ReviewState) -> dict:
    """Query RSI for each changed file: role, symbols, imports, blast radius.

    Uses the new rsi_db helpers instead of raw SQL.
    Builds both a structured dict (for the review prompt) and a flat string
    (rsi_context_str, passed to run_pr_fix if the user requests a fix).
    """
    changed_paths = [
        f["path"] for f in state.get("changed_files", [])
        if f.get("path") and f.get("status") != "removed"
    ]
    repo_id = state["repo_name"]

    repo_summary = await rsi_db.get_repo_summary(repo_id) or {}

    if not changed_paths:
        return {
            "repo_summary":         repo_summary,
            "rsi_context":          {},
            "rsi_context_str":      "No changed files.",
            "import_graph_context": "",
            "status":               "rsi_enriched",
        }

    logger.info("[review_rsi] Querying RSI for %d changed file(s): %s",
                len(changed_paths), changed_paths)

    metadata    = await rsi_db.get_file_metadata(repo_id, changed_paths)
    symbols     = await rsi_db.get_file_symbols(repo_id, changed_paths)
    imports     = await rsi_db.get_direct_imports(repo_id, changed_paths)
    importers   = await rsi_db.get_importers(repo_id, changed_paths)
    sensitivity = await rsi_db.check_sensitivity(repo_id, changed_paths)

    logger.info("[review_rsi] RSI coverage: %d/%d files in index",
                len(metadata), len(changed_paths))
    if len(metadata) < len(changed_paths):
        missing = [p for p in changed_paths if p not in metadata]
        logger.warning("[review_rsi] Not in RSI (may need re-index): %s", missing)

    # Need raw symbol rows for line-range × patch overlap (changed-symbol detection)
    pool = await rsi_db.get_pool()
    sym_rows_by_file: dict[str, list] = {}
    async with pool.acquire() as conn:
        for path in changed_paths:
            rows = await conn.fetch(
                "SELECT symbol_name, symbol_type, start_line, end_line "
                "FROM rsi_symbol_map WHERE repo_id=$1 AND file_path=$2",
                repo_id, path,
            )
            sym_rows_by_file[path] = list(rows)

    patch_by_path = {f["path"]: f.get("patch", "") for f in state.get("changed_files", [])}

    rsi_ctx:   dict      = {}
    rsi_lines: list[str] = []

    for fp in changed_paths:
        meta     = metadata.get(fp, {})
        role     = meta.get("role_tag", "unknown")
        desc     = meta.get("file_desc", "")
        syms     = symbols.get(fp, [])
        deps     = imports.get(fp, [])
        imp_list = importers.get(fp, [])
        is_sens  = fp in sensitivity

        # Which symbols overlap with the changed line ranges?
        changed_ranges  = _extract_changed_line_ranges(patch_by_path.get(fp, ""))
        changed_symbols: list[str] = []
        for sym in sym_rows_by_file.get(fp, []):
            for (range_start, range_end) in changed_ranges:
                if sym["start_line"] <= range_end and sym["end_line"] >= range_start:
                    changed_symbols.append(sym["symbol_name"])
                    break

        rsi_ctx[fp] = {
            "role":            role,
            "file_desc":       desc,
            "sensitivity":     sensitivity.get(fp, {
                "is_flagged": False, "requires_approval": False, "sensitivity_reason": "",
            }),
            "symbols_defined": [s.split(" (")[0] for s in syms],
            "changed_symbols": changed_symbols,
        }

        # Flat string block for this file
        header = f"### `{fp}`"
        if is_sens:
            reason = sensitivity[fp].get("sensitivity_reason", "sensitive")
            header += f"  ⚠️ SENSITIVE — {reason}"
        rsi_lines.append(header)
        rsi_lines.append(f"- Role: {role}")
        if desc:
            rsi_lines.append(f"- Description: {desc}")
        if changed_symbols:
            rsi_lines.append(f"- Changed symbols: {', '.join(changed_symbols)}")
        if syms:
            rsi_lines.append(f"- All symbols: {', '.join(syms[:8])}")
        if deps:
            rsi_lines.append(f"- Imports: {', '.join(deps[:5])}")
        if imp_list:
            rsi_lines.append(f"- Imported by {len(imp_list)} file(s): {', '.join(imp_list[:4])}")
        rsi_lines.append("")

        logger.info(
            "[review_rsi]  %-45s role=%-12s  changed_syms=%s  importers=%d  sensitive=%s",
            fp, role, changed_symbols, len(imp_list), is_sens,
        )
        if imp_list:
            logger.info("[review_rsi]    ↳ importers (1-hop): %s", imp_list[:4])

    # Direct blast radius only (depth 1) — transitive hops available on-demand via nav map
    import_strs: list[str] = []
    for path in changed_paths:
        imp_list = importers.get(path, [])
        if not imp_list:
            import_strs.append(f"- `{path}` — not directly imported by any indexed file.")
        else:
            sample = imp_list[:6]
            more   = len(imp_list) - len(sample)
            suffix = f" (+{more} more)" if more > 0 else ""
            import_strs.append(
                f"- `{path}` — imported by **{len(imp_list)}** file(s): "
                + ", ".join(f"`{f}`" for f in sample) + suffix
            )
        logger.info("[review_rsi]  blast-radius: %s → %d direct importers", path, len(imp_list))

    import_graph_str = "\n".join(import_strs) if import_strs else "No import data available."
    rsi_context_str  = "\n".join(rsi_lines)   if rsi_lines   else "No RSI data for changed files."

    return {
        "repo_summary":         repo_summary,
        "rsi_context":          rsi_ctx,
        "rsi_context_str":      rsi_context_str,
        "import_graph_context": import_graph_str,
        "status":               "rsi_enriched",
    }


async def fetch_file_contents(state: ReviewState) -> dict:
    """Fetch full file contents at the PR head SHA via GitHub API.

    Gives the review LLM the complete file, not just the patch —
    essential for understanding context around the changed lines.
    Capped at _MAX_FILES_FETCH non-removed files.
    """
    changed_files = state.get("changed_files", [])
    pr_head_sha   = state.get("pr_head_sha", "")
    token         = state["github_token"]
    owner, repo   = state["repo_name"].split("/")

    paths = [
        f["path"] for f in changed_files if f.get("status") != "removed"
    ][:_MAX_FILES_FETCH]

    logger.info("[review] Fetching %d file content(s) at SHA %s",
                len(paths), pr_head_sha[:8] if pr_head_sha else "HEAD")

    files_content: dict[str, str] = {}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for path in paths:
                params = {"ref": pr_head_sha} if pr_head_sha else {}
                resp = await client.get(
                    f"{_GH_API}/repos/{owner}/{repo}/contents/{path}",
                    headers=_gh_headers(token),
                    params=params,
                )
                if resp.status_code != 200:
                    logger.warning("[review] ✗ content %s — HTTP %d", path, resp.status_code)
                    continue

                data = resp.json()
                if data.get("encoding") == "base64":
                    raw = base64.b64decode(data["content"].replace("\n", ""))
                    content = raw.decode("utf-8", errors="replace")
                else:
                    content = data.get("content", "")

                files_content[path] = content
                logger.info("[review] ✓ %s (%d chars)", path, len(content))

    except Exception as exc:
        logger.warning("[review] fetch_file_contents failed (non-fatal): %s", exc)

    logger.info("[review] File contents: %d/%d fetched", len(files_content), len(paths))

    return {"files_content": files_content, "status": "files_content_fetched"}


async def generate_review(state: ReviewState) -> dict:
    """Generate scored code review with GPT-4o-mini.

    Context sent to LLM:
    - repo_summary        (project overview)
    - files_content       (full file content at PR head)
    - diff                (patches showing what changed)
    - rsi_context         (role, symbols, sensitivity, changed symbols per file)
    - import_graph_context (transitive blast radius)
    """
    llm = get_reasoning_llm()

    # Format diff
    diff_str = ""
    for f in state.get("changed_files", []):
        path  = f.get("path", "unknown")
        patch = f.get("patch", "(no patch available)")
        diff_str += f"\n\n### {path}\n```diff\n{patch}\n```"

    # Format file contents
    files_content = state.get("files_content", {})
    files_str = ""
    if files_content:
        files_str = "\n\n".join(
            f"### {path}\n```\n{content[:3000]}{'...[truncated]' if len(content) > 3000 else ''}\n```"
            for path, content in files_content.items()
        )
    else:
        files_str = "(file contents unavailable — review based on diff only)"

    repo_summary     = state.get("repo_summary") or {}
    repo_summary_str = (
        repo_summary.get("description", "No summary available.")
        if repo_summary
        else "No repo summary — cold-start index may not have run yet."
    )

    rsi_str = json.dumps(state.get("rsi_context", {}), indent=2)

    logger.info(
        "[review_gen] Context — repo_summary=%d  files=%d  diff=%d  rsi=%d  blast_radius=%d chars",
        len(repo_summary_str), len(files_str), len(diff_str),
        len(rsi_str), len(state.get("import_graph_context", "")),
    )
    logger.info("[review_gen] Sending to GPT-4o-mini...")

    try:
        response = await llm.ainvoke([
            SystemMessage(content=PR_REVIEW_SYSTEM_PROMPT),
            HumanMessage(content=PR_REVIEW_PROMPT.format(
                repo_summary=repo_summary_str,
                files_content=files_str,
                diff=diff_str,
                rsi_context=rsi_str,
                import_graph_context=state.get("import_graph_context", ""),
            )),
        ])

        raw = _extract_json(_to_str(response.content))
        try:
            review = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[review_gen] JSON parse failed — using fallback")
            review = {
                "score":                0,
                "score_label":          "Critical",
                "summary":              _to_str(response.content),
                "score_breakdown":      {"base": 100, "deductions": [], "ceiling_applied": None, "final": 0},
                "findings":             [],
                "merge_recommendation": "block",
                "merge_reason":         "Review parse failed.",
            }

        score = int(review.get("score", review.get("score_breakdown", {}).get("final", 0)))
        review["score_label"] = _score_label(score)
        review["score"] = score  # normalise in case only score_breakdown.final was set

        merge_rec = review.get("merge_recommendation", "block")
        findings  = review.get("findings", review.get("file_reviews", []))  # handle old format

        logger.info("[review_gen] Score: %d/100 — %s  recommendation=%s", score, review["score_label"], merge_rec)
        logger.info("[review_gen] Summary: %s", review.get("summary", "")[:200])
        for f in findings:
            logger.info("[review_gen]  [%s] %s — %s",
                        f.get("severity", "info").upper(),
                        f.get("file", f.get("file_path", "?")),
                        str(f.get("title", f.get("comment", "")))[:100])

        return {"review_result": review, "status": "review_generated"}

    except Exception as exc:
        logger.exception("[review_gen] LLM call failed")
        return {"error": str(exc), "status": "failed_generation"}


async def post_review_comment(state: ReviewState) -> dict:
    """Format the scored review and post it as a PR comment via GitHub API."""
    if state.get("error"):
        return {"status": "failed"}

    review    = state.get("review_result", {})
    score     = review.get("score", 0)
    label     = review.get("score_label", _score_label(score))
    emoji     = _score_emoji(label)
    summary   = review.get("summary", "No summary.")

    # New structured fields
    score_breakdown = review.get("score_breakdown", {})
    findings        = review.get("findings", review.get("file_reviews", []))  # backward compat
    merge_rec       = review.get("merge_recommendation", "request_changes")
    merge_reason    = review.get("merge_reason", "")

    merge_icon  = {"approve": "✅", "request_changes": "⚠️", "block": "🚫"}.get(merge_rec, "⚪")
    merge_label = {
        "approve":         "Approve — safe to merge",
        "request_changes": "Request Changes — fix before merge",
        "block":           "Block — must not merge",
    }.get(merge_rec, merge_rec)

    # ── Header ────────────────────────────────────────────
    body  = "## 🤖 DevOps Agent — PR Review\n\n"
    body += f"### {emoji} Score: **{score} / 100 — {label}**\n\n"
    body += f"**Recommendation:** {merge_icon} {merge_label}"
    if merge_reason:
        body += f"\n> {merge_reason}"
    body += "\n\n"

    # ── Score breakdown (deductions + ceiling) ─────────────
    deductions = score_breakdown.get("deductions", [])
    if deductions:
        body += "<details>\n<summary>Score breakdown</summary>\n\n"
        body += "| Finding | Severity | Points deducted |\n|---|---|---|\n"
        total_deducted = 0
        for d in deductions:
            sev = d.get("severity", "info")
            fid = d.get("finding_id", "—")
            pts = d.get("points_deducted", 0)
            total_deducted += pts
            sev_icon = "🔴" if sev == "critical" else "🟠" if sev == "warning" else "🔵"
            body += f"| {fid} | {sev_icon} {sev} | −{pts} |\n"
        body += f"\n**Base:** 100  →  **After deductions:** {100 - total_deducted}"
        ceiling = score_breakdown.get("ceiling_applied")
        if ceiling:
            final = score_breakdown.get("final", score)
            body += f"  →  **After ceiling:** {final}\n\n> ⚠️ _Ceiling applied: {ceiling}_"
        body += "\n\n</details>\n\n"

    # ── Summary ───────────────────────────────────────────
    body += f"---\n\n### Summary\n{summary}\n\n"

    # ── Findings ─────────────────────────────────────────
    if findings:
        body += "---\n\n### Findings\n\n"
        for f in findings:
            sev    = f.get("severity", "info").lower()
            icon   = "🔴" if sev == "critical" else "🟠" if sev == "warning" else "🔵"
            fid    = f.get("id", "")
            title  = f.get("title", "")
            fpath  = f.get("file", f.get("file_path", "unknown"))
            lr     = f.get("line_range")
            sym    = f.get("symbol")
            detail = f.get("detail", f.get("comment", ""))
            fix    = f.get("fix", "")

            loc_str = f"`{fpath}`"
            if lr:
                loc_str += f" @ {lr}"
            if sym:
                loc_str += f" (`{sym}`)"

            header = f"#### {icon} {fid + ' — ' if fid else ''}{title or sev.upper()}"
            body += f"{header}\n\n**Location:** {loc_str}\n\n"
            if detail:
                body += f"**Issue:** {detail}\n\n"
            if fix:
                body += f"**Fix:**\n```\n{fix}\n```\n\n"

    # Telegram hint if below fix threshold
    if score < 50:
        body += f"---\n> ⚠️ Score below quality threshold ({score}/100). "
        body += "A fix can be requested via the DevOps Agent Telegram bot.\n"

    body += "\n---\n*Generated by [DevOps Agent](https://github.com)*\n"

    token       = state["github_token"]
    owner, repo = state["repo_name"].split("/")
    pr_number   = state["pr_number"]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{_GH_API}/repos/{owner}/{repo}/issues/{pr_number}/comments",
                headers=_gh_headers(token),
                json={"body": body},
            )
            if resp.status_code not in (200, 201):
                logger.warning("[review] Comment post HTTP %d: %s",
                               resp.status_code, resp.text[:200])
                return {"error": f"Comment post failed ({resp.status_code})", "status": "failed_comment"}

            comment_url = resp.json().get("html_url", "")
            logger.info("[review] Comment posted: %s", comment_url)
            return {"comment_url": comment_url, "status": "comment_posted"}

    except Exception as exc:
        logger.exception("[review] post_review_comment failed")
        return {"error": str(exc), "status": "failed_comment"}


# ─────────────────────────────────────────────────────────
# Graph
# ─────────────────────────────────────────────────────────

def build_review_graph() -> StateGraph:
    graph = StateGraph(ReviewState)

    graph.add_node("fetch_pr_files",      fetch_pr_files)
    graph.add_node("rsi_enrich",          rsi_enrich)
    graph.add_node("fetch_file_contents", fetch_file_contents)
    graph.add_node("generate_review",     generate_review)
    graph.add_node("post_review_comment", post_review_comment)

    graph.set_entry_point("fetch_pr_files")

    graph.add_edge("fetch_pr_files",      "rsi_enrich")
    graph.add_edge("rsi_enrich",          "fetch_file_contents")
    graph.add_edge("fetch_file_contents", "generate_review")
    graph.add_edge("generate_review",     "post_review_comment")
    graph.add_edge("post_review_comment", END)

    return graph


review_agent_graph = build_review_graph().compile()


# ─────────────────────────────────────────────────────────
# Public entry point — review
# ─────────────────────────────────────────────────────────

async def run_pr_review(
    repo_name:    str,
    pr_number:    int,
    github_token: str,
    emit_event:   Callable | None = None,
    job_id:       str = "",
) -> dict:
    """Run the PR review pipeline and post the scored comment."""
    initial_state: ReviewState = {
        "repo_name":            repo_name,
        "pr_number":            pr_number,
        "pr_branch":            "",
        "pr_head_sha":          "",
        "github_token":         github_token,
        "changed_files":        [],
        "files_content":        {},
        "repo_summary":         {},
        "rsi_context":          {},
        "rsi_context_str":      "",
        "import_graph_context": "",
        "review_result":        {},
        "comment_url":          "",
        "status":               "starting",
        "error":                "",
    }

    if emit_event:
        emit_event("agent_step", {"job_id": job_id, "step": "starting",
                                  "detail": "Fetching PR diff and files..."})

    step_descriptions = {
        "fetch_pr_files":      "Fetching PR changed files via GitHub API",
        "rsi_enrich":          "RSI: role, symbols, imports, blast radius",
        "fetch_file_contents": "Fetching full file contents at PR head",
        "generate_review":     "Generating scored review with GPT-4o-mini",
        "post_review_comment": "Posting scored comment to PR",
    }

    final_state: dict = {}
    async for step in review_agent_graph.astream(initial_state):
        node_name   = list(step.keys())[0]
        node_output = step[node_name]
        logger.info("── review step: %-22s  status=%s",
                    node_name, node_output.get("status", ""))

        if emit_event:
            emit_event("agent_step", {
                "job_id": job_id,
                "step":   node_name,
                "status": node_output.get("status", ""),
                "detail": step_descriptions.get(node_name, node_name),
            })
        final_state = {**final_state, **node_output}

    return final_state or {}


# ─────────────────────────────────────────────────────────
# Public entry point — fix (Telegram "Request Fix" button)
# ─────────────────────────────────────────────────────────

async def run_pr_fix(
    repo_name:       str,
    pr_number:       int,
    pr_branch:       str,
    review_result:   dict,
    rsi_context_str: str,
    changed_files:   list[str],
    pr_diff:         str,
    github_token:    str,
    emit_event:      Callable | None = None,
    job_id:          str = "",
) -> dict:
    """Fix a PR that scored below the quality threshold.

    Reuses the CI fixer agent nodes directly (no synthetic webhook payload).
    Uses the review findings as the "error context" so the LLM knows what to fix.

    Pipeline: safety_precheck → memory_recall → fetch_files
            → generate_fix → apply_fix → post_fix_safety_check → open_pr
    """
    from agent.graph import (
        safety_precheck, memory_recall, fetch_files,
        request_context, fetch_requested_files,
        generate_fix, apply_fix, post_fix_safety_check, open_pr,
        _MAX_CONTEXT_ITERATIONS,
    )

    score       = review_result.get("score", 0)
    label       = review_result.get("score_label", _score_label(score))
    summary     = review_result.get("summary", "")
    findings    = review_result.get("findings", [])

    # Build a structured "error log" from the review findings
    issue_lines = [
        f"## PR Quality Gate Failed — Score {score}/100 ({label})",
        f"\n**Review Summary:** {summary}\n",
        "## Issues Requiring Fixes:",
    ]
    files_with_issues: list[str] = []
    for fr in findings:
        sev     = fr.get("severity", "info").upper()
        fpath   = fr.get("file", "unknown")
        detail  = fr.get("detail", "")
        sym     = fr.get("symbol")
        sym_str = f" (symbol: {sym})" if sym else ""
        issue_lines.append(f"- `{fpath}` [{sev}]{sym_str}: {detail}")
        if sev in ("CRITICAL", "WARNING") and fpath not in files_with_issues:
            files_with_issues.append(fpath)

    error_logs = "\n".join(issue_lines)

    # Fallback: if no specific issue files, use all changed files
    if not files_with_issues:
        files_with_issues = changed_files[:8]

    logger.info("[pr_fix] Starting fix for %s#%d — score=%d  target files=%s",
                repo_name, pr_number, score, files_with_issues)

    # Build nav map from RSI so the context loop can offer neighbours on-demand
    try:
        raw_imports   = await rsi_db.get_direct_imports(repo_name, files_with_issues[:10])
        raw_importers = await rsi_db.get_importers(repo_name, files_with_issues[:10])
        rsi_nav_map: dict = {
            fp: {
                "importers": raw_importers.get(fp, []),
                "imports":   raw_imports.get(fp, []),
            }
            for fp in files_with_issues[:10]
        }
    except Exception as e:
        logger.warning("[pr_fix] Could not build nav map (non-fatal): %s", e)
        rsi_nav_map = {}

    state: dict = {
        "github_event":         {},
        "error_logs":           error_logs,
        "repo_name":            repo_name,
        "branch":               pr_branch,
        "github_token":         github_token,
        "changed_files":        changed_files,
        "files_to_investigate": files_with_issues,
        "rsi_nav_map":          rsi_nav_map,
        "rsi_context":          rsi_context_str,
        "unsafe_files":         [],
        "memory_context":       "",
        "files_content":        {},
        "pr_diff":              pr_diff,
        "proposed_fix":         {},
        "final_pr_url":         "",
        "status":               "starting_fix",
        "error":                "",
        "retry_count":          0,
        "context_iteration":    0,
        "need_more_context":    False,
        "requested_files":      [],
    }

    STEPS          = [safety_precheck, memory_recall, fetch_files]
    TERMINAL_STATUSES = {"fix_generation_failed", "pr_failed",
                         "pr_skipped", "branch_creation_failed"}

    # Run safety_precheck → memory_recall → fetch_files
    for step_fn in STEPS:
        if emit_event:
            emit_event("agent_step", {
                "job_id": job_id,
                "step":   step_fn.__name__,
                "status": "running",
                "detail": f"PR fix: {step_fn.__name__}",
            })
        result = await step_fn(state)
        state  = {**state, **result}
        logger.info("[pr_fix] step=%-22s  status=%s",
                    step_fn.__name__, state.get("status", ""))

        if state.get("status") in TERMINAL_STATUSES:
            logger.warning("[pr_fix] Early stop at %s — %s",
                           step_fn.__name__, state.get("error", ""))
            return state

    # Dynamic context request loop (up to _MAX_CONTEXT_ITERATIONS rounds)
    for _iter in range(_MAX_CONTEXT_ITERATIONS):
        if emit_event:
            emit_event("agent_step", {"job_id": job_id, "step": "request_context",
                                      "status": "running", "detail": "LLM deciding if more context needed"})
        result = await request_context(state)
        state  = {**state, **result}
        logger.info("[pr_fix] request_context iter=%d  need_more=%s  files=%s",
                    _iter, state.get("need_more_context"), state.get("requested_files"))

        if not state.get("need_more_context") or not state.get("requested_files"):
            break

        if emit_event:
            emit_event("agent_step", {"job_id": job_id, "step": "fetch_requested_files",
                                      "status": "running", "detail": f"Fetching {len(state['requested_files'])} additional file(s)"})
        result = await fetch_requested_files(state)
        state  = {**state, **result}
        logger.info("[pr_fix] fetch_requested iter=%d  files_now=%d",
                    _iter, len(state.get("files_content", {})))

    # Run generate_fix → apply_fix → post_fix_safety_check
    for step_fn in [generate_fix, apply_fix, post_fix_safety_check]:
        if emit_event:
            emit_event("agent_step", {
                "job_id": job_id,
                "step":   step_fn.__name__,
                "status": "running",
                "detail": f"PR fix: {step_fn.__name__}",
            })
        result = await step_fn(state)
        state  = {**state, **result}
        logger.info("[pr_fix] step=%-22s  status=%s",
                    step_fn.__name__, state.get("status", ""))

        if state.get("status") in TERMINAL_STATUSES:
            logger.warning("[pr_fix] Early stop at %s — %s",
                           step_fn.__name__, state.get("error", ""))
            return state

    # open_pr only if there are files to push
    fix = state.get("proposed_fix", {})
    if not fix or not fix.get("files"):
        state["status"] = "pr_skipped"
        state["error"]  = "No files in proposed fix"
        logger.warning("[pr_fix] No files to push — skipping PR creation")
        return state

    if emit_event:
        emit_event("agent_step", {"job_id": job_id, "step": "open_pr",
                                  "status": "running", "detail": "Opening fix PR"})
    result = await open_pr(state)
    state  = {**state, **result}
    logger.info("[pr_fix] final status=%s  pr_url=%s",
                state.get("status"), state.get("final_pr_url", ""))

    return state
