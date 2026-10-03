"""Report email: unconfigured and failed sends are recorded, not silent."""
import socket

from app import mailer
from app.config import Settings
from app.store import Store


def _closed_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    return port


def test_unconfigured_reports_why():
    ok, err = mailer.send_report_detailed(Settings(smtp_host=None), "a@b.c", "r1", "<p>x</p>", {})
    assert ok is False and "not configured" in err
    assert mailer.mail_enabled(Settings(smtp_host=None)) is False


def test_unreachable_host_reports_why():
    s = Settings(smtp_host="127.0.0.1", smtp_port=_closed_port(), smtp_starttls=False)
    ok, err = mailer.send_report_detailed(s, "a@b.c", "r1", "<p>x</p>", {"adversarial": {"trials": 1}})
    assert ok is False and err.startswith("could not reach 127.0.0.1:")


def test_cli_test_send_prints_failure(capsys):
    s = Settings(smtp_host="127.0.0.1", smtp_port=_closed_port(), smtp_starttls=False)
    assert mailer.main(["me@lab.edu"], settings=s) == 1
    assert mailer.main(["not-an-address"], settings=s) == 2
    out = capsys.readouterr().out
    assert "SMTP_HOST=127.0.0.1" in out and "FAILED: could not reach" in out


def test_store_migrates_email_error_column(tmp_path):
    """A database created before the column existed gains it on open."""
    import sqlite3
    from app.store import SCHEMA
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)  # the base schema predates the column
    assert "email_error" not in {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    conn.commit(); conn.close()
    st = Store(str(path))
    assert "email_error" in {r["name"] for r in st._conn.execute("PRAGMA table_info(runs)")}
