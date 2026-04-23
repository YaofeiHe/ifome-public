"""CLI script to collect one website's recent article titles from the last 24 hours."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.tools.recent_site_titles import fetch_recent_site_titles  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect recent article titles from one site.")
    parser.add_argument("site_url", help="Website base URL, for example https://www.jiqizhixin.com/")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum number of titles to keep.")
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output for terminal inspection.",
    )
    args = parser.parse_args()

    results = fetch_recent_site_titles(
        args.site_url,
        hours=max(1, args.hours),
        limit=max(1, args.limit),
        now=datetime.now().astimezone(),
    )
    payload = {
        "site_url": args.site_url,
        "hours": max(1, args.hours),
        "count": len(results),
        "items": [asdict(item) for item in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
