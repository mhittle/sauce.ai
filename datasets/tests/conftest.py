import os
import tempfile

# app.main builds a module-level app at import; keep its catalog out of the repo.
os.environ.setdefault("DATASETS_DATA_DIR", tempfile.mkdtemp(prefix="datasets-test-"))
os.environ.pop("ANTHROPIC_API_KEY", None)
