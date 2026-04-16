"""
Networking/Config error detector and fix strategy generator.

How networking errors are triggered in a CD pipeline:
  Unlike quota/IAM errors (which come back as AWS API error codes), networking
  failures manifest as OS-level or application-level errors after a resource is
  provisioned but cannot communicate:

  ecr_pull     — ECS task starts but can't pull the container image from ECR.
                 Cause: missing VPC endpoint for ECR/S3, or security group blocks
                 outbound HTTPS, or subnet has no NAT Gateway route.

  security_group — Traffic between services is blocked by SG ingress/egress rules.
                   Cause: missing inbound rule on the target SG for the source IP/SG.

  nat_gateway  — Lambda/ECS in a private subnet can't reach the internet.
                 Cause: subnet's route table has no 0.0.0.0/0 → NAT Gateway route.

  dns          — Hostname resolution fails inside the VPC.
                 Cause: private hosted zone not associated with VPC, or VPC DNS
                 attributes (enableDnsHostnames, enableDnsSupport) disabled.

  subnet       — ECS/Lambda fails to place in the specified subnet.
                 Cause: wrong subnet ID, subnet in wrong AZ, or CIDR exhausted.

  vpc_endpoint — Service calls (S3, ECR, Secrets Manager) fail in private subnets.
                 Cause: VPC endpoint for the service is missing.

Fix strategy: IaC-level changes (Terraform/CDK/CloudFormation) to add the missing
networking configuration.
"""

import logging
import re

logger = logging.getLogger("devops_agent.aws.network")

# ── Categorised error patterns ────────────────────────────────────────────────

_NETWORK_PATTERN_MAP: dict[str, list[str]] = {
    "ecr_pull": [
        r"CannotPullContainerError",
        r"failed to resolve.*ecr",
        r"no such host.*\.ecr\.",
        r"pull access denied.*ecr",
        r"Error response from daemon.*ecr",
        r"repository does not exist.*ecr",
        r"timeout.*pull.*ecr",
    ],
    "security_group": [
        r"connection refused",
        r"Connection timed out.*:\d+",
        r"Host unreachable",
        r"target.*unhealthy",
        r"health check.*fail",
        r"no route to host",
        r"Operation timed out",
        r"i/o timeout",
    ],
    "nat_gateway": [
        r"Network is unreachable",
        r"unable to connect.*internet",
        r"no nat gateway",
        r"route.*0\.0\.0\.0/0.*not found",
        r"REJECT.*0\.0\.0\.0",
        r"cannot connect to.*\b(8\.8\.8|1\.1\.1)\b",
    ],
    "dns": [
        r"Name or service not known",
        r"DNS resolution failed",
        r"getaddrinfo.*NXDOMAIN",
        r"could not resolve host",
        r"name resolution failure",
        r"dial.*no such host",
    ],
    "subnet": [
        r"InvalidSubnetID",
        r"subnet.*not found",
        r"insufficient IP addresses",
        r"CIDR.*exhausted",
        r"No available addresses",
        r"subnet.*does not exist",
    ],
    "vpc_endpoint": [
        r"VPC endpoint.*not found",
        r"Missing VPC endpoint",
        r"interface endpoint.*required",
        r"gateway endpoint.*not configured",
        r"com\.amazonaws\..*endpoint.*unavailable",
    ],
}

_COMPILED: dict[str, re.Pattern] = {
    cat: re.compile("|".join(pats), re.IGNORECASE)
    for cat, pats in _NETWORK_PATTERN_MAP.items()
}

# ── Fix strategy templates (region placeholder filled by build_fix_strategy) ──

