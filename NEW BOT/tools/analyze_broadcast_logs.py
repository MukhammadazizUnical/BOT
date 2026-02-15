import argparse
import json
import re
from collections import Counter


LAG_RE = re.compile(r"'lagMs'\s*:\s*(\d+)")
OUTCOME_RE = re.compile(r"'outcome'\s*:\s*'([^']+)'")


def percentile(values: list[int], p: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = int((len(ordered) - 1) * p)
    return ordered[idx]


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze worker log outcomes and lag stats")
    parser.add_argument("logfile", help="Path to worker log file")
    args = parser.parse_args()

    with open(args.logfile, "r", encoding="utf-8", errors="ignore") as fh:
        lines = fh.readlines()

    lags: list[int] = []
    outcomes: Counter[str] = Counter()
    processed = 0

    for line in lines:
        if "process_broadcast_job" not in line or "{\"" in line:
            continue
        if "{'success':" not in line:
            continue
        processed += 1
        lag_match = LAG_RE.search(line)
        if lag_match:
            lags.append(int(lag_match.group(1)))

        outcome_match = OUTCOME_RE.search(line)
        if outcome_match:
            outcomes[outcome_match.group(1)] += 1

    report = {
        "processedJobs": processed,
        "lagMs": {
            "count": len(lags),
            "p50": percentile(lags, 0.50),
            "p95": percentile(lags, 0.95),
            "max": max(lags) if lags else 0,
        },
        "outcomes": dict(outcomes),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
