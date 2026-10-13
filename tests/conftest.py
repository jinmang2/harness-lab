"""Keep test batches out of the real runs/ directory (set before `lab` is imported)."""

import os
import tempfile

os.environ.setdefault("LAB_RUNS_DIR", tempfile.mkdtemp(prefix="harness-lab-test-runs-"))
