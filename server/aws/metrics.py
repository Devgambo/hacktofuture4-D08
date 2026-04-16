"""
CloudWatch P99 metrics fetcher for AWS CD pipeline error categories.

Why P99 (not P95)?
  CD failures are rare, high-impact events.  P99 captures the worst-case
  tail — the 1% of deployment windows where quota exhaustion, IAM denials,
  or network failures are most severe.  P95 would still miss 5% of the most
  critical failure spikes, which at deployment granularity can mean a
  production outage going undetected.

Metric mapping per category:
  quota   → AWS/Usage ResourceCount (Maximum per 5-min bucket → P99)
  iam     → CloudWatch Logs Insights on CloudTrail log group (error count/5min → P99)
  network → AWS/NetworkELB or AWS/ApplicationELB UnHealthyHostCount (ExtendedStatistics p99)
"""

import logging
import time
from datetime import datetime, timedelta, timezone

from aws.client import get_cloudwatch, get_logs

logger = logging.getLogger("devops_agent.aws.metrics")

_DEFAULT_WINDOW_HOURS = 168  # 7 days — enough history for a stable P99 estimate
_DEFAULT_PERIOD       = 300  # 5-minute CloudWatch buckets


def _p99(values: list[float]) -> float:
    """Compute 99th percentile without numpy."""
    if not values:
        return 0.0
    s   = sorted(values)
    idx = max(int(0.99 * len(s)) - 1, 0)
    return s[min(idx, len(s) - 1)]


def fetch_resource_usage_p99(
    service_code: str,
    resource_id: str,
    region: str,
    window_hours: int = _DEFAULT_WINDOW_HOURS,
) -> dict:
    """P99 of AWS resource count for a quota-limited resource.

    Queries the AWS/Usage namespace — available for most regional services
    that have service-quota limits (EC2 instances, ECS tasks, Lambda, etc.).

    Returns {"p99": float, "sample_count": int, "unit": "count"}.
    """
    cw    = get_cloudwatch(region)
    end   = datetime.now(timezone.utc)
    start = end - timedelta(hours=window_hours)

    try:
        resp = cw.get_metric_statistics(
            Namespace="AWS/Usage",
            MetricName="ResourceCount",
            Dimensions=[
                {"Name": "Type",     "Value": "Resource"},
                {"Name": "Resource", "Value": resource_id},
                {"Name": "Service",  "Value": service_code},
                {"Name": "Class",    "Value": "None"},
            ],
            StartTime=start,
            EndTime=end,
            Period=_DEFAULT_PERIOD,
            Statistics=["Maximum"],
        )
        values  = [dp["Maximum"] for dp in resp.get("Datapoints", [])]
        p99_val = _p99(values)
        logger.info(
            "[metrics.quota] service=%s resource=%s  p99=%.1f  samples=%d",
            service_code, resource_id, p99_val, len(values),
        )
        return {"p99": p99_val, "sample_count": len(values), "unit": "count"}
    except Exception as exc:
        logger.warning("[metrics.quota] CloudWatch query failed (non-fatal): %s", exc)
        return {"p99": 0.0, "sample_count": 0, "unit": "count", "error": str(exc)}


def fetch_iam_error_p99(
    log_group: str,
    region: str,
    window_hours: int = _DEFAULT_WINDOW_HOURS,
) -> dict:
    """P99 of IAM AccessDenied event rate per 5-min bucket via CloudWatch Logs Insights.

    Requires CloudTrail → CloudWatch Logs delivery to be configured.
    The log group name is set via AWS_CLOUDTRAIL_LOG_GROUP env var.

    Returns {"p99": float, "sample_count": int, "unit": "errors/5min"}.
    """
    logs     = get_logs(region)
    end_ts   = int(datetime.now(timezone.utc).timestamp())
    start_ts = end_ts - window_hours * 3600

    query = (
        "fields @timestamp, errorCode | "
        "filter errorCode = 'AccessDenied' or errorCode = 'UnauthorizedOperation' | "
        "stats count(*) as cnt by bin(5min) | "
        "sort @timestamp desc"
    )
    try:
        qid = logs.start_query(
            logGroupName=log_group,
            startTime=start_ts,
            endTime=end_ts,
            queryString=query,
        )["queryId"]

        for _ in range(30):
            r = logs.get_query_results(queryId=qid)
            if r["status"] == "Complete":
                counts = [
                    float(f["value"])
                    for row in r["results"]
                    for f in row
                    if f["field"] == "cnt"
                ]
                p99_val = _p99(counts)
                logger.info(
                    "[metrics.iam] log_group=%s  p99=%.1f  samples=%d",
                    log_group, p99_val, len(counts),
                )
                return {"p99": p99_val, "sample_count": len(counts), "unit": "errors/5min"}
            time.sleep(1)

        logger.warning("[metrics.iam] Logs Insights query timed out")
    except Exception as exc:
        logger.warning("[metrics.iam] Logs Insights query failed (non-fatal): %s", exc)

    return {"p99": 0.0, "sample_count": 0, "unit": "errors/5min"}


def fetch_network_p99(
    namespace: str,
    metric_name: str,
    dimensions: list[dict],
    region: str,
    window_hours: int = _DEFAULT_WINDOW_HOURS,
) -> dict:
    """P99 of a network-related CloudWatch metric.

    Uses CloudWatch ExtendedStatistics for native P99 computation — more accurate
    than computing it client-side when there are many data points.

    Common calls:
      namespace="AWS/ApplicationELB" metric_name="UnHealthyHostCount"
      namespace="AWS/ECS"            metric_name="CPUUtilization"

    Returns {"p99": float, "sample_count": int, "unit": "count"}.
    """
    cw    = get_cloudwatch(region)
    end   = datetime.now(timezone.utc)
    start = end - timedelta(hours=window_hours)

    try:
        resp = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=dimensions,
            StartTime=start,
            EndTime=end,
            Period=_DEFAULT_PERIOD,
            ExtendedStatistics=["p99"],
        )
        values = [
            dp["ExtendedStatistics"]["p99"]
            for dp in resp.get("Datapoints", [])
            if "ExtendedStatistics" in dp
        ]
        p99_val = _p99(values)
        logger.info(
            "[metrics.network] %s/%s  p99=%.3f  samples=%d",
            namespace, metric_name, p99_val, len(values),
        )
        return {"p99": p99_val, "sample_count": len(values), "unit": "count"}
    except Exception as exc:
        logger.warning("[metrics.network] CloudWatch query failed (non-fatal): %s", exc)
        return {"p99": 0.0, "sample_count": 0, "unit": "count", "error": str(exc)}
