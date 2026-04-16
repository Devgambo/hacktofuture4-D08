"""
Telegram message formatters using MarkdownV2.
"""

import re


def _md_escape(value: str) -> str:
    """Escape MarkdownV2-reserved characters.
    IMPORTANT: backslash must be escaped FIRST to avoid double-escaping.
    """
    return (
        value.replace("\\", "\\\\")  # must be first
        .replace("|", "\\|")
        .replace("_", "\\_")
        .replace("*", "\\*")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("(", "\\(")
        .replace(")", "\\)")
        .replace("~", "\\~")
        .replace("`", "\\`")
        .replace(">", "\\>")
        .replace("#", "\\#")
        .replace("+", "\\+")
        .replace("-", "\\-")
        .replace("=", "\\=")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace(".", "\\.")
        .replace("!", "\\!")
    )


def _truncate(text: str, limit: int) -> str:
    """Truncate text while keeping whole words where possible."""
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    sliced = normalized[: limit - 3].rsplit(" ", 1)[0]
    return (sliced or normalized[: limit - 3]) + "..."


def ci_failed_started(
    repo: str,
    branch: str,
    workflow: str,
    actor: str,
    job_id: str,
    run_url: str,
) -> str:
    """CI failure detected - agent started."""
    lines = [
        "*WARN \\| CI: Some jobs were not successful*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*Branch:* {_md_escape(branch)}",
        f"*Workflow:* {_md_escape(workflow)}",
        f"*Triggered by:* {_md_escape(actor)}",
        f"*Run id:* {_md_escape(job_id)}",
        "*Status:* DevOps Agent workflow started",
    ]
    if run_url:
        lines.extend(["", f"*Action:* View workflow run", _md_escape(run_url)])
    return "\n".join(lines)


def ci_completed(repo: str, job_id: str, pr_url: str) -> str:
    """CI recovery completed - fix PR created."""
    lines = [
        "*INFO \\| CI Recovery Completed*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*Run id:* {_md_escape(job_id)}",
        "*Status:* Fix PR created successfully",
    ]
    if pr_url:
        lines.extend(["", f"*Action:* View fix PR", _md_escape(pr_url)])
    return "\n".join(lines)


def ci_completed_approval(repo: str, job_id: str, pr_url: str) -> str:
    """CI recovery completed - fix PR created, pending user approval."""
    lines = [
        "*INFO \\| CI Recovery Completed*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*Run id:* {_md_escape(job_id)}",
        "*Status:* Fix PR created successfully",
        "",
        "*Action Required:* Review and choose to merge or close below\\.",
    ]
    if pr_url:
        lines.extend(["", f"*Action:* View fix PR", _md_escape(pr_url)])
    return "\n".join(lines)


def ci_failed(repo: str, job_id: str, error_text: str) -> str:
    """CI recovery failed."""
    short_error = _truncate(error_text or "unknown error", 160)
    return "\n".join(
        [
            "*ERROR \\| CI Recovery Failed*",
            "",
            f"*Repository:* {_md_escape(repo)}",
            f"*Run id:* {_md_escape(job_id)}",
            "*Failure stage:* agent execution",
            f"*Error:* {_md_escape(short_error)}",
            "*Action:* Check backend logs for this run id",
        ]
    )


def pr_main_update(
    repo: str,
    pr_number: int,
    action: str,
    author: str,
    title: str,
    description: str,
    pr_url: str,
    needs_approval: bool = False,
) -> str:
    """PR updated on main branch."""
    lines = [
        "*INFO \\| PR Update on main*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*PR:* \\#{pr_number}",
        f"*Action:* {_md_escape(action)}",
        f"*Author:* {_md_escape(author)}",
        f"*Title:* {_md_escape(_truncate(title, 160))}",
        f"*Description:* {_md_escape(_truncate(description or 'No description', 160))}",
    ]
    if needs_approval:
        lines.extend(["", "*Action Required:* Review and choose to merge or close below\\."])
    if pr_url:
        lines.extend(["", f"*Action:* View PR", _md_escape(pr_url)])
    return "\n".join(lines)


def pr_review_completed(repo: str, pr_number: int, comment_url: str) -> str:
    """PR review posted."""
    lines = [
        "*INFO \\| PR Review Posted*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*PR:* \\#{pr_number}",
        "*Status:* Review comment published",
    ]
    if comment_url:
        lines.extend(["", f"*Action:* View review comment", _md_escape(comment_url)])
    return "\n".join(lines)


def pr_failed(repo: str, pr_number: int, error_text: str) -> str:
    """PR processing failed."""
    short_error = _truncate(error_text or "unknown error", 160)
    return "\n".join(
        [
            "*ERROR \\| PR Processing Failed*",
            "",
            f"*Repository:* {_md_escape(repo)}",
            f"*PR:* \\#{pr_number}",
            "*Stage:* reindex or review",
            f"*Error:* {_md_escape(short_error)}",
            "*Action:* Check backend logs for repo and PR number",
        ]
    )


