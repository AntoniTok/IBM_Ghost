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
    return conn

def get_activity_status(expected_time: str, actual_time: Optional[str]) -> str:
    """Determine activity status"""
    if actual_time:
        return "completed"
    
    # Check if expected time has passed
    now = datetime.now().time()
    expected = datetime.strptime(expected_time, "%H:%M").time()
    
    if now > expected:
        # More than 2 hours late = missed
        time_diff = datetime.combine(date.today(), now) - datetime.combine(date.today(), expected)
        if time_diff > timedelta(hours=2):
            return "missed"
    
    return "pending"

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
    """Get all activities"""
    conn = get_db()
    cursor = conn.execute("""
        SELECT a.id, a.name, a.category, 
               rt.expected_time,
               r.actual_time,
               r.responded_at
        FROM activities a
        LEFT JOIN routine_template rt ON a.id = rt.activity_id
        LEFT JOIN (
            SELECT p.activity_id, r.actual_time, r.responded_at
            FROM responses r
            JOIN prompts p ON r.prompt_id = p.id
            WHERE date(r.responded_at) = date('now')
            ORDER BY r.responded_at DESC
        ) r ON a.id = r.activity_id
        ORDER BY rt.expected_time
    """)
    
    activities = []
    for row in cursor.fetchall():
        activity = Activity(
            id=row['id'],
            name=row['name'],
            category=row['category'],
            expected_time=row['expected_time'],
            time=row['actual_time'],
            status=get_activity_status(row['expected_time'] or "00:00", row['actual_time'])
        )
        activities.append(activity)
    
    conn.close()
    return activities

@app.get("/api/activities/date/{activity_date}", response_model=List[Activity])
def get_activities_by_date(activity_date: str):
    """Get activities for a specific date"""
    conn = get_db()
    cursor = conn.execute("""
        SELECT a.id, a.name, a.category, 
               rt.expected_time,
               r.actual_time,
               r.responded_at
        FROM activities a
        LEFT JOIN routine_template rt ON a.id = rt.activity_id
        LEFT JOIN (
            SELECT p.activity_id, r.actual_time, r.responded_at
            FROM responses r
            JOIN prompts p ON r.prompt_id = p.id
            WHERE date(r.responded_at) = ?
            ORDER BY r.responded_at DESC
        ) r ON a.id = r.activity_id
        ORDER BY rt.expected_time
    """, (activity_date,))
    
    activities = []
    for row in cursor.fetchall():
        activity = Activity(
            id=row['id'],
            name=row['name'],
            category=row['category'],
            expected_time=row['expected_time'],
            time=row['actual_time'],
            status=get_activity_status(row['expected_time'] or "00:00", row['actual_time'])
        )
        activities.append(activity)
    
    conn.close()
    return activities

@app.post("/api/activities/log")
def log_activity(activity: dict):
    """Log a manual activity (creates custom activity if needed)"""
    conn = get_db()
    
    try:
        # Check if activity exists
        cursor = conn.execute("SELECT id FROM activities WHERE name = ?", (activity['activity'],))
        row = cursor.fetchone()
        
        if not row:
            # Create custom activity if it doesn't exist
            category = activity.get('category', 'other')
            conn.execute("""
                INSERT INTO activities (name, category)
                VALUES (?, ?)
            """, (activity['activity'], category))
            activity_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            print(f"Created new custom activity: {activity['activity']} ({category})")
        else:
            activity_id = row['id']
        
        # Create prompt
        conn.execute("""
            INSERT INTO prompts (activity_id, day_type, prompted_at, expected_time)
            VALUES (?, 'weekday', datetime('now'), '00:00')
        """, (activity_id,))
        
        prompt_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        
        # Create response
        conn.execute("""
            INSERT INTO responses (prompt_id, responded_at, confirmed, actual_time)
            VALUES (?, datetime('now'), 1, ?)
        """, (prompt_id, activity.get('time', datetime.now().strftime("%H:%M"))))
        
        conn.commit()
        
        return {
            "status": "success",
            "message": "Activity logged",
            "activity_id": activity_id,
            "is_new": row is None
        }
        
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to log activity: {str(e)}")
    finally:
        conn.close()
@app.delete("/api/activities/{response_id}")
def delete_activity(response_id: int):
    """Delete an activity response"""
    conn = get_db()
    
    try:
        # Check if response exists
        cursor = conn.execute("SELECT id FROM responses WHERE id = ?", (response_id,))
        row = cursor.fetchone()
        
        if not row:
            raise HTTPException(status_code=404, detail="Activity not found")
        
        # Delete the response
        conn.execute("DELETE FROM responses WHERE id = ?", (response_id,))
        conn.commit()
        
        return {
            "status": "success",
            "message": "Activity deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to delete activity: {str(e)}")
    finally:
        conn.close()


