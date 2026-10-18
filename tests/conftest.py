"""Keep test batches out of the real runs/ directory (set before `lab` is imported)."""

import os
import tempfile
import threading

import pytest

os.environ.setdefault("LAB_RUNS_DIR", tempfile.mkdtemp(prefix="harness-lab-test-runs-"))

from lab import gateway  # noqa: E402  (after LAB_RUNS_DIR)


@pytest.fixture(scope="module")
def mock_gateway(tmp_path_factory):
    server = gateway.serve("mock", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old = {k: os.environ.get(k) for k in ("DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "LAB_MODEL_SPEC")}
    os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
    os.environ["DEEPSEEK_API_KEY"] = "test"
    os.environ.pop("LAB_MODEL_SPEC", None)
    yield
    server.shutdown()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

