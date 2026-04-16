import logging
import dataclasses
from .base import CDFailureContext, CDProviderAdapter

logger = logging.getLogger("devops_agent.cd_providers.azure")

try:
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient
    AZURE_AVAILABLE = True
except ImportError:
    AZURE_AVAILABLE = False


class AzureAdapter(CDProviderAdapter):
    """Azure Monitor Enrichment Adapter."""
    
    async def enrich(self, ctx: CDFailureContext) -> CDFailureContext:
        if not AZURE_AVAILABLE:
            logger.warning("azure-monitor-query not installed. Skipping Azure enrichment.")
            return ctx

        workspace_id = ctx.provider_config.get("workspace_id")
        
        enriched_logs = ""
        
        if workspace_id:
            try:
                # Queries Azure Monitor for the last errors 
                credential = DefaultAzureCredential()
                client = LogsQueryClient(credential)
                
                query = "AppExceptions | top 50 by TimeGenerated desc"
                
                # In a real app we'd need a time range
                response = client.query_workspace(
                    workspace_id=workspace_id,
                    query=query,
                    timespan="PT1H" 
                )
                
                if response.tables:
                    # just extract some raw data
                    lines = []
                    for row in response.tables[0].rows:
                        lines.append(str(row))
                    enriched_logs = "\n".join(lines)
            except Exception as e:
                logger.warning(f"Failed to fetch Azure logs: {e}")

        return dataclasses.replace(ctx,
            enriched_logs=enriched_logs if enriched_logs else ctx.enriched_logs,
        )
