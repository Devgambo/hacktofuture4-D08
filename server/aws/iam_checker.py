"""
IAM/Permissions error detector and fix strategy generator.

How IAM errors are triggered in a CD pipeline:
  The GitHub Actions OIDC role, CodeDeploy service role, Lambda execution role,
  or ECS task role calls an AWS API but the attached IAM policies do not grant
  the required action on the target resource.  AWS returns:
    - AccessDeniedException       (most services)
    - UnauthorizedOperation       (EC2, CloudFormation)
    - "is not authorized to perform: <action> on resource: <arn>"
    - sts:AssumeRole denied       (cross-account / OIDC role chain)

  These surface in GitHub Actions logs as errors from the Terraform / AWS CLI /
  AWS SDK calls made by the CD pipeline.

Fix strategy (generated for the LLM):
  1. Extract the exact IAM Action and Resource ARN from the error message.
  2. Identify the principal ARN (the role that lacks permission).
  3. Generate the minimal IAM policy statement to add in the IaC.
"""

import logging
import re

logger = logging.getLogger("devops_agent.aws.iam")

# ── Error pattern detection ───────────────────────────────────────────────────

_IAM_PATTERNS = [
    r"AccessDenied(?:Exception)?",
    r"UnauthorizedOperation",
    r"is not authorized to perform",
    r"arn:aws:iam:.*:role/.*is not authorized",
    r"User:.*is not authorized",
    r"not authorized to perform[:\s]+\S+",
    r"sts:AssumeRole.*[Dd]enied",
    r"Access Denied",
]
_IAM_RE = re.compile("|".join(_IAM_PATTERNS))

# Extracts the IAM Action from error messages such as:
#   "is not authorized to perform: ec2:DescribeInstances on resource: arn:..."
#   "not authorized to perform sts:AssumeRole"
_ACTION_RE = re.compile(
    r"perform[:\s]+([a-zA-Z0-9]+:[a-zA-Z0-9]+)",
    re.IGNORECASE,
)

# Extracts the Resource ARN or wildcard
_RESOURCE_RE = re.compile(
    r"on resource[:\s]+(arn:[^\s,\"'\)]+|[*])",
    re.IGNORECASE,
)

# Extracts the calling principal ARN (user, role, assumed-role)
_PRINCIPAL_RE = re.compile(
    r"(arn:aws:(?:iam|sts):[^:]*:[\d]+:(?:user|role|assumed-role)/[\w\-/\.@]+)",
    re.IGNORECASE,
)


def detect(error_logs: str) -> dict | None:
    """Return IAM error details if CI logs indicate a permissions failure, else None."""
    if not _IAM_RE.search(error_logs):
        return None

    action_m    = _ACTION_RE.search(error_logs)
    resource_m  = _RESOURCE_RE.search(error_logs)
    principal_m = _PRINCIPAL_RE.search(error_logs)

    detail = {
        "category":         "iam",
        "missing_action":   action_m.group(1).strip()    if action_m    else None,
        "missing_resource": resource_m.group(1).strip()  if resource_m  else "*",
        "principal_arn":    principal_m.group(1)         if principal_m else None,
    }

    logger.info(
        "[iam.detect] IAM error — action=%s  resource=%s  principal=%s",
        detail["missing_action"], detail["missing_resource"], detail["principal_arn"],
    )
    return detail


def build_fix_strategy(detection: dict) -> str:
    """Return the minimal IAM fix strategy with the exact policy statement needed.

    The generated policy snippet is the smallest addition that grants only the
    missing permission — following the principle of least privilege.
    """
    action    = detection.get("missing_action")   or "UNKNOWN_ACTION"
    resource  = detection.get("missing_resource") or "*"
    principal = detection.get("principal_arn")    or "the deployment role"

    policy_stmt = (
        "{\n"
        '  "Effect": "Allow",\n'
        f'  "Action": ["{action}"],\n'
        f'  "Resource": "{resource}"\n'
        "}"
    )

    terraform_snippet = (
        'statement {\n'
        '  effect    = "Allow"\n'
        f'  actions   = ["{action}"]\n'
        f'  resources = ["{resource}"]\n'
        '}'
    )

    return (
        f"The CD deployment failed because the IAM principal '{principal}' "
        f"is not authorized to perform '{action}' on '{resource}'. "
        f"Fix: Add the following statement to the role's IAM policy in your IaC.\n\n"
        f"JSON policy statement:\n{policy_stmt}\n\n"
        f"Terraform (aws_iam_policy_document data source):\n{terraform_snippet}\n\n"
        f"If using CloudFormation, add this to the IAM::ManagedPolicy or inline "
        f"Policies property of the role resource for '{principal}'.\n"
        f"If using OIDC (GitHub Actions), verify the trust policy of the role "
        f"also allows sts:AssumeRoleWithWebIdentity from the correct GitHub repo."
    )
