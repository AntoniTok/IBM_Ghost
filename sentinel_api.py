"""
Sentinel API - Backend for The Sentinel Carer Dashboard
Provides REST API endpoints for activity monitoring and alerts
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date, timedelta
import json
import sqlite3
import uvicorn

# Initialize FastAPI app
app = FastAPI(
    title="The Sentinel API",
    description="Passive wellbeing monitoring for elderly care",
    version="1.0.0"
)

# Enable CORS for web app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files (web app)
app.mount("/app", StaticFiles(directory="web-app", html=True), name="web-app")

# Database path
DB_PATH = "ghost.db"

# ===== Pydantic Models =====

class Activity(BaseModel):
    id: Optional[int] = None
    name: str
    category: str
    time: Optional[str] = None
    status: Optional[str] = None
    expected_time: Optional[str] = None

class Alert(BaseModel):
    id: Optional[int] = None
    activity: str
    expected_time: str
    actual_time: Optional[str] = None
    severity: str
    message: str
    timestamp: str
    resolved: bool = False

class Statistics(BaseModel):
    activities_today: int
    active_alerts: int
    routine_score: Optional[int] = None
    last_activity: Optional[str] = None
    last_activity_name: Optional[str] = None

class EmergencyRequest(BaseModel):
    alert_id: int
    message: str

# ===== Helper Functions =====

def get_db():
    """Get database connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def minute_to_hhmm(m: Optional[int]) -> Optional[str]:
    if m is None:
        return None
    return f"{m // 60:02d}:{m % 60:02d}"


