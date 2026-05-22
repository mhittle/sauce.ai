#!/usr/bin/env python3
"""Pick `ready-for-agent` roadmap items and flip them to `in-progress`.

Triggered by `.github/workflows/dev-agent.yml` on push-to-main when
`roadmap.md` changes. Pure stdlib.

Behaviour:
  * Scan the at-a-glance table at the top of `roadmap.md` for rows
    whose Status cell is `ready-for-agent`. For each such row, flip
    both the row's Status cell AND the matching `### <Title>` detail
    section's `**Status:**` line to `in-progress`.
  * If any rows were picked, commit `roadmap.md` with `[skip ci]` in
    the message (so the push doesn't re-trigger this workflow) and
    push to `origin/main`. Skip the git steps when run locally
    (i.e. `GITHUB_ACTIONS` is not `true`) so a dry-run leaves the
    working tree dirty for inspection.
  * Emit the picked titles to `$GITHUB_OUTPUT` as `items=<JSON array>`.
    On no picks, emit `items=[]` (idempotent).
  * Warn — never fail — when a table title has no matching detail
    section header, or when a detail section has no
    `**Status:** ready-for-agent` line.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP = REPO_ROOT / "roadmap.md"
TARGET_STATUS = "ready-for-agent"
NEW_STATUS = "in-progress"

_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*"
    r"\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$"
)


def _is_separator(cells: list[str]) -> bool:
    return all(set(c) <= {"-", ":"} for c in cells if c)


def _is_header(cells: list[str]) -> bool:
    return cells[0].lower() == "pri"


def _flip_table(text: str) -> tuple[str, list[str]]:
    picked: list[str] = []
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        m = _ROW_RE.match(line)
        if not m:
            out.append(line)
            continue
        cells = [m.group(i).strip() for i in range(1, 6)]
        if _is_header(cells) or _is_separator(cells):
            out.append(line)
            continue
        if cells[4] == TARGET_STATUS:
            picked.append(cells[3])
            cells[4] = NEW_STATUS
            out.append(
                f"| {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | {cells[4]} |\n"
            )
        else:
            out.append(line)
    return "".join(out), picked


def _flip_detail(text: str, title: str) -> tuple[str, str | None]:
    heading_re = re.compile(r"^### " + re.escape(title) + r"\s*$", re.MULTILINE)
    heading = heading_re.search(text)
    if not heading:
        return text, f"no detail section header found for '{title}'"
    section_start = heading.end()
    next_heading = re.search(r"^### ", text[section_start:], re.MULTILINE)
    section_end = (
        section_start + next_heading.start() if next_heading else len(text)
    )
    section = text[section_start:section_end]
    status_re = re.compile(
        r"(\*\*Status:\*\*\s*)" + re.escape(TARGET_STATUS) + r"\b"
    )
    new_section, n = status_re.subn(r"\g<1>" + NEW_STATUS, section, count=1)
    if n == 0:
        return text, (
            f"detail section for '{title}' has no "
            f"`**Status:** {TARGET_STATUS}` line"
        )
    return text[:section_start] + new_section + text[section_end:], None


def _emit_output(items: list[str]) -> None:
    payload = "items=" + json.dumps(items)
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write(payload + "\n")
    else:
        print(payload)


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def _push_with_retry(attempts: int = 3) -> None:
    # main can advance between checkout and push (concurrent merges, or a
    # re-run replaying an old SHA). Rebase the flip commit onto the latest
    # main and retry rather than failing the dispatch.
    for i in range(attempts):
        try:
            _run(["git", "push", "origin", "HEAD:main"])
            return
        except subprocess.CalledProcessError:
            if i == attempts - 1:
                raise
            _run(["git", "fetch", "origin", "main"])
            _run(["git", "rebase", "origin/main"])


def main() -> int:
    original = ROADMAP.read_text(encoding="utf-8")
    text, picked = _flip_table(original)

    warnings: list[str] = []
    for title in picked:
        text, warn = _flip_detail(text, title)
        if warn:
            warnings.append(warn)

    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)

    if not picked:
        _emit_output([])
        print("no ready-for-agent items found")
        return 0

    if text != original:
        ROADMAP.write_text(text, encoding="utf-8")

    if os.environ.get("GITHUB_ACTIONS") == "true" and text != original:
        _run(["git", "config", "user.name", "github-actions[bot]"])
        _run([
            "git", "config", "user.email",
            "github-actions[bot]@users.noreply.github.com",
        ])
        _run(["git", "add", str(ROADMAP)])
        msg = (
            f"agent dispatcher: flip {len(picked)} item(s) "
            f"to in-progress [skip ci]"
        )
        _run(["git", "commit", "-m", msg])
        _push_with_retry()

    _emit_output(picked)
    print(f"picked={picked}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