# ===== Alert Endpoints =====

@app.get("/api/alerts", response_model=List[Alert])
def get_alerts():
    """Get all alerts (mock data for now)"""
    # In production, this would query a real alerts table
    alerts = [
        Alert(
            id=1,
            activity="medication",
            expected_time="09:00",
            actual_time=None,
            severity="warning",
            message="Medication time passed without confirmation",
            timestamp=(datetime.now() - timedelta(hours=1)).isoformat(),
            resolved=False
        ),
        Alert(
            id=2,
            activity="breakfast",
            expected_time="08:00",
            actual_time=None,
            severity="critical",
            message="No activity detected for 2 hours past expected breakfast time",
            timestamp=(datetime.now() - timedelta(hours=2)).isoformat(),
            resolved=False
        )
    ]
    return alerts

@app.get("/api/alerts/active", response_model=List[Alert])
def get_active_alerts():
    """Get active (unresolved) alerts"""
    all_alerts = get_alerts()
    return [alert for alert in all_alerts if not alert.resolved]

@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge_alert(alert_id: int):
    """Acknowledge an alert"""
    # In production, update database
    return {"status": "success", "message": f"Alert {alert_id} acknowledged"}

@app.post("/api/alerts/{alert_id}/false-alarm")
def mark_false_alarm(alert_id: int):
    """Mark alert as false alarm"""
    # In production, update database
    return {"status": "success", "message": f"Alert {alert_id} marked as false alarm"}

# ===== Statistics Endpoints =====

@app.get("/api/statistics/dashboard", response_model=Statistics)
def get_dashboard_statistics():
    """Get dashboard statistics"""
    conn = get_db()
    
    # Count today's activities
    cursor = conn.execute("""
        SELECT COUNT(*) as count
        FROM responses r
        JOIN prompts p ON r.prompt_id = p.id
        WHERE date(r.responded_at) = date('now')
        AND r.confirmed = 1
    """)
    activities_today = cursor.fetchone()['count']
    
    # Get last activity
    cursor = conn.execute("""
        SELECT a.name, r.actual_time
        FROM responses r
        JOIN prompts p ON r.prompt_id = p.id
        JOIN activities a ON p.activity_id = a.id
        WHERE date(r.responded_at) = date('now')
        ORDER BY r.responded_at DESC
        LIMIT 1
    """)
    last_activity_row = cursor.fetchone()
    
    conn.close()
    
    # Calculate routine score (mock for now)
    routine_score = min(100, activities_today * 25)
    
    stats = Statistics(
        activities_today=activities_today,
        active_alerts=len(get_active_alerts()),
        routine_score=routine_score,
        last_activity=last_activity_row['actual_time'] if last_activity_row else None,
        last_activity_name=last_activity_row['name'] if last_activity_row else None
    )
    
    return stats

@app.get("/api/statistics/patterns")
def get_patterns():
    """Get activity patterns (mock data)"""
    return {
        "wake_up": {"mean": "07:15", "std_dev": 30},
        "breakfast": {"mean": "08:30", "std_dev": 45},
        "medication": {"mean": "09:00", "std_dev": 15},
        "lunch": {"mean": "12:30", "std_dev": 60}
    }

# ===== Routine Endpoints =====

@app.get("/api/routine/template")
def get_routine_template():
    """Get routine template"""
    conn = get_db()
    cursor = conn.execute("""
        SELECT a.name, rt.expected_time, rt.day_type
        FROM routine_template rt
        JOIN activities a ON rt.activity_id = a.id
        ORDER BY rt.expected_time
    """)
    
    templates = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return templates

@app.post("/api/routine/template")
def update_routine_template(data: dict):
    """Update routine template"""
    conn = get_db()
    conn.execute("""
        UPDATE routine_template
        SET expected_time = ?, updated_at = datetime('now')
        WHERE activity_id = ?
    """, (data['expected_time'], data['activity_id']))
    
    conn.commit()
    conn.close()
    
    return {"status": "success", "message": "Routine template updated"}

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
    print("Starting The Sentinel API...")
    print("Web App: http://localhost:5000/app/index.html")
    print("API Docs: http://localhost:5000/docs")
    
    uvicorn.run(app, host="0.0.0.0", port=5000)

# Made with Bob