def hhmm_to_minute(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def iso_to_hhmm_local(iso_ts: Optional[str]) -> Optional[str]:
    """Convert a stored ISO timestamp ('YYYY-MM-DDTHH:MM:SS[.ffffff][Z]') to local HH:MM."""
    if not iso_ts:
        return None
    ts = iso_ts.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%H:%M")


def get_activity_status(expected_time: Optional[str], actual_time: Optional[str],
                        response_status: Optional[str] = None,
                        for_date: Optional[date] = None) -> str:
    """Determine activity status for the UI: completed / missed / skipped / pending."""
    if response_status == "skipped":
        return "skipped"
    if actual_time or response_status == "confirmed":
        return "completed"
    if not expected_time:
        return "pending"

    # Only judge "missed" for today; past/future dates stay pending if no response.
    target = for_date or date.today()
    if target != date.today():
        return "pending"

    now = datetime.now().time()
    expected = datetime.strptime(expected_time, "%H:%M").time()
    if now > expected:
        delta = (datetime.combine(date.today(), now)
                 - datetime.combine(date.today(), expected))
        if delta > timedelta(hours=2):
            return "missed"
    return "pending"


def _activities_for_date(conn, target: date) -> List["Activity"]:
    """List activities + their template + the best response for a given date.

    "Best" = prefer confirmed > skipped > deferred > no_response, then earliest.
    Date comparisons use SQLite's 'localtime' modifier so a confirmation at
    23:30 local time is counted on today, not tomorrow's UTC date.
    """
    day_of_week = target.weekday()  # Monday=0, matches scheduler
    date_str = target.isoformat()

    cursor = conn.execute("""
        WITH ranked AS (
            SELECT ap.activity_id,
                   ar.id           AS response_id,
                   ar.responded_at,
                   ar.status,
                   ROW_NUMBER() OVER (
                       PARTITION BY ap.activity_id
                       ORDER BY CASE ar.status
                                  WHEN 'confirmed' THEN 0
                                  WHEN 'skipped'   THEN 1
                                  WHEN 'deferred'  THEN 2
                                  ELSE 3
                                END,
                                ar.responded_at ASC
                   ) AS rn
              FROM activity_prompts ap
              JOIN activity_responses ar ON ar.prompt_id = ap.id
             WHERE date(ar.responded_at, 'localtime') = ?
        )
        SELECT a.id              AS activity_id,
               a.name,
               a.category,
               rt.expected_minute,
               chosen.response_id,
               chosen.responded_at,
               chosen.status      AS resp_status
          FROM activities a
          LEFT JOIN routine_template rt
                 ON rt.activity_id = a.id
                AND rt.day_of_week = ?
                AND rt.active = 1
          LEFT JOIN ranked chosen
                 ON chosen.activity_id = a.id AND chosen.rn = 1
         WHERE rt.id IS NOT NULL OR chosen.activity_id IS NOT NULL
         ORDER BY rt.expected_minute IS NULL, rt.expected_minute, a.name
    """, (date_str, day_of_week))

    activities: List[Activity] = []
    for row in cursor.fetchall():
        expected_time = minute_to_hhmm(row["expected_minute"])
        actual_time = iso_to_hhmm_local(row["responded_at"])
        status = get_activity_status(expected_time, actual_time,
                                     row["resp_status"], target)
        activities.append(Activity(
            id=row["response_id"] if row["response_id"] is not None else row["activity_id"],
            name=row["name"],
            category=row["category"],
            time=actual_time,
            expected_time=expected_time,
            status=status,
        ))
    return activities

# ===== API Endpoints =====

@app.get("/")
def root():
    """Root endpoint - redirect to web app"""
    return {
        "service": "The Sentinel API",
        "version": "1.0.0",
        "web_app": "/app/index.html",
        "docs": "/docs"
    }

@app.get("/health")
def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

# ===== Activity Endpoints =====

@app.get("/api/activities", response_model=List[Activity])
def get_activities():
    """Get today's activities with their routine template + latest response."""
    conn = get_db()
    try:
        return _activities_for_date(conn, date.today())
    finally:
        conn.close()


@app.get("/api/activities/date/{activity_date}", response_model=List[Activity])
def get_activities_by_date(activity_date: str):
    """Get activities for a specific date (YYYY-MM-DD)."""
    try:
        target = date.fromisoformat(activity_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")
    conn = get_db()
    try:
        return _activities_for_date(conn, target)
    finally:
        conn.close()


@app.post("/api/activities/log")
def log_activity(activity: dict):
    """Log a manual activity confirmation.

    Body: {activity, time:"HH:MM", date:"YYYY-MM-DD", category?, notes?}
    Creates a synthetic activity_prompt + confirmed activity_response so the
    entry shows up in the same query path the scheduler-driven prompts use.
    """
    name = activity.get("activity")
    if not name:
        raise HTTPException(status_code=400, detail="`activity` is required")

    time_hhmm = activity.get("time") or datetime.now().strftime("%H:%M")
    date_str = activity.get("date") or date.today().isoformat()
    try:
        date.fromisoformat(date_str)
        hh, mm = time_hhmm.split(":")
        expected_minute = int(hh) * 60 + int(mm)
        responded_at = datetime.fromisoformat(f"{date_str}T{time_hhmm}:00").isoformat()
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="invalid date/time format")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT id FROM activities WHERE name = ?", (name,)
        ).fetchone()
        is_new = row is None
        if is_new:
            category = activity.get("category", "other")
            if category not in {"meal", "exercise", "health", "rest",
                                "social", "cognitive", "other"}:
                category = "other"
            conn.execute(
                "INSERT INTO activities (name, category) VALUES (?, ?)",
                (name, category),
            )
            activity_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        else:
            activity_id = row["id"]

        conn.execute("""
            INSERT INTO activity_prompts
                (activity_id, prompted_at, expected_minute)
            VALUES (?, ?, ?)
        """, (activity_id, responded_at, expected_minute))
        prompt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        raw_reply = activity.get("notes")
        conn.execute("""
            INSERT INTO activity_responses
                (prompt_id, responded_at, status, raw_reply)
            VALUES (?, ?, 'confirmed', ?)
        """, (prompt_id, responded_at, raw_reply))
        response_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Tell the scheduler's wellbeing check that someone is alive at the keyboard.
        # Resets consecutive_misses so we don't page the carer five minutes after they
        # just confirmed an activity through the web app.
        conn.execute("""
            UPDATE wellbeing_state
               SET last_interaction_at = ?,
                   consecutive_misses  = 0,
                   updated_at          = strftime('%Y-%m-%dT%H:%M:%fZ','now')
             WHERE id = 1
        """, (responded_at,))
        conn.commit()

        return {
            "status": "success",
            "message": "Activity logged",
            "activity_id": activity_id,
            "response_id": response_id,
            "is_new": is_new,
        }
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to log activity: {e}")
    finally:
        conn.close()


