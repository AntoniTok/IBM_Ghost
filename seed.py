"""
seed.py — drop a few scheduled events into the DB so the scheduler has
something to do. Run once after init_db.py.

Re-running creates duplicates. If you want a clean slate:
    sqlite3 ghost.db "DELETE FROM scheduled_events"
"""

from datetime import datetime, timezone, timedelta
from db import get_db

db = get_db()

# Daily 8am morning briefing
db.execute("""
    INSERT INTO scheduled_events (kind, title, cron_expr, priority)
    VALUES ('briefing', 'Morning briefing', '0 8 * * *', 3)
""")

# Daily 9am medication
db.execute("""
    INSERT INTO scheduled_events (kind, title, cron_expr, priority)
    VALUES ('medication', 'Blood pressure tablet', '0 9 * * *', 1)
""")

# One-off appointment 2 minutes from now — for fast feedback when testing
soon = (datetime.now(timezone.utc) + timedelta(minutes=2)).strftime(
    "%Y-%m-%dT%H:%M:%S.%fZ"
)
db.execute("""
    INSERT INTO scheduled_events (kind, title, one_off_at, priority)
    VALUES ('appointment', 'Test appointment', ?, 2)
""", (soon,))

db.close()
print("✓ seeded 3 scheduled events")
print(f"  - briefing daily at 8am")
print(f"  - medication daily at 9am")
print(f"  - one-off appointment at {soon} (≈ 2 min from now)")