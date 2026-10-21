"""week2 deployment verifier: one fixed command for every week2 task.

    python3 week2_verify.py [WORKSPACE]

Loops that check completion with a command (the Verified RALPH preset, lab ralph-verified and
ralph-check) are configured once per deployment, not per task. This picks the acceptance suite
from the workspace's SPEC.md title (`# durations: spec`, `# sizes: spec` or `# versions: spec`), runs it on the
workspace, prints its JSON line and exits with its code. An unknown workspace exits 2.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = {"durations": HERE / "week2_acceptance.py", "sizes": HERE / "week2_sizes_acceptance.py",
          "versions": HERE / "week2_versions_acceptance.py"}


def main() -> int:
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    spec = workspace / "SPEC.md"
    title = spec.read_text(encoding="utf-8").splitlines()[0] if spec.is_file() else ""
    name = title.removeprefix("# ").split(":")[0].strip()
    suite = SUITES.get(name)
    if suite is None:
        print(f'{{"passed": 0, "total": 0, "failed": [{{"test": "verify", "rule": "", "error": "no week2 SPEC.md in {workspace}"}}]}}')
        return 2
    return subprocess.run([sys.executable, str(suite), str(workspace)]).returncode


if __name__ == "__main__":
    sys.exit(main())