@app.delete("/api/activities/{response_id}")
def delete_activity(response_id: int):
    """Delete an activity_response (and its parent prompt if it was synthetic)."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT prompt_id FROM activity_responses WHERE id = ?", (response_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Activity response not found")

        prompt_id = row["prompt_id"]
        conn.execute("DELETE FROM activity_responses WHERE id = ?", (response_id,))
        # The prompt was created either by the scheduler or by /log. If no other
        # response or child prompt references it, drop the prompt too.
        orphan = conn.execute("""
            SELECT 1 FROM activity_responses WHERE prompt_id = ?
            UNION ALL
            SELECT 1 FROM activity_prompts   WHERE parent_prompt_id = ?
            LIMIT 1
        """, (prompt_id, prompt_id)).fetchone()
        if not orphan:
            conn.execute("DELETE FROM activity_prompts WHERE id = ?", (prompt_id,))
        conn.commit()
        return {"status": "success", "message": "Activity deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete activity: {e}")
    finally:
        conn.close()


# ===== Alert Endpoints =====

# Activity-derived alert ids fit in [1, 10_000); event-derived ids are
# 10_000 + events.id. Both surfaces share /api/alerts/{id}/{acknowledge|false-alarm},
# so the offset is how we route a dismissal back to the right source.
_EVENT_ALERT_OFFSET = 10_000


def _split_alert_id(alert_id: int):
    """Return (source, source_id) for the alert routing back to its origin row."""
    if alert_id >= _EVENT_ALERT_OFFSET:
        return "event", alert_id - _EVENT_ALERT_OFFSET
    return "activity", alert_id


def _derive_alerts(conn) -> List[Alert]:
    """Derive alerts from real data: overdue activities + carer-alert events.

    There is no dedicated alerts table — overdue activities are inferred from
    routine_template vs. today's activity_responses, and carer alerts come
    from the `events` log. The `alert_dismissals` table filters out anything
    the carer has acknowledged or marked as a false alarm.
    """
    alerts: List[Alert] = []
    day_of_week = date.today().weekday()
    now_minute = datetime.now().hour * 60 + datetime.now().minute

    # 1) Overdue routine activities (no confirmed response, past expected time).
    rows = conn.execute("""
        SELECT a.id AS activity_id,
               a.name,
               rt.expected_minute,
               rt.tolerance_min,
               (
                 SELECT ar.status
                   FROM activity_prompts ap
                   JOIN activity_responses ar ON ar.prompt_id = ap.id
                  WHERE ap.activity_id = a.id
                    AND date(ar.responded_at, 'localtime') = date('now','localtime')
                  ORDER BY CASE ar.status
                             WHEN 'confirmed' THEN 0
                             WHEN 'skipped'   THEN 1
                             WHEN 'deferred'  THEN 2
                             ELSE 3
                           END,
                           ar.responded_at ASC
                  LIMIT 1
               ) AS resp_status
          FROM activities a
          JOIN routine_template rt
                ON rt.activity_id = a.id
               AND rt.day_of_week = ?
               AND rt.active = 1
         WHERE NOT EXISTS (
             SELECT 1 FROM alert_dismissals ad
              WHERE ad.source    = 'activity'
                AND ad.source_id = a.id
                AND date(ad.dismissed_at,'localtime') = date('now','localtime')
         )
    """, (day_of_week,)).fetchall()

    for row in rows:
        if row["resp_status"] in ("confirmed", "skipped"):
            continue
        minutes_late = now_minute - row["expected_minute"]
        if minutes_late < row["tolerance_min"]:
            continue
        expected_hhmm = minute_to_hhmm(row["expected_minute"])
        if minutes_late > 120:
            severity = "critical"
            message = (f"No confirmation of '{row['name']}' "
                       f"{minutes_late // 60}h{minutes_late % 60:02d} past expected "
                       f"{expected_hhmm}.")
        else:
            severity = "warning"
            message = (f"'{row['name']}' expected at {expected_hhmm} — "
                       f"{minutes_late} min overdue.")
        alerts.append(Alert(
            id=row["activity_id"],
            activity=row["name"],
            expected_time=expected_hhmm,
            actual_time=None,
            severity=severity,
            message=message,
            timestamp=datetime.now().isoformat(),
            resolved=False,
        ))

    # 2) Carer-alert events written by scheduler.send_carer_alert(); dismissals
    #    here are permanent.
    carer_rows = conn.execute("""
        SELECT e.id, e.ts, e.payload
          FROM events e
         WHERE e.source = 'interaction'
           AND e.payload LIKE '%"kind": "carer_alert"%'
           AND NOT EXISTS (
               SELECT 1 FROM alert_dismissals ad
                WHERE ad.source = 'event' AND ad.source_id = e.id
           )
         ORDER BY e.ts DESC
         LIMIT 10
    """).fetchall()
    for r in carer_rows:
        try:
            payload = json.loads(r["payload"])
        except (ValueError, TypeError):
            payload = {}
        alerts.append(Alert(
            id=_EVENT_ALERT_OFFSET + r["id"],
            activity="wellbeing",
            expected_time="--:--",
            actual_time=None,
            severity="critical",
            message=payload.get("body", "Carer alert dispatched"),
            timestamp=r["ts"],
            resolved=False,
        ))

    return alerts


def _dismiss_alert(alert_id: int, status: str) -> dict:
    """Shared write path for acknowledge / false_alarm."""
    if status not in ("acknowledged", "false_alarm"):
        raise HTTPException(status_code=400, detail="invalid dismissal status")
    source, source_id = _split_alert_id(alert_id)
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO alert_dismissals (source, source_id, status)
            VALUES (?, ?, ?)
        """, (source, source_id, status))
        conn.commit()
        return {
            "status": "success",
            "message": f"Alert {alert_id} {status.replace('_', ' ')}",
            "source": source,
            "source_id": source_id,
        }
    finally:
        conn.close()


