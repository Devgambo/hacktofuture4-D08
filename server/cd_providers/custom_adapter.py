import dataclasses
import logging
import asyncio

from .base import CDFailureContext, CDProviderAdapter

logger = logging.getLogger("devops_agent.cd_providers.custom")

class CustomAdapter(CDProviderAdapter):
    """
    No-op passthrough adapter.
    Used for custom, self-hosted, or unrecognized providers where 
    the webhook payload already contains everything needed, 
    or we don't have an automated way to query their API.
    """
    
    async def enrich(self, ctx: CDFailureContext) -> CDFailureContext:
        logger.info(f"CustomAdapter: No enrichment available for provider '{ctx.provider}', passing through context.")
        return ctx
