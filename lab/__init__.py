"""harness-lab: same model, different harness."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = Path(os.environ.get("LAB_RUNS_DIR") or ROOT / "runs")
SKILLS_DIR = ROOT / "skills"
TASKS_DIR = ROOT / "tasks"
ENV_FILE = ROOT / ".env"
DOTENV_KEYS: set[str] = set()  # keys whose value came from .env (not the launch environment)


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Load KEY=VALUE lines from `.env` without overriding the real environment."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").split("\n"):  # only \n ends a line, as when written
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if value and key not in os.environ:
            os.environ[key] = value
            DOTENV_KEYS.add(key)
