"""
query_loader.py
Reads, caches, and formats SQL files from backend/queries/.

Usage
-----
    from query_loader import load_query

    sql = load_query("mql/volume", table=TABLE, trunc="DAY", quarter_start="2026-01-01")
    rows = execute_query(sql)

File naming convention
----------------------
    backend/queries/<category>/<name>.sql

Template syntax
---------------
SQL files use Python {param} placeholders for structural elements (table names,
column names, date-truncation functions, Python-computed dates) that cannot be
passed as bound SQL parameters.  User-supplied VALUES must still be passed as
bound parameters to `execute_query(sql, params=[...])` — never interpolated here.
"""

import functools
from pathlib import Path
from typing import Any

_QUERIES_DIR = Path(__file__).parent / "queries"
_cache: dict[str, str] = {}


def load_query(name: str, **kwargs: Any) -> str:
    """
    Load a .sql file from backend/queries/<name>.sql, format it with **kwargs,
    and return the final SQL string.

    Results are cached by file path (not by kwargs), so the disk read happens
    only once per server lifetime.  If a template key is missing the call raises
    KeyError with a clear message listing the available placeholders.

    Args:
        name:    Slash-separated path relative to queries/, without .sql extension.
                 Example: "mql/volume", "coverage/current".
        **kwargs: Named values substituted into {placeholder} in the SQL file.
                  These should be STRUCTURAL values only (table names, column
                  names, date-function strings, Python-computed dates).
                  Do NOT pass user-supplied values here — bind them via params.

    Returns:
        Formatted SQL string ready to pass to execute_query().
    """
    path = _QUERIES_DIR / f"{name}.sql"
    if not path.exists():
        raise FileNotFoundError(f"SQL file not found: {path}")

    # Read + cache the raw template
    raw = _cache.get(name)
    if raw is None:
        raw = path.read_text(encoding="utf-8")
        _cache[name] = raw

    if not kwargs:
        return raw

    try:
        return raw.format(**kwargs)
    except KeyError as exc:
        available = [w.strip("{}") for w in __import__("re").findall(r"\{[^}]+\}", raw)]
        raise KeyError(
            f"Placeholder {exc} not supplied for query '{name}'. "
            f"Placeholders in file: {available}"
        ) from exc


def clear_cache() -> None:
    """Flush the in-memory query cache (useful in tests)."""
    _cache.clear()
