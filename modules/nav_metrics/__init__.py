"""Fleet nav metrics ingest and aggregation (PR-N7+)."""

from modules.nav_metrics.aggregate import collect_fleet_rows, import_fleet_inbox, list_inbox_files
from modules.nav_metrics.collector import (
    collector_status,
    ingest_remote_payload,
    start_collector,
    stop_collector,
)
from modules.nav_metrics.ingest import NAV_METRICS_PREFIX, parse_nav_metrics_lines
from modules.nav_metrics.push_client import push_metric_record, push_metric_record_async
from modules.nav_metrics.store import (
    append_nav_metric,
    fleet_summary,
    format_fleet_dashboard,
    read_recent_metrics,
)

__all__ = [
    "NAV_METRICS_PREFIX",
    "append_nav_metric",
    "collect_fleet_rows",
    "collector_status",
    "fleet_summary",
    "format_fleet_dashboard",
    "import_fleet_inbox",
    "ingest_remote_payload",
    "list_inbox_files",
    "parse_nav_metrics_lines",
    "push_metric_record",
    "push_metric_record_async",
    "read_recent_metrics",
    "start_collector",
    "stop_collector",
]