_FIX_TEMPLATES: dict[str, str] = {
    "ecr_pull": (
        "ECS cannot pull the container image from ECR. "
        "Root cause: either the task's VPC has no route to ECR (private registry) "
        "or the security group blocks outbound HTTPS (443).\n"
        "Fix option A — Add VPC Interface Endpoints in Terraform:\n"
        "  aws_vpc_endpoint for com.amazonaws.{region}.ecr.api\n"
        "  aws_vpc_endpoint for com.amazonaws.{region}.ecr.dkr\n"
        "  aws_vpc_endpoint for com.amazonaws.{region}.s3 (Gateway type)\n"
        "  Attach a security group that allows inbound HTTPS from the ECS task SG.\n"
        "Fix option B — Ensure the ECS task's security group has an outbound rule "
        "allowing TCP 443 to 0.0.0.0/0, and the task's subnet has a route to a "
        "NAT Gateway (0.0.0.0/0 → nat_gateway_id in the aws_route resource)."
    ),
    "security_group": (
        "A security group is blocking required traffic between services. "
        "Root cause: the target security group is missing an inbound rule "
        "for the required port/protocol from the source.\n"
        "Fix: Add an aws_security_group_rule (Terraform) or update the ingress "
        "block in the aws_security_group resource:\n"
        '  type        = "ingress"\n'
        "  from_port   = <required_port>\n"
        "  to_port     = <required_port>\n"
        '  protocol    = "tcp"\n'
        "  source_security_group_id = <source_sg_id>\n"
        "Verify that the source security group also has an outbound rule "
        "allowing the same port."
    ),
    "nat_gateway": (
        "A Lambda function or ECS task in a private subnet cannot reach the internet. "
        "Root cause: the private subnet's route table has no default route (0.0.0.0/0) "
        "pointing to a NAT Gateway.\n"
        "Fix: Add an aws_route to the private subnet's route table in Terraform:\n"
        "  resource \"aws_route\" \"private_nat\" {\n"
        "    route_table_id         = aws_route_table.private.id\n"
        '    destination_cidr_block = "0.0.0.0/0"\n'
        "    nat_gateway_id         = aws_nat_gateway.main.id\n"
        "  }\n"
        "Ensure the NAT Gateway itself is in a PUBLIC subnet with an Elastic IP, "
        "and that subnet's route table has a route to the Internet Gateway."
    ),
    "dns": (
        "DNS hostname resolution is failing inside the VPC. "
        "Root cause: either the private hosted zone is not associated with the VPC, "
        "or VPC DNS support is disabled.\n"
        "Fix option A — Associate the private hosted zone with the VPC (Terraform):\n"
        "  resource \"aws_route53_zone_association\" \"main\" {\n"
        "    zone_id = aws_route53_zone.private.zone_id\n"
        "    vpc_id  = aws_vpc.main.id\n"
        "  }\n"
        "Fix option B — Enable DNS on the VPC (Terraform):\n"
        "  resource \"aws_vpc\" \"main\" {\n"
        "    enable_dns_hostnames = true\n"
        "    enable_dns_support   = true\n"
        "  }"
    ),
    "subnet": (
        "ECS or Lambda cannot place into the specified subnet. "
        "Root cause: the subnet ID is invalid, in the wrong AZ, or has no available IPs.\n"
        "Fix: Verify the subnet_ids in your ECS service / Lambda configuration "
        "match actual subnet IDs in the target region/AZ. "
        "If the subnet is out of IPs, either expand the CIDR in a new subnet or "
        "use a different existing subnet with available addresses. "
        "In Terraform, update the subnet_ids list in the aws_ecs_service or "
        "aws_lambda_function vpc_config block."
    ),
    "vpc_endpoint": (
        "AWS service calls are failing from a private subnet because a VPC endpoint "
        "is missing — traffic cannot reach the service without going through the internet.\n"
        "Fix: Add the required VPC endpoint in Terraform:\n"
        "  resource \"aws_vpc_endpoint\" \"<service>\" {\n"
        "    vpc_id            = aws_vpc.main.id\n"
        '    service_name      = "com.amazonaws.{region}.<service>"\n'
        '    vpc_endpoint_type = "Interface"  # or "Gateway" for S3/DynamoDB\n'
        "    subnet_ids        = [<private_subnet_ids>]\n"
        "    security_group_ids = [aws_security_group.vpc_endpoint.id]\n"
        '    private_dns_enabled = true\n'
        "  }\n"
        "Common endpoints needed: ecr.api, ecr.dkr, s3 (Gateway), "
        "secretsmanager, ssm, logs."
    ),
}


def detect(error_logs: str) -> dict | None:
    """Return network error details if CI logs indicate a networking failure, else None.

    Checks categories in priority order: ecr_pull first (most common in ECS deploys),
    then security_group, nat_gateway, dns, subnet, vpc_endpoint.
    """
    for category in ("ecr_pull", "security_group", "nat_gateway", "dns", "subnet", "vpc_endpoint"):
        pattern = _COMPILED[category]
        m = pattern.search(error_logs)
        if m:
            logger.info("[network.detect] Category=%s  matched=%r", category, m.group())
            return {
                "category":     "network",
                "sub_category": category,
                "raw_pattern":  m.group(),
            }
    return None


def build_fix_strategy(detection: dict, region: str = "us-east-1") -> str:
    """Return the concrete networking fix strategy with region substituted."""
    sub = detection.get("sub_category", "security_group")
    template = _FIX_TEMPLATES.get(sub, _FIX_TEMPLATES["security_group"])
    return template.replace("{region}", region)