def pr_review_score(
    repo: str,
    pr_number: int,
    score: int,
    label: str,
    comment_url: str,
    merge_recommendation: str = "block",
    top_findings: list | None = None,
) -> str:
    """PR review completed with a score below the quality threshold — 'Request Fix' button will follow."""
    merge_icon  = {"approve": "✅", "request_changes": "⚠️", "block": "🚫"}.get(merge_recommendation, "⚪")
    merge_label = {
        "approve":         "Approve",
        "request_changes": "Request Changes",
        "block":           "Block — must not merge",
    }.get(merge_recommendation, merge_recommendation)

    lines = [
        "*⚠️ PR Quality Gate Failed*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*PR:* \\#{pr_number}",
        f"*Score:* {score}/100 — {_md_escape(label)}",
        f"*Recommendation:* {merge_icon} {_md_escape(merge_label)}",
        "*Status:* Review posted\\. Click below to request an automated fix\\.",
    ]

    # Surface top critical findings so the user can see why without opening GitHub
    if top_findings:
        critical = [f for f in top_findings if f.get("severity") == "critical"][:2]
        if critical:
            lines.append("")
            lines.append("*Key issues:*")
            for f in critical:
                title = _truncate(f.get("title", f.get("comment", "Issue")), 80)
                fpath = f.get("file", f.get("file_path", "unknown"))
                lines.append(f"🔴 {_md_escape(title)} \\(`{_md_escape(fpath)}`\\)")

    if comment_url:
        lines.extend(["", f"*Review:* {_md_escape(comment_url)}"])
    return "\n".join(lines)


def _score_label(score: int) -> str:
    if score < 30:  return "Critical"
    if score < 50:  return "Needs Work"
    if score < 70:  return "Fair"
    if score < 90:  return "Good"
    return "Excellent"


def pr_low_score_fix_opened(repo: str, pr_number: int, score: int, fix_pr_url: str) -> str:
    """PR was given a low score, so a fix PR was automatically opened."""
    score_label = _score_label(score)
    lines = [
        "*\u26a0\ufe0f PR Quality Gate Failed*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*PR:* \\#{pr_number}",
        f"*Score:* {score}/100",
        "*Status:* Fix PR automatically opened",
    ]
    if fix_pr_url:
        lines.extend(["", f"*Action:* View fix PR", _md_escape(fix_pr_url)])
    return "\n".join(lines)


def cold_start_started(repo: str) -> str:
    """RSI cold start started."""
    return "\n".join(
        [
            "*INFO \\| Repository Initialization Started*",
            "",
            f"*Repository:* {_md_escape(repo)}",
            "*Status:* Building index...",
        ]
    )


def cold_start_completed(repo: str) -> str:
    """RSI cold start completed."""
    return "\n".join(
        [
            "*INFO \\| Repository Initialization Complete*",
            "",
            f"*Repository:* {_md_escape(repo)}",
            "*Status:* Ready for operations",
        ]
    )


def cold_start_failed(repo: str, error_text: str) -> str:
    """RSI cold start failed."""
    short_error = _truncate(error_text or "unknown error", 160)
    return "\n".join(
        [
            "*ERROR \\| Repository Initialization Failed*",
            "",
            f"*Repository:* {_md_escape(repo)}",
            f"*Error:* {_md_escape(short_error)}",
        ]
    )


# ─────────────────────────────────────────────────────────
# CD Failure Reporting
# ─────────────────────────────────────────────────────────

def cd_failure_started(repo: str, service: str, environment: str) -> str:
    """⚙️ CD failure detected — diagnosis agent started."""
    return "\n".join(
        [
            "*⚙️ CD Failure Detected — Diagnosing\\.\\.\\.*",
            "",
            f"*Repository:* {_md_escape(repo)}",
            f"*Service:* {_md_escape(service)}",
            f"*Environment:* {_md_escape(environment)}",
            "*Status:* Gathering cloud logs & identifying root cause\\.\\.\\.",
        ]
    )

def cd_failure_report(repo: str, service: str, environment: str, diagnosis: dict) -> str:
    """🚨 CD DEPLOYMENT FAILED — full diagnostic report."""
    severity = diagnosis.get("severity", "high").lower()
    
    # Emoji based on severity
    if severity == "critical":
        sev_icon = "🚨 CRITICAL"
    elif severity == "high":
        sev_icon = "🔴 HIGH"
    elif severity == "medium":
        sev_icon = "🟠 MEDIUM"
    else:
        sev_icon = "🟡 LOW"
        
    root_cause = diagnosis.get("root_cause", "Unknown")
    recommended_fix = diagnosis.get("recommended_fix", "None")
    
    lines = [
        f"*{sev_icon} \\| CD DEPLOYMENT FAILED*",
        "",
        f"*Repository:* {_md_escape(repo)}",
        f"*Service:* {_md_escape(service)}",
        f"*Environment:* {_md_escape(environment)}",
        "",
        f"*Root Cause:* {_md_escape(root_cause)}",
    ]
    
    immediate_actions = diagnosis.get("immediate_actions", [])
    if immediate_actions:
        lines.append("")
        lines.append("*Immediate Actions:*")
        for action in immediate_actions:
            lines.append(f"• {_md_escape(action)}")
            
    lines.extend([
        "",
        f"*Recommended Fix:* {_md_escape(recommended_fix)}",
    ])
    
    prevent_recurrence = diagnosis.get("prevent_recurrence")
    if prevent_recurrence:
        lines.extend(["", f"*Prevention:* {_md_escape(prevent_recurrence)}"])
        
    resource_analysis = diagnosis.get("resource_analysis")
    if resource_analysis and resource_analysis != "null":
        lines.extend(["", f"*Resource Analysis:* {_md_escape(resource_analysis)}"])

    return "\n".join(lines)
