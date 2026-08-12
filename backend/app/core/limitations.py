"""Automated LIMITATIONS.md appends (M-35 hook; PROJECT.md §1).

Automated producers (M-20 in-control inflation findings, and later M-13
seasonal warnings and M-27/M-28 sensitivity flags) append entries to the
living register through this single helper, so every entry follows the
register's template and numbering.

Appends happen in the persistence phase of a run (run_experiment), never
inside run_pipeline — reproduction re-runs must not grow the register.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import ConfigError
from app.core.time import utc_now

_LIM_ID_RE = re.compile(r"^## LIM-(\d+)\b", re.MULTILINE)


def next_lim_id(text: str) -> str:
    numbers = [int(m) for m in _LIM_ID_RE.findall(text)]
    return f"LIM-{max(numbers, default=0) + 1:03d}"


def append_limitation(
    path: Path,
    *,
    title: str,
    description: str,
    affected_rqs: str,
    mitigation_status: str,
    source: str,
) -> str:
    """Append one templated entry to the register; returns the new LIM id."""
    if not path.is_file():
        raise ConfigError("LIMITATIONS register not found", path=str(path))
    text = path.read_text(encoding="utf-8")
    lim_id = next_lim_id(text)
    entry = (
        f"\n## {lim_id} — {title}\n\n"
        f"Date discovered:    {utc_now().date().isoformat()}\n"
        f"Description:        {description}\n"
        f"Affected RQ(s):     {affected_rqs}\n"
        f"Mitigation status:  {mitigation_status}\n"
        f"Source:             {source}\n"
    )
    path.write_text(text.rstrip("\n") + "\n" + entry, encoding="utf-8")
    return lim_id
