import sqlite3
from pathlib import Path

DB_PATH = Path("ghost.db")

conn = sqlite3.connect(DB_PATH)

conn.executescript("""

    CREATE TABLE IF NOT EXISTS activities (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        category    TEXT NOT NULL CHECK(category IN (
                        'meal', 'exercise', 'health', 'rest', 'social', 'cognitive', 'other'
                    )),
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS routine_template (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id     INTEGER NOT NULL REFERENCES activities(id),
        day_type        TEXT NOT NULL CHECK(day_type IN ('weekday', 'weekend')),
        expected_time   TEXT NOT NULL,
        updated_at      TIMESTAMP NOT NULL, 
        UNIQUE(activity_id, day_type)
    );

    CREATE TABLE IF NOT EXISTS prompts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        activity_id     INTEGER NOT NULL REFERENCES activities(id),
        day_type        TEXT NOT NULL CHECK(day_type IN ('weekday', 'weekend')),
        prompted_at     TIMESTAMP NOT NULL,
        expected_time   TEXT NOT NULL,
        is_reprompt     BOOLEAN DEFAULT false
    );

    CREATE TABLE IF NOT EXISTS responses (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        prompt_id           INTEGER NOT NULL UNIQUE REFERENCES prompts(id),
        responded_at        TIMESTAMP,
        confirmed           BOOLEAN NOT NULL DEFAULT false,
        skipped             BOOLEAN NOT NULL DEFAULT false,
        deferred            BOOLEAN NOT NULL DEFAULT false,
        actual_time         TEXT,
        sentiment           TEXT CHECK(sentiment IN ('positive', 'neutral', 'low', null)),
        deferred_until      TIMESTAMP,
        deferred_completed  BOOLEAN DEFAULT false
    );

""")

# Preload activities
PRESET_ACTIVITIES = [
    ("wake up",    "rest"),
    ("breakfast",  "meal"),
    ("medication", "health"),
    ("walk",       "exercise"),
    ("lunch",      "meal"),
    ("dinner",     "meal"),
    ("bedtime",    "rest"),
    ("chess",      "cognitive"),
    ("read",      "cognitive"),
    ("call",      "social")
]

conn.executemany("""
    INSERT OR IGNORE INTO activities (name, category) VALUES (?, ?)
""", PRESET_ACTIVITIES)

conn.commit()
conn.close()

print("✓ ghost.db created")
print("✓ 4 tables created")
print("✓ Activities preloaded")