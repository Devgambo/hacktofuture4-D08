import logging
import dataclasses
from .base import CDFailureContext, CDProviderAdapter

logger = logging.getLogger("devops_agent.cd_providers.gcp")

try:
    from google.cloud import logging as gcp_logging
    GCP_AVAILABLE = True
except ImportError:
    GCP_AVAILABLE = False


class GCPAdapter(CDProviderAdapter):
    """GCP Cloud Logging Enrichment Adapter."""
    
    async def enrich(self, ctx: CDFailureContext) -> CDFailureContext:
        if not GCP_AVAILABLE:
            logger.warning("google-cloud-logging not installed. Skipping GCP enrichment.")
            return ctx

        project_id = ctx.provider_config.get("project_id")
        service_name = ctx.service
        
        enriched_logs = ""
        
        if project_id:
            try:
                client = gcp_logging.Client(project=project_id)
                # Query recent error logs for the service
                filter_str = f'severity>=ERROR AND resource.labels.service_name="{service_name}"'
                
                entries = list(client.list_entries(filter_=filter_str, max_results=50))
                
                if entries:
                    lines = []
                    for entry in entries:
                        payload = entry.payload
                        if isinstance(payload, dict):
                            lines.append(str(payload.get('message', payload)))
                        else:
                            lines.append(str(payload))
                    enriched_logs = "\n".join(lines)
                    
            except Exception as e:
                logger.warning(f"Failed to fetch GCP logs: {e}")

        return dataclasses.replace(ctx,
            enriched_logs=enriched_logs if enriched_logs else ctx.enriched_logs,
        )
