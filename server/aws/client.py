"""
boto3 client factory for AWS CD pipeline error detection.

Credentials are loaded from environment variables:
  AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_SESSION_TOKEN (optional)

If running on EC2/ECS/Lambda, credentials are picked up automatically
from the instance/task IAM role — no explicit keys needed.
"""

import logging

import boto3

from config import get_settings

logger = logging.getLogger("devops_agent.aws.client")


def get_aws_session(region: str | None = None) -> boto3.Session:
    settings = get_settings()
    kwargs: dict = {"region_name": region or settings.aws_region or "us-east-1"}
    if settings.aws_access_key_id:
        kwargs["aws_access_key_id"]     = settings.aws_access_key_id
        kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        if settings.aws_session_token:
            kwargs["aws_session_token"] = settings.aws_session_token
    return boto3.Session(**kwargs)


def get_cloudwatch(region: str | None = None):
    return get_aws_session(region).client("cloudwatch")


def get_logs(region: str | None = None):
    return get_aws_session(region).client("logs")


def get_cloudtrail(region: str | None = None):
    return get_aws_session(region).client("cloudtrail")


def get_service_quotas(region: str | None = None):
    return get_aws_session(region).client("service-quotas")


def get_iam():
    return get_aws_session().client("iam")


def get_ec2(region: str | None = None):
    return get_aws_session(region).client("ec2")
