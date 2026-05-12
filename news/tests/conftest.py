import os
import sys

# Ensure the project root is on sys.path so `import app...` works when pytest
# is launched from any cwd (matters for the admin "Run tests" view).
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
