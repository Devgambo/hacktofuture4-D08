"""
AWS CD Pipeline Error Analyzer — main orchestrator.

Runs the three detection passes (quota → IAM → network) against GitHub Actions
CI log text and returns a CDAnalysisResult with:
  - detected:      whether an AWS CD error was found
  - category:      "quota" | "iam" | "network"
  - sub_category:  network sub-type (ecr_pull, security_group, nat_gateway, dns, subnet, vpc_endpoint)
  - fix_strategy:  plain-English description the LLM uses to generate the IaC patch
  - p99_metric:    CloudWatch P99 metric for the matched category (best-effort, may be empty)

Metric fetching is non-fatal — if AWS credentials are not configured or the
CloudWatch query fails, the analyzer still returns the fix strategy derived
from log-pattern matching alone.

Detection priority: quota → iam → network
(Quota and IAM errors are more actionable and unambiguous; network errors
are the fallback when OS-level connection errors are present.)
"""

import logging
from dataclasses import dataclass, field

from config import get_settings
from aws import quota as quota_mod
from aws import iam_checker as iam_mod
from aws import network as network_mod

logger = logging.getLogger("devops_agent.aws.cd_analyzer")


@dataclass
class CDAnalysisResult:
    detected:     bool  = False
    category:     str   = ""           # "quota" | "iam" | "network" | ""
    sub_category: str   = ""           # network sub-type
    fix_strategy: str   = ""           # plain-English fix for the LLM
    p99_metric:   dict  = field(default_factory=dict)  # {"p99": float, "sample_count": int, ...}
    raw_detection: dict = field(default_factory=dict)  # raw output from the detector


async def analyze(error_logs: str, region: str | None = None) -> CDAnalysisResult:
    """Analyze GitHub Actions CI log text for AWS CD pipeline failure categories.

    Args:
        error_logs: Raw CI job log text (already fetched by parse_event node).
        region:     AWS region override. Falls back to AWS_REGION env var then us-east-1.

    Returns:
        CDAnalysisResult — always returned, detected=False if no AWS pattern matched.
    """
    settings   = get_settings()
    aws_region = region or settings.aws_region or "us-east-1"
    has_creds  = bool(settings.aws_access_key_id or settings.aws_region)

    if not error_logs:
        return CDAnalysisResult(detected=False)

    # ── Pass 1: Resources/Quota ───────────────────────────────────────────
    quota_det = quota_mod.detect(error_logs)
    if quota_det:
        p99 = {}
        if has_creds and quota_det.get("quota_code"):
            try:
                from aws.metrics import fetch_resource_usage_p99
                p99 = fetch_resource_usage_p99(
                    service_code=quota_det.get("service_code", "ec2"),
                    resource_id=quota_det.get("quota_code", ""),
                    region=aws_region,
                )
            except Exception as exc:
                logger.warning("[cd_analyzer] P99 quota metric failed (non-fatal): %s", exc)

        current_quota = {}
        if has_creds and quota_det.get("service_code") and quota_det.get("quota_code"):
            try:
                current_quota = quota_mod.get_current_quota(
                    quota_det["service_code"], quota_det["quota_code"], aws_region
                )
            except Exception as exc:
                logger.warning("[cd_analyzer] Service Quotas API failed (non-fatal): %s", exc)

        fix = quota_mod.build_fix_strategy(quota_det, current_quota)
        logger.info("[cd_analyzer] category=quota  p99=%s", p99)
        return CDAnalysisResult(
            detected=True,
            category="quota",
            fix_strategy=fix,
            p99_metric=p99,
            raw_detection=quota_det,
        )

    # ── Pass 2: IAM/Permissions ───────────────────────────────────────────
    iam_det = iam_mod.detect(error_logs)
    if iam_det:
        p99 = {}
        if has_creds and settings.aws_cloudtrail_log_group:
            try:
                from aws.metrics import fetch_iam_error_p99
                p99 = fetch_iam_error_p99(
                    log_group=settings.aws_cloudtrail_log_group,
                    region=aws_region,
                )
            except Exception as exc:
                logger.warning("[cd_analyzer] P99 IAM metric failed (non-fatal): %s", exc)

        fix = iam_mod.build_fix_strategy(iam_det)
        logger.info("[cd_analyzer] category=iam  p99=%s  action=%s", p99, iam_det.get("missing_action"))
        return CDAnalysisResult(
            detected=True,
            category="iam",
            fix_strategy=fix,
            p99_metric=p99,
            raw_detection=iam_det,
        )

    # ── Pass 3: Networking/Config ─────────────────────────────────────────
    net_det = network_mod.detect(error_logs)
    if net_det:
        fix = network_mod.build_fix_strategy(net_det, region=aws_region)
        logger.info("[cd_analyzer] category=network  sub=%s", net_det.get("sub_category"))
        return CDAnalysisResult(
            detected=True,
            category="network",
            sub_category=net_det.get("sub_category", ""),
            fix_strategy=fix,
            p99_metric={},  # network metrics require specific LB/ECS ARNs — skipped here
            raw_detection=net_det,
        )

    logger.info("[cd_analyzer] No AWS CD error pattern matched in logs")
    return CDAnalysisResult(detected=False)
