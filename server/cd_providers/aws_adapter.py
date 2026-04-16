import logging
import dataclasses
from .base import CDFailureContext, CDProviderAdapter

logger = logging.getLogger("devops_agent.cd_providers.aws")

try:
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError
    BOTO3_AVAILABLE = True
except ImportError:
    BOTO3_AVAILABLE = False


class AWSAdapter(CDProviderAdapter):
    """
    AWS Enrichment Adapter.
    Uses boto3 to fetch logs from CloudWatch.
    """
    
    def __init__(self):
        self.session = None

    def _get_client(self, service_name: str, region_name: str):
        if not BOTO3_AVAILABLE:
            return None
        from config import get_settings
        settings = get_settings()
        
        # If explicit keys are provided, use them. Otherwise rely on environment/IAM role.
        kwargs = {}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        
        region = region_name or settings.aws_region or "us-east-1"
        return boto3.client(service_name, region_name=region, **kwargs)

    async def enrich(self, ctx: CDFailureContext) -> CDFailureContext:
        if not BOTO3_AVAILABLE:
            logger.warning("boto3 not installed. Skipping AWS enrichment.")
            return ctx

        region = ctx.provider_config.get("region")
        log_group = ctx.provider_config.get("log_group")
        
        enriched_logs = ""
        enriched_metrics = {}
        enriched_events = []

        # 1. Fetch CloudWatch Logs if log_group is provided
        if log_group:
            try:
                logs_client = self._get_client("logs", region)
                response = logs_client.filter_log_events(
                    logGroupName=log_group,
                    limit=50,
                    interleaved=True
                )
                events = response.get("events", [])
                if events:
                    lines = [e.get("message", "") for e in events]
                    enriched_logs = "\n".join(lines)
            except Exception as e:
                logger.warning(f"Failed to fetch CloudWatch logs for {log_group}: {e}")

        # 2. Add ECS / Lambda logic here if requested later
        # For now, we return logs
        
        return dataclasses.replace(ctx,
            enriched_logs=enriched_logs if enriched_logs else ctx.enriched_logs,
            enriched_metrics=enriched_metrics if enriched_metrics else ctx.enriched_metrics,
            enriched_events=enriched_events if enriched_events else ctx.enriched_events,
        )
