"""`check` helper: exit 0 if answer JSON equals the expected JSON (key order ignored).

    python3 compare_json.py answer.json expected.json
"""

import json
import sys

try:
    answer = json.load(open(sys.argv[1], encoding="utf-8"))
    expected = json.load(open(sys.argv[2], encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    print(f"cannot read: {exc}")
    sys.exit(1)
if answer != expected:
    print(f"mismatch\nanswer:   {answer}\nexpected: {expected}")
    sys.exit(1)
