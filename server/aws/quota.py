"""
Resources/Quota error detector and fix strategy generator.

How quota errors are triggered in a CD pipeline:
  Terraform apply / CloudFormation deploy / CDK deploy tries to CREATE a new
  AWS resource (EC2 instance, ECS task, Lambda, S3 bucket, etc.) but the
  account has hit the regional service quota limit.  AWS returns:
    - LimitExceededException      (most services)
    - VcpuLimitExceeded           (EC2)
    - RequestLimitExceeded        (API rate limit variant)
    - TooManyRequestsException    (Lambda, API Gateway)

  These surface in GitHub Actions logs as Terraform/CDK/CloudFormation errors.

Fix strategy (generated for the LLM):
  1. Identify the exact service + quota code from the error.
  2. Query Service Quotas API for current limit.
  3. If quota is adjustable: generate a quota-increase request in IaC or
     a boto3 call (request_service_quota_increase).
  4. If not adjustable: generate an IaC diff to reduce resource count below limit.
"""

import logging
import re

from aws.client import get_service_quotas

logger = logging.getLogger("devops_agent.aws.quota")

# ── Error pattern detection ───────────────────────────────────────────────────

_QUOTA_PATTERNS = [
    r"LimitExceededException",
    r"RequestLimitExceeded",
    r"TooManyRequestsException",
    r"VcpuLimitExceeded",
    r"InstanceLimitExceeded",
    r"ResourceLimitExceeded",
    r"QuotaExceededException",
    r"Service limit reached",
    r"exceeded.*quota",
    r"limit.*exceeded",
    r"Maximum number of.*reached",
    r"reached the maximum",
]
_QUOTA_RE = re.compile("|".join(_QUOTA_PATTERNS), re.IGNORECASE)

# Maps lower-case error substrings → (service_code, quota_name, quota_code)
# These are the most common quota hits in CD pipelines.
_KNOWN_QUOTA_MAP: dict[str, dict] = {
    "vcpulimitexceeded": {
        "service_code": "ec2",
        "quota_name": "Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances",
        "quota_code": "L-1216C47A",
    },
    "instancelimitexceeded": {
        "service_code": "ec2",
        "quota_name": "Running On-Demand EC2 instances",
        "quota_code": "L-1216C47A",
    },
    "task definition": {
        "service_code": "ecs",
        "quota_name": "Task definitions per region",
        "quota_code": "L-21C621EB",
    },
    "function count": {
        "service_code": "lambda",
        "quota_name": "Function and layer storage",
        "quota_code": "L-2ACBD22F",
    },
    "concurrent executions": {
        "service_code": "lambda",
        "quota_name": "Concurrent executions",
        "quota_code": "L-B99A9384",
    },
    "bucket": {
        "service_code": "s3",
        "quota_name": "Buckets",
        "quota_code": "L-DC2B2D3D",
    },
    "stack": {
        "service_code": "cloudformation",
        "quota_name": "Stacks",
        "quota_code": "L-0485CB21",
    },
}


def detect(error_logs: str) -> dict | None:
    """Return quota error details if CI logs indicate a quota breach, else None."""
    if not _QUOTA_RE.search(error_logs):
        return None

    match = _QUOTA_RE.search(error_logs)
    detail: dict = {"category": "quota", "raw_pattern": match.group()}

    logs_lower = error_logs.lower()
    for key, meta in _KNOWN_QUOTA_MAP.items():
        if key in logs_lower:
            detail.update(meta)
            break

    logger.info("[quota.detect] Quota error found: %s", detail)
    return detail


def get_current_quota(service_code: str, quota_code: str, region: str) -> dict:
    """Fetch the current quota value from AWS Service Quotas API.

    Returns {} on failure — callers treat this as non-fatal.
    """
    try:
        sq   = get_service_quotas(region)
        resp = sq.get_service_quota(ServiceCode=service_code, QuotaCode=quota_code)
        q    = resp["Quota"]
        return {
            "quota_name": q.get("QuotaName", ""),
            "value":      q.get("Value", 0),
            "unit":       q.get("Unit", ""),
            "adjustable": q.get("Adjustable", False),
        }
    except Exception as exc:
        logger.warning("[quota] Service Quotas API failed (non-fatal): %s", exc)
        return {}


def build_fix_strategy(detection: dict, current_quota: dict) -> str:
    """Return a plain-English fix strategy for the LLM to turn into an IaC patch."""
    service    = detection.get("service_code", "unknown").upper()
    quota_name = detection.get("quota_name", "the service quota")
    quota_code = detection.get("quota_code", "")
    current    = current_quota.get("value", "unknown")
    adjustable = current_quota.get("adjustable", True)  # assume adjustable if unknown

    if adjustable:
        return (
            f"The CD deployment failed because the AWS {service} quota "
            f"'{quota_name}' (current limit: {current}) was exceeded. "
            f"Fix option A — request a quota increase in your IaC: "
            f"add an aws_servicequotas_service_quota resource (Terraform) or "
            f"RequestServiceQuotaIncrease API call targeting quota code '{quota_code}'. "
            f"Fix option B — reduce the number of {service} resources requested "
            f"in the failing IaC template to stay below the current limit of {current}. "
            f"Prefer option B for immediate unblocking, option A for long-term capacity."
        )

    return (
        f"The CD deployment failed because the AWS {service} quota "
        f"'{quota_name}' (limit: {current}) was exceeded. "
        f"This quota is NOT adjustable via the Service Quotas API. "
        f"Fix: Reduce the number of {service} resources requested in the IaC template "
        f"to stay under the hard limit of {current}. "
        f"Consider consolidating resources or using a different resource type."
    )