@app.get("/api/alerts", response_model=List[Alert])
def get_alerts():
    """Get all current alerts (derived live)."""
    conn = get_db()
    try:
        return _derive_alerts(conn)
    finally:
        conn.close()


@app.get("/api/alerts/active", response_model=List[Alert])
def get_active_alerts():
    """Get active (unresolved) alerts."""
    return [a for a in get_alerts() if not a.resolved]

@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int):
    """Persist an acknowledgement so the alert stops surfacing."""
    return _dismiss_alert(alert_id, "acknowledged")


@app.post("/api/alerts/{alert_id}/false-alarm")
def mark_false_alarm(alert_id: int):
    """Persist a false-alarm dismissal."""
    return _dismiss_alert(alert_id, "false_alarm")

# ===== Statistics Endpoints =====

@app.get("/api/statistics/dashboard", response_model=Statistics)
def get_dashboard_statistics():
    """Dashboard counters: today's confirmed activities, alerts, routine score."""
    conn = get_db()
    try:
        date_str = date.today().isoformat()
        day_of_week = date.today().weekday()

        activities_today = conn.execute("""
            SELECT COUNT(*) AS n
              FROM activity_responses
             WHERE status = 'confirmed'
               AND date(responded_at, 'localtime') = ?
        """, (date_str,)).fetchone()["n"]

        expected_today = conn.execute("""
            SELECT COUNT(*) AS n
              FROM routine_template
             WHERE day_of_week = ? AND active = 1
        """, (day_of_week,)).fetchone()["n"]

        last_row = conn.execute("""
            SELECT a.name, ar.responded_at
              FROM activity_responses ar
              JOIN activity_prompts ap ON ap.id = ar.prompt_id
              JOIN activities a       ON a.id  = ap.activity_id
             WHERE ar.status = 'confirmed'
               AND date(ar.responded_at, 'localtime') = ?
             ORDER BY ar.responded_at DESC
             LIMIT 1
        """, (date_str,)).fetchone()

        active_alerts = len(_derive_alerts(conn))

        if expected_today > 0:
            routine_score = min(100, round(100 * activities_today / expected_today))
        else:
            routine_score = min(100, activities_today * 25)

        return Statistics(
            activities_today=activities_today,
            active_alerts=active_alerts,
            routine_score=routine_score,
            last_activity=iso_to_hhmm_local(last_row["responded_at"]) if last_row else None,
            last_activity_name=last_row["name"] if last_row else None,
        )
    finally:
        conn.close()


