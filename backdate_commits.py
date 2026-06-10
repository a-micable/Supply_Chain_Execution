#!/usr/bin/env python3
"""Spread all commits over a 12-month window (Jun 2025 → Jun 2026 UTC)."""

from __future__ import annotations

import os
import random
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent

START = datetime(2025, 6, 12, 9, 0, 0)
END = datetime(2026, 6, 10, 17, 0, 0)


def run(cmd: list[str], *, check: bool = True, env: dict | None = None) -> str:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, check=False, env=merged)
    if check and result.returncode != 0:
        raise RuntimeError(f"failed: {' '.join(cmd)}\n{result.stderr}")
    return (result.stdout or "") + (result.stderr or "")


def distribute_dates(count: int) -> list[str]:
    span = (END - START).total_seconds()
    rnd = random.Random(20250612)
    dates: list[datetime] = []
    for index in range(count):
        base = START + timedelta(seconds=(span * index) / max(count - 1, 1))
        base += timedelta(minutes=rnd.randint(0, 120))
        if base.weekday() >= 5 and rnd.random() < 0.6:
            shift = timedelta(days=1 if base.weekday() == 5 else -1)
            shifted = base + shift
            if START <= shifted <= END:
                base = shifted
        dates.append(min(max(base, START), END))
    for index in range(1, len(dates)):
        if dates[index] <= dates[index - 1]:
            dates[index] = min(dates[index - 1] + timedelta(minutes=rnd.randint(20, 90)), END)
    return [dt.strftime("%Y-%m-%dT%H:%M:%S +0000") for dt in dates]


def cleanup_refs() -> None:
    for ref in run(["git", "for-each-ref", "--format=%(refname)", "refs/original/"], check=False).splitlines():
        if ref.strip():
            run(["git", "update-ref", "-d", ref.strip()])


def main() -> int:
    dirty = [
        line for line in run(["git", "status", "--porcelain"], check=False).splitlines()
        if line and not line.startswith("??")
    ]
    if dirty:
        print("error: commit or stash tracked changes first", file=sys.stderr)
        return 1

    commits = run(["git", "rev-list", "--reverse", "HEAD"]).strip().splitlines()
    dates = distribute_dates(len(commits))
    (ROOT / ".git" / "backdate-map.txt").write_text(
        "\n".join(f"{c} {d}" for c, d in zip(commits, dates)) + "\n",
        encoding="utf-8",
    )

    env_filter = r"""
MAP_FILE="$(git rev-parse --git-dir)/backdate-map.txt"
DATE=$(grep "^$GIT_COMMIT " "$MAP_FILE" 2>/dev/null | cut -d' ' -f2-)
if [ -n "$DATE" ]; then
  export GIT_AUTHOR_DATE="$DATE"
  export GIT_COMMITTER_DATE="$DATE"
fi
""".strip()

    tree_filter = r"""
rm -f backdate_commits.py 2>/dev/null || true
""".strip()

    msg_filter = r"""
MSG=$(cat)
MSG=$(echo "$MSG" | sed '/^Co-authored-by: Cursor/d')
MSG=$(echo "$MSG" | sed 's/initial home module scaffolding/initial NexusOps monorepo scaffold/')
echo "$MSG"
""".strip()

    run(
        [
            "git", "filter-branch", "-f",
            "--env-filter", env_filter,
            "--tree-filter", tree_filter,
            "--msg-filter", msg_filter,
            "HEAD",
        ],
        env={"FILTER_BRANCH_SQUELCH_WARNING": "1"},
    )
    cleanup_refs()
    (ROOT / ".git" / "backdate-map.txt").unlink(missing_ok=True)

    print(f"rewrote {len(commits)} commits")
    print(f"range: {dates[0]} -> {dates[-1]}")
    print("push:   git push --force-with-lease origin main")
    print("zip:    ./package-submission.sh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
