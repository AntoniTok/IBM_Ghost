"""
seed.py — populate ghost.db with test data so the scheduler has
something to work with. Run once after init_db.py.

Re-running creates duplicates. For a clean slate:
    python init_db.py              # recreates schema
    python seed.py                 # re-seed
"""

from datetime import datetime, timezone, timedelta
from db import get_db

db = get_db()

# ----- scheduled events -----------------------------------------------------

db.execute("""
    INSERT INTO scheduled_events (kind, title, cron_expr, priority)
    VALUES ('briefing', 'Morning briefing', '0 8 * * *', 3)
""")

db.execute("""
    INSERT INTO scheduled_events (kind, title, cron_expr, priority)
    VALUES ('medication', 'Blood pressure tablet', '0 9 * * *', 1)
""")

soon = (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime(
    "%Y-%m-%dT%H:%M:%S.%fZ"
)
db.execute("""
    INSERT INTO scheduled_events (kind, title, one_off_at, priority)
    VALUES ('appointment', 'Test appointment', ?, 2)
""", (soon,))

# ----- routine templates (activity prompting) --------------------------------
# expected_minute = minutes from midnight.  480 = 08:00, 540 = 09:00, etc.
# These use the preset activities created by init_db.py.

TEMPLATES = [
    # (activity_name, day_of_week, expected_minute, tolerance_min)
    ("wake up",    None, 7 * 60,       30),   # 07:00 every day
    ("breakfast",  None, 8 * 60,       30),   # 08:00
    ("medication", None, 9 * 60,       15),   # 09:00, tighter tolerance
    ("walk",       None, 10 * 60 + 30, 45),   # 10:30
    ("lunch",      None, 12 * 60 + 30, 30),   # 12:30
    ("dinner",     None, 18 * 60,      30),   # 18:00
    ("bedtime",    None, 22 * 60,      30),   # 22:00
]

for name, day, minute, tolerance in TEMPLATES:
    # Look up activity id
    row = db.execute(
        "SELECT id FROM activities WHERE name = ?", (name,)
    ).fetchone()
    if not row:
        print(f"  ⚠ activity {name!r} not found, skipping")
        continue
    activity_id = row["id"]

    # If day is None, insert for every day of the week (0-6)
    days = [day] if day is not None else list(range(7))
    for d in days:
        db.execute("""
            INSERT OR IGNORE INTO routine_template
                (activity_id, day_of_week, expected_minute, tolerance_min)
            VALUES (?, ?, ?, ?)
        """, (activity_id, d, minute, tolerance))

db.close()

# ----- summary ---------------------------------------------------------------

print("✓ seeded test data")
print(f"  - 2 recurring scheduled events (briefing 8am, medication 9am)")
print(f"  - 1 one-off appointment at {soon} (≈ 2 min from now)")
print(f"  - {len(TEMPLATES)} activity templates × 7 days = {len(TEMPLATES) * 7} routine_template rows")