# The Sentinel - Quick Start Guide

Get The Sentinel Carer Dashboard up and running in 5 minutes!

## 🚀 Quick Start

### 🎯 Option A: View Web App Only (No Setup Required!)

**Just want to see the interface?** Open the web app directly in your browser:

1. Navigate to the `web-app` folder in your file explorer
2. Double-click `index.html` to open it in your browser
3. The app will automatically use **mock data** - no backend needed!

**What you'll see with mock data:**
- ✅ Dashboard with sample statistics
- ✅ Sample alerts (missed medication, delayed breakfast)
- ✅ Activity timeline with sample events
- ✅ All UI interactions and navigation
- ✅ Settings page

**Note:** This is perfect for demos and UI testing. To connect to real data from the Raspberry Pi, follow Option B below.

---

### 🔧 Option B: Full Setup with Backend

**Want real data and API integration?**

#### Step 1: Install Dependencies

```bash
pip install fastapi uvicorn pydantic
```

#### Step 2: Get Database Files

The database schema is maintained on the `database` branch. You need to either:

**Option A: Merge database branch**
```bash
git merge database
```

**Option B: Copy files from database branch**
```bash
git checkout database -- init_db.py ghost.db
```

Then initialize the database:
```bash
python init_db.py
```

Expected output:
```
✓ ghost.db created
✓ 4 tables created
✓ Activities preloaded
```

### Step 3: Start the API Server

```bash
python sentinel_api.py
```

Expected output:
```
🚀 Starting The Sentinel API...
📱 Web App: http://localhost:5000/app/index.html
📚 API Docs: http://localhost:5000/docs
```

### Step 4: Open the Web App

Open your browser and navigate to:
```
http://localhost:5000/app/index.html
```

### Step 5: Configure Connection

1. Click **"Settings"** in the sidebar
2. The API endpoint should already be set to `http://localhost:5000`
3. Click **"Test Connection"** - you should see "✅ Connection successful!"
4. Enable browser notifications (optional)
5. Click **"Save Connection"**

### Step 6: Explore the Dashboard

- **Dashboard**: View activity statistics and recent alerts
- **Alerts**: See all anomaly notifications
- **Timeline**: Browse activity history
- **Settings**: Configure preferences

## 📊 Testing with Sample Data

The app includes mock data for testing. You'll see:
- Sample activities (wake up, breakfast, medication, lunch)
- Sample alerts (missed medication, delayed breakfast)
- Dashboard statistics

## 🎯 Next Steps

### Add Real Activities

Use the API to log activities:

```bash
curl -X POST http://localhost:5000/api/activities/log \
  -H "Content-Type: application/json" \
  -d '{"activity": "breakfast", "time": "08:30"}'
```

### View API Documentation

Visit the interactive API docs:
```
http://localhost:5000/docs
```

### Integrate with Raspberry Pi

1. Deploy `sentinel_api.py` to your Raspberry Pi
2. Find your Pi's IP address: `hostname -I`
3. Update the web app Settings with Pi's IP: `http://192.168.1.XXX:5000`

## 🔧 Troubleshooting

### Port Already in Use

If port 5000 is busy, edit `sentinel_api.py`:
```python
uvicorn.run(app, host="0.0.0.0", port=8000)  # Change to 8000
```

Then update web app Settings to `http://localhost:8000`

### Database Not Found

Make sure you have the database files from the `database` branch:
```bash
# Get database files
git checkout database -- init_db.py

# Initialize database
python init_db.py
```

### CORS Errors

If you see CORS errors in browser console:
1. Make sure you're accessing via `http://localhost:5000/app/`
2. Not opening `index.html` directly from file system

### No Activities Showing

The database starts empty. Either:
1. Use mock data (automatic fallback)
2. Log activities via API
3. Wait for pattern learning to populate data

## 📱 Mobile Access

To access from your phone on the same network:

1. Find your computer's IP address:
   - Windows: `ipconfig`
   - Mac/Linux: `ifconfig` or `hostname -I`

2. On your phone's browser, visit:
   ```
   http://YOUR_COMPUTER_IP:5000/app/index.html
   ```

3. Add to home screen for app-like experience

## 🎨 Customization

### Change Theme Colors

Edit `web-app/css/styles.css`:
```css
:root {
    --primary: #3b82f6;  /* Change primary color */
}
```

### Add Custom Activities

Edit `init_db.py` and add to `PRESET_ACTIVITIES`:
```python
("yoga", "exercise"),
("tea", "meal"),
```

Then re-run: `python init_db.py`

## 📚 Learn More

- **Full Documentation**: See `web-app/README.md`
- **API Reference**: Visit `/docs` endpoint
- **Database Schema**: See `init_db.py`

## 🆘 Need Help?

1. Check browser console for errors (F12)
2. Check API server logs in terminal
3. Verify database exists: `ls ghost.db`
4. Test API health: `curl http://localhost:5000/health`

## ✅ Success Checklist

- [ ] Dependencies installed
- [ ] Database initialized
- [ ] API server running
- [ ] Web app accessible
- [ ] Connection test passed
- [ ] Dashboard showing data
- [ ] Notifications enabled (optional)

---

**Congratulations!** 🎉 The Sentinel is now running!

Next: Explore the dashboard, test alerts, and integrate with your Raspberry Pi.