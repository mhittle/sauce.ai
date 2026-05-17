import os
import sys

# Ensure the project root is on sys.path so `import app...` works when pytest
# is launched from any cwd (matters for the admin "Run tests" view).
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# Disable CSRF enforcement suite-wide (mirrors Flask-WTF's WTF_CSRF_ENABLED=
# False testing convention). Must run before `app.config` is imported so the
# Config class picks it up. test_csrf.py re-enables it on its own app to
# exercise the real enforcement path.
os.environ.setdefault("CSRF_ENABLED", "0")