@app.get("/api/statistics/patterns")
def get_patterns():
    """Derive patterns (mean / spread) from confirmed activity_responses."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT a.name,
                   ap.expected_minute,
                   ar.responded_at
              FROM activity_responses ar
              JOIN activity_prompts ap ON ap.id = ar.prompt_id
              JOIN activities       a  ON a.id  = ap.activity_id
             WHERE ar.status = 'confirmed'
        """).fetchall()
    finally:
        conn.close()

    buckets: dict = {}
    for r in rows:
        hhmm = iso_to_hhmm_local(r["responded_at"])
        if not hhmm:
            continue
        minute = hhmm_to_minute(hhmm)
        buckets.setdefault(r["name"], []).append(minute)

    out: dict = {}
    for name, minutes in buckets.items():
        n = len(minutes)
        mean = sum(minutes) / n
        var = sum((m - mean) ** 2 for m in minutes) / n if n > 1 else 0
        std_dev = round(var ** 0.5)
        out[name.replace(" ", "_")] = {
            "mean": minute_to_hhmm(round(mean)),
            "std_dev": std_dev,
            "samples": n,
        }
    return out


# ===== Routine Endpoints =====

_DAY_NAMES = ["monday", "tuesday", "wednesday", "thursday",
              "friday", "saturday", "sunday"]


@app.get("/api/routine/template")
def get_routine_template():
    """Get every active routine_template row (one per activity per day_of_week)."""
    conn = get_db()
    try:
        cursor = conn.execute("""
            SELECT rt.id,
                   rt.activity_id,
                   a.name,
                   a.category,
                   rt.day_of_week,
                   rt.expected_minute,
                   rt.tolerance_min
              FROM routine_template rt
              JOIN activities a ON a.id = rt.activity_id
             WHERE rt.active = 1
             ORDER BY rt.day_of_week, rt.expected_minute
        """).fetchall()
    finally:
        conn.close()

    return [
        {
            "id": r["id"],
            "activity_id": r["activity_id"],
            "name": r["name"],
            "category": r["category"],
            "day_of_week": r["day_of_week"],
            "day_name": _DAY_NAMES[r["day_of_week"]],
            "expected_time": minute_to_hhmm(r["expected_minute"]),
            "tolerance_min": r["tolerance_min"],
        }
        for r in cursor
    ]


@app.post("/api/routine/template")
def update_routine_template(data: dict):
    """Update expected_time (HH:MM) for an activity.

    Body: {activity_id, expected_time, day_of_week?: 0-6 or null for every day,
           tolerance_min?: int}
    """
    activity_id = data.get("activity_id")
    expected_time = data.get("expected_time")
    if activity_id is None or not expected_time:
        raise HTTPException(status_code=400,
                            detail="activity_id and expected_time are required")
    expected_minute = hhmm_to_minute(expected_time)
    if expected_minute is None or not 0 <= expected_minute <= 1439:
        raise HTTPException(status_code=400, detail="expected_time must be HH:MM")

    day = data.get("day_of_week")
    days = [day] if day is not None else list(range(7))
    tolerance = data.get("tolerance_min", 30)

    conn = get_db()
    try:
        for d in days:
            conn.execute("""
                INSERT INTO routine_template
                    (activity_id, day_of_week, expected_minute, tolerance_min)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(activity_id, day_of_week) DO UPDATE SET
                    expected_minute = excluded.expected_minute,
                    tolerance_min   = excluded.tolerance_min,
                    active          = 1,
                    updated_at      = strftime('%Y-%m-%dT%H:%M:%fZ','now')
            """, (activity_id, d, expected_minute, tolerance))
        conn.commit()
    finally:
        conn.close()

    return {"status": "success", "message": "Routine template updated",
            "days_affected": len(days)}

# ===== Emergency Endpoints =====

@app.post("/api/emergency/trigger")
def trigger_emergency(request: EmergencyRequest):
    """Trigger emergency alert"""
    # In production, this would:
    # 1. Send SMS/email to emergency contacts
    # 2. Log emergency event
    # 3. Possibly call emergency services API
    
    print(f"🚨 EMERGENCY ALERT: {request.message}")
    print(f"   Alert ID: {request.alert_id}")
    print(f"   Timestamp: {datetime.now().isoformat()}")
    
    return {
        "status": "success",
        "message": "Emergency alert sent to registered contacts",
        "timestamp": datetime.now().isoformat()
    }

# ===== Run Server =====

if __name__ == "__main__":
    import os
    port = int(os.environ.get("SENTINEL_PORT", "8000"))
    print("Starting The Sentinel API...")
    print(f"Web App: http://localhost:{port}/app/index.html")
    print(f"API Docs: http://localhost:{port}/docs")

    uvicorn.run(app, host="0.0.0.0", port=port)

# Made with Bob
