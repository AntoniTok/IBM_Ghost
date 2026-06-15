"""
scheduler.py — Granite Ghost schedule tracking engine.

Long-lived process. Ticks every TICK_SECONDS, asking:
  1.  Is anything time-triggered due?       (check_scheduled)
  1b. Is any routine activity overdue?      (check_activities)
  2.  Is anything reactive worth speaking?  (check_reactive)
  3.  Is the user OK?                       (check_wellbeing)
  +   Update routine baseline               (update_routine_baseline)
  +   Clean up expired utterances            (cleanup_expired)

Each question produces zero or more rows in utterance_queue. The
scheduler never speaks, never calls Granite — it only decides.

Run with:  python scheduler.py
Stop with: Ctrl-C
"""

import json
import logging
import signal
import sys
import time
from datetime import datetime, timedelta, timezone

from croniter import croniter

from db import get_db

# ---------------------------------------------------------------------------
# Config — tune these to taste
# ---------------------------------------------------------------------------

TICK_SECONDS = 30

# Auto-detect local timezone from system (handles GMT/BST automatically)
LOCAL_TZ = datetime.now().astimezone().tzinfo

USER_NAME = "Margaret"

MIN_SAMPLES_FOR_BASELINE   = 14
EXPECTED_ACTIVE_THRESHOLD  = 0.3
CHECK_IN_AFTER_HOURS       = 2
ESCALATE_AFTER_HOURS       = 5
ALERT_COOLDOWN_HOURS       = 6

REACTIVE_LOOKBACK_HOURS    = 6
USER_PRESENT_WINDOW_SECONDS = 120
BASELINE_EVENTS_PER_HOUR    = 20

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("scheduler")


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def utcnow():
    return datetime.now(timezone.utc)

def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

def parse_iso(s):
    if s is None:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

def to_local(dt_utc):
    return dt_utc.astimezone(LOCAL_TZ)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_running = True

def _shutdown(signum, frame):
    global _running
    log.info("shutdown signal received, finishing current tick")
    _running = False

