import os
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JOBS = os.path.join(HERE, "jobs")
if JOBS not in sys.path:
    sys.path.insert(0, JOBS)

from _bootstrap import job_lock, AlreadyRunning  # noqa: E402


def test_acquire_then_release_then_reacquire():
    name = "pytest_lock_a"
    with job_lock(name):
        pass
    # Should be re-acquirable after release.
    with job_lock(name):
        pass


def test_second_acquire_while_held_raises():
    name = "pytest_lock_b"
    with job_lock(name):
        with pytest.raises(AlreadyRunning):
            with job_lock(name):
                pass  # pragma: no cover


def test_independent_jobs_do_not_block_each_other():
    with job_lock("pytest_lock_c"):
        with job_lock("pytest_lock_d"):
            pass


def test_release_on_exception():
    name = "pytest_lock_e"
    with pytest.raises(RuntimeError):
        with job_lock(name):
            raise RuntimeError("body blew up")
    # Lock should be released even though the body raised.
    with job_lock(name):
        pass
