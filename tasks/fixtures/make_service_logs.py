"""Generate the `service-logs` fixture and its expected answer (deterministic).

    uv run python tasks/fixtures/make_service_logs.py

Writes tasks/fixtures/service-logs/logs/*.log (copied into the agent workspace) and
tasks/expected/service-logs.json (kept outside the workspace for `check`).
"""

import json
import random
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "service-logs" / "logs"
EXPECTED = HERE.parent / "expected" / "service-logs.json"
SERVICES = ["api", "auth", "billing", "worker"]
CODES = ["E101", "E204", "E318", "E422", "E503"]
MESSAGES = {
    "INFO": ["request served path=/v1/items status=200", "cache refreshed keys=128", "heartbeat ok", "job dequeued queue=default"],
    "WARN": ["slow response latency_ms=1840", "retrying upstream attempt=2", "pool near capacity used=92%"],
    "ERROR": ["upstream timeout", "token signature invalid", "payment provider rejected", "db deadlock detected", "queue overflow"],
}


def main() -> None:
    rng = random.Random(20261013)
    OUT.mkdir(parents=True, exist_ok=True)
    errors_by_service: dict[str, int] = {}
    first_seen: dict[str, str] = {}
    codes = Counter()
    start = datetime(2026, 10, 1, 0, 0, 0)
    for service in SERVICES:
        t = start
        lines = []
        count = 0
        for _ in range(1200):
            t += timedelta(seconds=rng.randint(1, 40))
            level = rng.choices(["INFO", "WARN", "ERROR"], weights=[80, 14, 6])[0]
            stamp = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            message = rng.choice(MESSAGES[level])
            if level == "ERROR":
                code = rng.choices(CODES, weights=[3, 2, 5, 2, 1])[0]
                message += f" code={code}"
                count += 1
                codes[code] += 1
                if code not in first_seen or stamp < first_seen[code]:
                    first_seen[code] = stamp
            lines.append(f"{stamp} {level:<5} {service} {message} trace_id={rng.getrandbits(64):016x}")
        (OUT / f"{service}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")
        errors_by_service[service] = count
    top = codes.most_common(1)[0][0]
    EXPECTED.parent.mkdir(exist_ok=True)
    EXPECTED.write_text(
        json.dumps({"errors_by_service": errors_by_service, "top_error_code": top, "top_error_first_seen": first_seen[top]}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(EXPECTED.read_text())


if __name__ == "__main__":
    main()
