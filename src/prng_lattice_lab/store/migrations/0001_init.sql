-- 0001_init: sweep runs and their per-cell results.
CREATE TABLE IF NOT EXISTS sweep_run (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    config_json  TEXT    NOT NULL,
    lab_version  TEXT    NOT NULL,
    created_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS sweep_cell (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id            INTEGER NOT NULL REFERENCES sweep_run(id),
    bits_per_call     INTEGER NOT NULL,
    num_observations  INTEGER NOT NULL,
    trials            INTEGER NOT NULL,
    successes         INTEGER NOT NULL,
    method_used       TEXT    NOT NULL,
    median_ns         REAL,
    mean_margin       REAL,
    capability_gap    TEXT
);

CREATE INDEX IF NOT EXISTS idx_cell_run ON sweep_cell(run_id);
