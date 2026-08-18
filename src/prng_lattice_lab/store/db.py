"""
Sole owner of the results database (SQLite). Every write goes through here and is
validated against schema/records.schema.json before it lands. No other module
opens the DB. Mirrors repoauditor's store/ discipline so the fold-in feels native.

Minimal but real: enough to persist sweep runs and cells so a report is a pure
read projection over stored records (never recomputed at report time).
"""
from __future__ import annotations

import json
import sqlite3
from importlib import resources
from pathlib import Path

_SCHEMA_CACHE: dict | None = None


def _load_schema() -> dict:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        # schema/ lives at the project root, resolved relative to this file.
        root = Path(__file__).resolve().parents[3]
        with open(root / "schema" / "records.schema.json", "r", encoding="utf-8") as fh:
            _SCHEMA_CACHE = json.load(fh)
    return _SCHEMA_CACHE


def _validate(record_type: str, record: dict) -> None:
    """Lightweight required-field check against the schema. Full jsonschema
    validation is a drop-in upgrade (add jsonschema to deps); kept dependency-free
    here so the scaffold runs out of the box. Fails loud on missing required keys.
    """
    schema = _load_schema()
    defs = schema.get("$defs", {})
    spec = defs.get(record_type)
    if spec is None:
        raise ValueError(f"no schema definition for record type {record_type!r}")
    missing = [k for k in spec.get("required", []) if k not in record]
    if missing:
        raise ValueError(f"{record_type} record missing required fields: {missing}")


class Store:
    def __init__(self, path: str | Path = "data/lab.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        root = Path(__file__).resolve().parent / "migrations"
        for sql_file in sorted(root.glob("*.sql")):
            self.conn.executescript(sql_file.read_text(encoding="utf-8"))
        self.conn.commit()

    def record_sweep_run(self, run: dict) -> int:
        _validate("SweepRun", run)
        cur = self.conn.execute(
            "INSERT INTO sweep_run(config_json, lab_version, created_at) VALUES (?,?,?)",
            (json.dumps(run["config"]), run["lab_version"], run["created_at"]),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def record_cell(self, run_id: int, cell: dict) -> None:
        _validate("SweepCell", cell)
        self.conn.execute(
            "INSERT INTO sweep_cell(run_id, bits_per_call, num_observations, trials, "
            "successes, method_used, median_ns, mean_margin, capability_gap) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (run_id, cell["bits_per_call"], cell["num_observations"], cell["trials"],
             cell["successes"], cell["method_used"], cell.get("median_ns"),
             cell.get("mean_margin"), cell.get("capability_gap")),
        )
        self.conn.commit()

    def list_cells(self, run_id: int) -> list[dict]:
        cur = self.conn.execute(
            "SELECT bits_per_call, num_observations, trials, successes, method_used, "
            "median_ns, mean_margin, capability_gap FROM sweep_cell WHERE run_id=? "
            "ORDER BY bits_per_call, num_observations", (run_id,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def close(self) -> None:
        self.conn.close()
