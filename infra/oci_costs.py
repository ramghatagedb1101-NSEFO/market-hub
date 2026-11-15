"""
What the Oracle account has cost, day by day (owner, 15 Nov 2026: "why has Oracle charged me 101 rupees on 13th Nov?").
Reads Oracle's own usage records (Usage API, COST) from the start of the month before last to today, and prints the
total per day and per service, and the account's currency. Read-only; nothing is changed. Same settings as
infra/oci_launch.py. Run by oci-ip.yml (action=costs).
"""
import sys
from datetime import datetime, timedelta, timezone

import oci

from oci_launch import config


def main() -> int:
    cfg = config()
    u = oci.usage_api.UsageapiClient(cfg)
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = (end - timedelta(days=45)).replace(day=1)
    for group in (None, ["service"]):
        d = oci.usage_api.models.RequestSummarizedUsagesDetails(
            tenant_id=cfg["tenancy"], time_usage_started=start, time_usage_ended=end, granularity="DAILY",
            query_type="COST", group_by=group)
        items = u.request_summarized_usages(d).data.items
        rows = {}
        for it in items:
            key = (it.time_usage_started.strftime("%Y-%m-%d"), it.service if group else "all services")
            rows[key] = rows.get(key, 0.0) + float(it.computed_amount or 0)
            cur = it.currency
        total = sum(v for (dd, s), v in rows.items() if s == "all services") if not group else sum(rows.values())
        print(f"{'by service' if group else 'by day'}: total {total:.4f} {cur if items else ''} from {start:%d %b %Y}")
        for (dd, s), v in sorted(rows.items()):
            if abs(v) > 0.00001:
                print(f"  {dd} {s}: {v:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