signal.signal(signal.SIGINT,  _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


_tick_count = 0


def main():
    global _tick_count
    db = get_db()
    log.info("scheduler started — tick=%ss", TICK_SECONDS)
    while _running:
        _tick_count += 1
        try:
            tick(db, utcnow())
        except Exception:
            log.exception("tick #%d failed", _tick_count)
        time.sleep(TICK_SECONDS)
    log.info("scheduler stopped after %d ticks", _tick_count)
    db.close()


def tick(db, now):
    log.info("tick #%d  %s", _tick_count, iso(now))
    check_scheduled(db, now)
    check_activities(db, now)
    check_reactive(db, now)
    check_wellbeing(db, now)
    update_routine_baseline(db, now)
    cleanup_expired(db, now)
    mark_unresponded_expired(db, now)
    log_queue_depth(db)


# ===========================================================================
# QUESTION 1 — time-triggered events
# ===========================================================================

def check_scheduled(db, now):
    rows = db.execute("SELECT * FROM scheduled_events WHERE active = 1").fetchall()
    for row in rows:
        if not is_due(row, now):
            continue
        if already_fired_this_period(row, now):
            continue
        try:
            db.execute("BEGIN")
            dispatch_scheduled(db, row, now)
            db.execute(
                "UPDATE scheduled_events SET last_fired = ? WHERE id = ?",
                (iso(now), row["id"]),
            )
            if row["one_off_at"]:
                db.execute(
                    "UPDATE scheduled_events SET active = 0 WHERE id = ?",
                    (row["id"],),
                )
            db.execute("COMMIT")
            log.info("fired scheduled_event id=%s kind=%s title=%r",
                     row["id"], row["kind"], row["title"])
        except Exception:
            db.execute("ROLLBACK")
            log.exception("failed to dispatch scheduled_event id=%s", row["id"])


def is_due(row, now):
    if row["one_off_at"]:
        target = parse_iso(row["one_off_at"])
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return now >= target

    if row["cron_expr"]:
        local_now = to_local(now)
        prev_fire_local = croniter(row["cron_expr"], local_now).get_prev(datetime)
        if prev_fire_local.tzinfo is None:
            prev_fire_local = prev_fire_local.replace(tzinfo=LOCAL_TZ)
        prev_fire_utc = prev_fire_local.astimezone(timezone.utc)
        return (now - prev_fire_utc).total_seconds() < TICK_SECONDS * 2

    return False


def already_fired_this_period(row, now):
    if not row["last_fired"]:
        return False
    last = parse_iso(row["last_fired"])

    if row["one_off_at"]:
        return True

    local_now = to_local(now)
    prev_fire_local = croniter(row["cron_expr"], local_now).get_prev(datetime)
    if prev_fire_local.tzinfo is None:
        prev_fire_local = prev_fire_local.replace(tzinfo=LOCAL_TZ)
    prev_fire_utc = prev_fire_local.astimezone(timezone.utc)
    return last >= prev_fire_utc


def dispatch_scheduled(db, event, now):
    kind = event["kind"]
    if   kind == "briefing":    enqueue_briefing(db, now)
    elif kind == "medication":  enqueue_medication(db, event, now)
    elif kind == "appointment": enqueue_appointment(db, event, now)
    elif kind == "check_in":    enqueue_check_in(db, now)
    elif kind == "custom":      enqueue_custom(db, event, now)
    else: log.warning("unknown scheduled kind: %s", kind)


def enqueue_utterance(db, *, deliver_after, expires_at, priority,
                       template_name, context_query, source_event_id=None):
    cur = db.execute("""
        INSERT INTO utterance_queue
          (deliver_after, expires_at, priority, template_name,
           context_query, source_event_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        iso(deliver_after),
        iso(expires_at) if expires_at else None,
        priority,
        template_name,
        json.dumps(context_query),
        source_event_id,
    ))
    return cur.lastrowid


def enqueue_briefing(db, now):
    enqueue_utterance(
        db,
        deliver_after=now,
        expires_at=now + timedelta(hours=2),
        priority=3,
        template_name="morning_briefing.txt",
        context_query={
            "sms_since": "12h",
            "news_since": "12h",
            "weather": "latest",
            "user_name": True,
            "time_of_day": time_of_day(now),
        },
    )


def enqueue_medication(db, event, now):
    enqueue_utterance(
        db,
        deliver_after=now,
        expires_at=now + timedelta(hours=6),
        priority=1,
        template_name="medication_reminder.txt",
        context_query={
            "medication_name": event["title"],
            "time_of_day": time_of_day(now),
            "user_name": True,
        },
        source_event_id=event["id"],
    )


def enqueue_appointment(db, event, now):
    enqueue_utterance(
        db,
        deliver_after=now,
        expires_at=now + timedelta(hours=1),
        priority=2,
        template_name="appointment_reminder.txt",
        context_query={"title": event["title"], "user_name": True},
        source_event_id=event["id"],
    )


def enqueue_check_in(db, now):
    enqueue_utterance(
        db,
        deliver_after=now,
        expires_at=now + timedelta(minutes=30),
        priority=2,
        template_name="wellbeing_check_in.txt",
        context_query={"user_name": True, "time_of_day": time_of_day(now)},
    )
    db.execute("""
        UPDATE wellbeing_state
           SET last_check_in_at = ?,
               consecutive_misses = consecutive_misses + 1,
               updated_at = ?
         WHERE id = 1
    """, (iso(now), iso(now)))


def enqueue_custom(db, event, now):
    enqueue_utterance(
        db,
        deliver_after=now,
        expires_at=now + timedelta(hours=1),
        priority=5,
        template_name="custom.txt",
        context_query={"title": event["title"], "user_name": True},
        source_event_id=event["id"],
    )


# ===========================================================================
# QUESTION 1b — routine activity prompting
# ===========================================================================

def check_activities(db, now):
    """Are any routine activities due for prompting?"""
    local_now = to_local(now)
    day = local_now.weekday()
    current_minute = local_now.hour * 60 + local_now.minute

    templates = db.execute("""
        SELECT rt.*, a.name AS activity_name
          FROM routine_template rt
          JOIN activities a ON a.id = rt.activity_id
         WHERE rt.active = 1 AND rt.day_of_week = ?
    """, (day,)).fetchall()

    for t in templates:
        diff = current_minute - t["expected_minute"]
        if diff < 0 or diff > t["tolerance_min"]:
            continue
        if already_prompted_today(db, t, now):
            continue
        enqueue_activity_prompt(db, t, now)

    check_deferred(db, now)


def already_prompted_today(db, template, now):
    """Has this activity already been prompted today (excluding re-prompts)?"""
    today_start = to_local(now).replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start.astimezone(timezone.utc)
    row = db.execute("""
        SELECT 1 FROM activity_prompts
         WHERE activity_id = ? AND prompted_at >= ?
           AND parent_prompt_id IS NULL
         LIMIT 1
    """, (template["activity_id"], iso(today_start_utc))).fetchone()
    return row is not None


def enqueue_activity_prompt(db, template, now):
    """Create an activity prompt + matching utterance queue entry."""
    db.execute("BEGIN")
    try:
        utt_id = enqueue_utterance(
            db,
            deliver_after=now,
            expires_at=now + timedelta(minutes=template["tolerance_min"]),
            priority=4,
            template_name="activity_prompt.txt",
            context_query={
                "activity_name": template["activity_name"],
                "user_name": True,
                "time_of_day": time_of_day(now),
            },
        )
        db.execute("""
            INSERT INTO activity_prompts (activity_id, expected_minute, utterance_id)
            VALUES (?, ?, ?)
        """, (template["activity_id"], template["expected_minute"], utt_id))
        db.execute("COMMIT")
        log.info("prompted activity %r (template id=%s)",
                 template["activity_name"], template["id"])
    except Exception:
        db.execute("ROLLBACK")
        raise


def check_deferred(db, now):
    """Re-prompt activities that were deferred and are now due."""
    rows = db.execute("""
        SELECT ap.id AS prompt_id, ap.activity_id, ap.expected_minute,
               a.name AS activity_name
          FROM activity_prompts ap
          JOIN activity_responses ar ON ar.prompt_id = ap.id
          JOIN activities a ON a.id = ap.activity_id
         WHERE ar.status = 'deferred'
           AND ar.deferred_until IS NOT NULL
           AND ar.deferred_until <= ?
           AND NOT EXISTS (
               SELECT 1 FROM activity_prompts child
                WHERE child.parent_prompt_id = ap.id
           )
    """, (iso(now),)).fetchall()

    for r in rows:
        db.execute("BEGIN")
        try:
            utt_id = enqueue_utterance(
                db,
                deliver_after=now,
                expires_at=now + timedelta(minutes=30),
                priority=4,
                template_name="activity_prompt.txt",
                context_query={
                    "activity_name": r["activity_name"],
                    "user_name": True,
                    "time_of_day": time_of_day(now),
                    "is_followup": True,
                },
            )
            db.execute("""
                INSERT INTO activity_prompts
                    (activity_id, expected_minute, parent_prompt_id, utterance_id)
                VALUES (?, ?, ?, ?)
            """, (r["activity_id"], r["expected_minute"], r["prompt_id"], utt_id))
            db.execute("COMMIT")
            log.info("re-prompted deferred activity %r (parent prompt=%s)",
                     r["activity_name"], r["prompt_id"])
        except Exception:
            db.execute("ROLLBACK")
            log.exception("failed to re-prompt deferred prompt=%s", r["prompt_id"])


# ===========================================================================
# QUESTION 2 — reactive events
# ===========================================================================

def check_reactive(db, now):
    cutoff = now - timedelta(hours=REACTIVE_LOOKBACK_HOURS)
    rows = db.execute("""
        SELECT * FROM events
         WHERE consumed = 0 AND ts >= ?
         ORDER BY ts
    """, (iso(cutoff),)).fetchall()

    if not rows:
        return

    by_source = {}
    for r in rows:
        by_source.setdefault(r["source"], []).append(r)

    sms = by_source.get("sms", [])
    if sms and user_recently_present(db, now):
        enqueue_sms_summary(db, sms, now)
        mark_consumed(db, [r["id"] for r in sms])


def enqueue_sms_summary(db, sms_events, now):
    enqueue_utterance(
        db,
        deliver_after=now,
        expires_at=now + timedelta(hours=1),
        priority=4,
        template_name="sms_summary.txt",
        context_query={
            "sms_event_ids": [r["id"] for r in sms_events],
            "user_name": True,
            "time_context": "just now",
        },
    )


def user_recently_present(db, now):
    row = db.execute("""
        SELECT ts FROM events
         WHERE source = 'pir'
         ORDER BY ts DESC LIMIT 1
    """).fetchone()
    if not row:
        return False
    last_pir = parse_iso(row["ts"])
    return (now - last_pir).total_seconds() < USER_PRESENT_WINDOW_SECONDS


def mark_consumed(db, event_ids):
    if not event_ids:
        return
    placeholders = ",".join("?" * len(event_ids))
    db.execute(
        f"UPDATE events SET consumed = 1 WHERE id IN ({placeholders})",
        event_ids,
    )


# ===========================================================================
# QUESTION 3 — wellbeing
# ===========================================================================

def check_wellbeing(db, now):
    state = db.execute("SELECT * FROM wellbeing_state WHERE id = 1").fetchone()
    if not state:
        return

    # Reset consecutive misses if user interacted since the last check-in
    if (state["last_interaction_at"] and state["last_check_in_at"]
            and state["last_interaction_at"] > state["last_check_in_at"]):
        db.execute("""
            UPDATE wellbeing_state
               SET consecutive_misses = 0, updated_at = ?
             WHERE id = 1
        """, (iso(now),))

    local_now = to_local(now)
    routine = db.execute("""
        SELECT activity_score, sample_count FROM routine
         WHERE day_of_week = ? AND hour = ?
    """, (local_now.weekday(), local_now.hour)).fetchone()

    if not routine or routine["sample_count"] < MIN_SAMPLES_FOR_BASELINE:
        return

    if routine["activity_score"] <= EXPECTED_ACTIVE_THRESHOLD:
        return  # quiet hour by design — user normally inactive

    last_interaction = parse_iso(state["last_interaction_at"])
    hours_silent = ((now - last_interaction).total_seconds() / 3600
                    if last_interaction else 999)

    if hours_silent > CHECK_IN_AFTER_HOURS and not check_in_pending(db, now):
        log.info("wellbeing: silent %.1fh during expected-active hour, check-in",
                 hours_silent)
        enqueue_check_in(db, now)
        return

    if (hours_silent > ESCALATE_AFTER_HOURS
            and state["consecutive_misses"] >= 2
            and not alerted_recently(state, now)):
        log.warning("wellbeing: escalating — %.1fh silent, %d missed",
                    hours_silent, state["consecutive_misses"])
        send_carer_alert(db, now)
        db.execute(
            "UPDATE wellbeing_state SET alert_sent_at = ?, updated_at = ? WHERE id = 1",
            (iso(now), iso(now)),
        )


def check_in_pending(db, now):
    row = db.execute("""
        SELECT 1 FROM utterance_queue
         WHERE template_name = 'wellbeing_check_in.txt'
           AND delivered_at IS NULL
           AND (expires_at IS NULL OR expires_at > ?)
         LIMIT 1
    """, (iso(now),)).fetchone()
    return row is not None


def alerted_recently(state, now):
    if not state["alert_sent_at"]:
        return False
    last = parse_iso(state["alert_sent_at"])
    return (now - last).total_seconds() < ALERT_COOLDOWN_HOURS * 3600


def send_carer_alert(db, now):
    """Stub. Replace the TODO with your SMS API call."""
    payload = {
        "to": "carer",
        "body": f"No interaction from {USER_NAME} for several hours. "
                f"You may want to check in.",
        "sent_at": iso(now),
    }
    db.execute(
        "INSERT INTO events (source, payload, consumed) VALUES (?, ?, 1)",
        ("interaction", json.dumps({"kind": "carer_alert", **payload})),
    )
    log.warning("carer alert dispatched: %s", payload)
    # TODO: sms_client.send(to=CARER_NUMBER, body=payload["body"])


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def time_of_day(dt_utc):
    h = to_local(dt_utc).hour
    if h < 5:   return "night"
    if h < 12:  return "morning"
    if h < 17:  return "afternoon"
    if h < 21:  return "evening"
    return "night"


def update_routine_baseline(db, now):
    """Update routine table with observed sensor activity for the previous hour."""
    local_now = to_local(now)
    prev_hour = local_now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    day, hour = prev_hour.weekday(), prev_hour.hour

    # Skip if already updated this hour
    existing = db.execute("""
        SELECT last_updated FROM routine WHERE day_of_week = ? AND hour = ?
    """, (day, hour)).fetchone()
    if existing and existing["last_updated"]:
        last = parse_iso(existing["last_updated"])
        if last and (now - last).total_seconds() < 3600:
            return

    prev_hour_utc = prev_hour.astimezone(timezone.utc)
    end_utc = prev_hour_utc + timedelta(hours=1)

    count = db.execute("""
        SELECT COUNT(*) FROM events
         WHERE source IN ('pir', 'mic') AND ts >= ? AND ts < ?
    """, (iso(prev_hour_utc), iso(end_utc))).fetchone()[0]

    score = min(count / BASELINE_EVENTS_PER_HOUR, 1.0)

    db.execute("""
        INSERT INTO routine (day_of_week, hour, activity_score, sample_count, last_updated)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(day_of_week, hour) DO UPDATE SET
            activity_score = (activity_score * sample_count + excluded.activity_score)
                             / (sample_count + 1),
            sample_count = sample_count + 1,
            last_updated = excluded.last_updated
    """, (day, hour, score, iso(now)))
    log.info("baseline: day=%d hour=%02d score=%.2f (%d sensor events)",
             day, hour, score, count)


def cleanup_expired(db, now):
    """Mark expired undelivered utterances so they stop cluttering the queue."""
    result = db.execute("""
        UPDATE utterance_queue
           SET delivered_at = 'expired'
         WHERE delivered_at IS NULL
           AND expires_at IS NOT NULL
           AND expires_at < ?
    """, (iso(now),))
    if result.rowcount:
        log.info("expired %d undelivered utterances", result.rowcount)


def mark_unresponded_expired(db, _now):
    """Persist 'no_response' rows for activity prompts whose utterance expired.

    Without this, "missed" is only ever inferred at API read-time. With it,
    the day-summary queries have a definitive answer that survives a clock
    rollover — tomorrow's dashboard knows yesterday's lunch went unanswered.
    activity_responses.prompt_id is UNIQUE, so this is idempotent.
    """
    result = db.execute("""
        INSERT INTO activity_responses (prompt_id, status)
        SELECT ap.id, 'no_response'
          FROM activity_prompts ap
          JOIN utterance_queue uq ON uq.id = ap.utterance_id
         WHERE uq.delivered_at = 'expired'
           AND NOT EXISTS (
               SELECT 1 FROM activity_responses ar WHERE ar.prompt_id = ap.id
           )
    """)
    if result.rowcount:
        log.info("recorded %d no_response rows for expired prompts",
                 result.rowcount)


def log_queue_depth(db):
    """Log how many utterances are waiting for the orchestrator."""
    row = db.execute("""
        SELECT COUNT(*) AS n FROM utterance_queue WHERE delivered_at IS NULL
    """).fetchone()
    if row["n"] > 0:
        log.info("utterance queue: %d pending", row["n"])


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)