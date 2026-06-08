"""Importing this first puts the signal/ root on sys.path so jobs run with
`python jobs/<name>.py` can `import app.*`. (Same trick as news/jobs.)"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
