"""
init_db.py — Granite Ghost database schema

Creates ghost.db with all tables needed by the scheduler (and the rest of
the system, once you build it).

Run once. Re-running is safe — uses IF NOT EXISTS throughout.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("ghost.db")

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- =====================================================================
-- 1. EVENT LOG  (append-only, every signal from the world lands here)
-- =====================================================================
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    source     TEXT    NOT NULL CHECK(source IN (
                   'sms','news','weather','spotify','pir','mic','interaction'
               )),
    payload    TEXT    NOT NULL,
    consumed   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_unconsumed ON events(consumed, ts);
CREATE INDEX IF NOT EXISTS idx_events_source_ts  ON events(source, ts);


-- =====================================================================
-- 2. SCHEDULED EVENTS  (the scheduler's calendar — cron + one-offs)
-- =====================================================================
CREATE TABLE IF NOT EXISTS scheduled_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    kind         TEXT    NOT NULL CHECK(kind IN (
                     'briefing','medication','appointment','check_in','custom'
                 )),
    title        TEXT    NOT NULL,
    cron_expr    TEXT,
    one_off_at   TEXT,
    priority     INTEGER NOT NULL DEFAULT 5 CHECK(priority BETWEEN 1 AND 10),
    active       INTEGER NOT NULL DEFAULT 1,
    last_fired   TEXT,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    CHECK ((cron_expr IS NULL) != (one_off_at IS NULL))
);


-- =====================================================================
-- 3. UTTERANCE QUEUE  (scheduler -> orchestrator)
-- =====================================================================
CREATE TABLE IF NOT EXISTS utterance_queue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    deliver_after   TEXT    NOT NULL,
    expires_at      TEXT,
    priority        INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 10),
    template_name   TEXT    NOT NULL,
    context_query   TEXT    NOT NULL,
    source_event_id INTEGER REFERENCES scheduled_events(id),
    delivered_at    TEXT,
    response        TEXT
);
CREATE INDEX IF NOT EXISTS idx_queue_pending
    ON utterance_queue(delivered_at, deliver_after, priority);


-- =====================================================================
-- 4. ROUTINE BASELINE  (learned activity pattern for wellbeing detection)
-- =====================================================================
CREATE TABLE IF NOT EXISTS routine (
    day_of_week    INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
    hour           INTEGER NOT NULL CHECK(hour BETWEEN 0 AND 23),
    activity_score REAL    NOT NULL DEFAULT 0,
    sample_count   INTEGER NOT NULL DEFAULT 0,
    last_updated   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (day_of_week, hour)
);


-- =====================================================================
-- 5. WELLBEING STATE  (singleton — one row, id=1)
-- =====================================================================
CREATE TABLE IF NOT EXISTS wellbeing_state (
    id                   INTEGER PRIMARY KEY CHECK(id = 1),
    last_interaction_at  TEXT,
    last_check_in_at     TEXT,
    consecutive_misses   INTEGER NOT NULL DEFAULT 0,
    alert_sent_at        TEXT,
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);


-- =====================================================================
-- 6. ACTIVITY TRACKING  (routine prompting — explicit confirmations)
-- =====================================================================
CREATE TABLE IF NOT EXISTS activities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    category    TEXT    NOT NULL CHECK(category IN (
                    'meal','exercise','health','rest','social','cognitive','other'
                )),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS routine_template (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id     INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    day_of_week     INTEGER NOT NULL CHECK(day_of_week BETWEEN 0 AND 6),
    expected_minute INTEGER NOT NULL CHECK(expected_minute BETWEEN 0 AND 1439),
    tolerance_min   INTEGER NOT NULL DEFAULT 30,
    active          INTEGER NOT NULL DEFAULT 1,
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(activity_id, day_of_week)
);

CREATE TABLE IF NOT EXISTS activity_prompts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_id       INTEGER NOT NULL REFERENCES activities(id),
    prompted_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    expected_minute   INTEGER NOT NULL,
    parent_prompt_id  INTEGER REFERENCES activity_prompts(id),
    utterance_id      INTEGER REFERENCES utterance_queue(id)
);
CREATE INDEX IF NOT EXISTS idx_activity_prompts_at
    ON activity_prompts(prompted_at);
CREATE INDEX IF NOT EXISTS idx_activity_prompts_activity
    ON activity_prompts(activity_id, prompted_at);

CREATE TABLE IF NOT EXISTS activity_responses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_id       INTEGER NOT NULL UNIQUE REFERENCES activity_prompts(id),
    responded_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    status          TEXT    NOT NULL CHECK(status IN (
                        'confirmed','skipped','deferred','no_response'
                    )),
    sentiment       TEXT    CHECK(sentiment IS NULL OR sentiment IN (
                        'positive','neutral','low'
                    )),
    deferred_until  TEXT,
    raw_reply       TEXT
);
"""

PRESET_ACTIVITIES = [
    ("wake up",    "rest"),
    ("breakfast",  "meal"),
    ("medication", "health"),
    ("walk",       "exercise"),
    ("lunch",      "meal"),
    ("dinner",     "meal"),
    ("bedtime",    "rest"),
    ("chess",      "cognitive"),
    ("read",       "cognitive"),
    ("call",       "social"),
]


def init():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.executemany(
        "INSERT OR IGNORE INTO activities (name, category) VALUES (?, ?)",
        PRESET_ACTIVITIES,
    )
    conn.execute("INSERT OR IGNORE INTO wellbeing_state (id) VALUES (1)")
    conn.commit()
    conn.close()
    print(f"✓ {DB_PATH} ready ({len(PRESET_ACTIVITIES)} activities preloaded)")


if __name__ == "__main__":
    init()