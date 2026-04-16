import dataclasses
from abc import ABC, abstractmethod
from typing import Any

@dataclasses.dataclass
class CDFailureContext:
    """Provider-neutral container for all failure context."""
    job_id: str
    repo: str
    service: str
    environment: str
    status: str                         # "failed" | "degraded" | "rollback"
    error_message: str
    provider: str                       # "aws" | "azure" | "gcp" | "custom"
    deployment_id: str
    timestamp: str
    commit_sha: str
    branch: str
    error_logs: str                     # from webhook or enrichment
    resource_info: dict[str, Any]       # cpu, memory, etc.
    provider_config: dict[str, Any]     # provider-specific IDs
    enriched_logs: str                  # additional logs from cloud API
    enriched_metrics: dict[str, Any]    # additional metrics from cloud API
    enriched_events: list[str]          # recent events from cloud API

class CDProviderAdapter(ABC):
    """Enrichment adapter — fetches additional context from cloud APIs."""

    @abstractmethod
    async def enrich(self, ctx: CDFailureContext) -> CDFailureContext:
        """Fetch logs/metrics/events from the cloud provider and add to context."""
        pass
