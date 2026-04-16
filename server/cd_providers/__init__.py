from .base import CDFailureContext, CDProviderAdapter
from .custom_adapter import CustomAdapter
from .aws_adapter import AWSAdapter
from .azure_adapter import AzureAdapter
from .gcp_adapter import GCPAdapter

import logging
logger = logging.getLogger("devops_agent.cd_providers")

def get_cd_adapter(provider_name: str) -> CDProviderAdapter:
    """Factory to return the appropriate enrichment adapter."""
    name = provider_name.lower().strip()
    if name == "aws":
        return AWSAdapter()
    elif name == "azure":
        return AzureAdapter()
    elif name == "gcp":
        return GCPAdapter()
    else:
        # Fallback for custom or unrecognized providers
        return CustomAdapter()

__all__ = [
    "CDFailureContext",
    "CDProviderAdapter",
    "get_cd_adapter",
]
