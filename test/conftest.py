"""
Runs before any test module (or main.py) is imported for this whole test session.

utils/logger.py's setup_logging() reads LOG_DIR from the environment and is
configured once, the first time main.py is imported — after that it's a no-op
(idempotent), so it can't be redirected later via a per-test fixture/monkeypatch.
Setting LOG_DIR here, at conftest.py's module level, keeps the entire test run's
log output inside test/_test_logs/ instead of writing into the real project's
logs/ folder.
"""
import os

os.environ.setdefault("LOG_DIR", os.path.join(os.path.dirname(__file__), "_test_logs"))
