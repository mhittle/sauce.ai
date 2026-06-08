import pathlib
import sys

# Put signal/ on the path so `import app.*` works when pytest is invoked from
# the repo root (`python -m pytest signal/tests/ -q`).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
