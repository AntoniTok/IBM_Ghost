# The Sentinel - Carer Dashboard Web App

A modern, responsive web application for monitoring elderly wellbeing through passive activity tracking.

## 🎯 Overview

The Sentinel Carer Dashboard provides family members and caregivers with real-time insights into their loved one's daily routines, alerts for anomalies, and tools for emergency response.

## ✨ Features

### 📊 Dashboard
- Real-time activity statistics
- Routine adherence score
- Recent alerts overview
- Today's activity summary

### 🔔 Alerts
- Anomaly notifications
- Severity levels (warning, critical)
- Alert acknowledgment
- Emergency escalation

### 📅 Timeline
- Complete activity history
- Date filtering
- Visual timeline view
- Activity status tracking

### ⚙️ Settings
- Raspberry Pi connection configuration
- Notification preferences
- Auto-refresh interval
- Browser notification permissions

## 🚀 Getting Started

### Prerequisites

- Modern web browser (Chrome, Firefox, Safari, Edge)
- Raspberry Pi running The Sentinel backend (optional for development)

### Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd IBM_Ghost
   git checkout app
   ```

2. **Open the web app:**
   ```bash
   cd web-app
   # Open index.html in your browser
   # Or use a local server:
   python -m http.server 8000
   # Then visit: http://localhost:8000
   ```

### Configuration

1. **Navigate to Settings page**
2. **Enter your Raspberry Pi API endpoint:**
   - Format: `http://192.168.1.100:5000`
   - Replace with your Pi's IP address
3. **Enable browser notifications** (optional)
4. **Set refresh interval** (default: 30 seconds)
5. **Click "Save Connection"**
6. **Click "Test Connection"** to verify

## 📱 Usage

### Dashboard

The dashboard provides an at-a-glance view of:
- **Activities Today**: Number of completed activities
- **Active Alerts**: Current unresolved alerts
- **Routine Score**: Percentage of activities completed on time
- **Last Activity**: Time of most recent activity

### Viewing Alerts

1. Click **"Alerts"** in the sidebar
2. View all alerts (active and resolved)
3. Click an alert to see details
4. Options:
   - **Acknowledge**: Mark alert as seen
   - **False Alarm**: Dismiss incorrect alert
   - **Contact Emergency**: Escalate to emergency services

### Activity Timeline

1. Click **"Timeline"** in the sidebar
2. View chronological activity log
3. Filter by date using the date picker
4. See expected vs actual times

### Emergency Response

When a critical alert occurs:
1. Browser notification appears (if enabled)
2. Alert shows in dashboard
3. Click alert for details
4. Choose action:
   - Check in with loved one
   - Mark as false alarm
   - Contact emergency services

## 🛠️ Technical Details

### Architecture

```
web-app/
├── index.html          # Main HTML structure
├── css/
│   └── styles.css      # Styling and responsive design
├── js/
│   ├── api.js          # API communication layer
│   ├── notifications.js # Browser notification handling
│   └── app.js          # Main application logic
└── README.md           # This file
```

### API Integration

The app communicates with the Raspberry Pi backend via REST API:

**Endpoints:**
- `GET /health` - Connection test
- `GET /api/activities` - Get all activities
- `GET /api/activities/date/{date}` - Get activities by date
- `GET /api/alerts` - Get all alerts
- `GET /api/alerts/active` - Get active alerts
- `POST /api/alerts/{id}/acknowledge` - Acknowledge alert
- `GET /api/statistics/dashboard` - Get dashboard stats
- `POST /api/emergency/trigger` - Trigger emergency alert

### Mock Data

For development without a backend, the app includes mock data:
- Sample activities (wake up, breakfast, medication, etc.)
- Sample alerts (missed medication, delayed breakfast)
- Sample statistics

The app automatically falls back to mock data if the API is unavailable.

### Browser Notifications

The app uses the Web Notifications API:
- Requests permission on first load
- Shows alerts for anomalies
- Plays notification sound
- Requires user interaction to dismiss critical alerts

### Local Storage

Settings are persisted in browser localStorage:
- API endpoint URL
- Notification preferences
- Refresh interval

## 🎨 Customization

### Changing Colors

Edit `css/styles.css` CSS variables:

```css
:root {
    --primary: #3b82f6;      /* Primary blue */
    --danger: #ef4444;       /* Alert red */
    --success: #10b981;      /* Success green */
    --warning: #f59e0b;      /* Warning orange */
}
```

### Adding Activity Icons

Edit `js/app.js` activityIcons object:

```javascript
const activityIcons = {
    'wake up': '🌅',
    'breakfast': '🍳',
    'your-activity': '🎯',  // Add custom activity
};
```

### Adjusting Refresh Rate

Default: 30 seconds
- Change in Settings page
- Or edit localStorage: `refreshInterval`

## 📊 Browser Compatibility

| Browser | Version | Support |
|---------|---------|---------|
| Chrome  | 90+     | ✅ Full |
| Firefox | 88+     | ✅ Full |
| Safari  | 14+     | ✅ Full |
| Edge    | 90+     | ✅ Full |

**Note:** Notifications require HTTPS in production (except localhost).

## 🔒 Security

- All data stored locally in browser
- No cloud storage or third-party services
- Direct connection to Raspberry Pi only
- HTTPS recommended for production

## 🐛 Troubleshooting

### "Disconnected" Status

**Problem:** Red "Disconnected" indicator

**Solutions:**
1. Check Raspberry Pi is powered on
2. Verify IP address in Settings
3. Ensure Pi and computer on same network
4. Check firewall settings
5. Test connection in Settings page

### No Notifications

**Problem:** Not receiving browser notifications

**Solutions:**
1. Check notification permission in browser settings
2. Enable notifications in Settings page
3. Ensure "Do Not Disturb" is off
4. Try different browser

### Mock Data Showing

**Problem:** Seeing sample data instead of real data

**Solutions:**
1. Configure API endpoint in Settings
2. Test connection
3. Check browser console for errors
4. Verify backend is running

### Slow Performance

**Problem:** App feels sluggish

**Solutions:**
1. Increase refresh interval (Settings)
2. Clear browser cache
3. Close other tabs
4. Check network connection

## 📝 Development

### Running Locally

```bash
# Simple HTTP server
python -m http.server 8000

# Or with Node.js
npx http-server -p 8000

# Or with PHP
php -S localhost:8000
```

### Testing with Mock Data

The app automatically uses mock data when the backend is unavailable. To force mock data:

1. Set invalid API endpoint in Settings
2. Or comment out API calls in `js/app.js`

### Adding New Features

1. **New Page:**
   - Add HTML in `index.html`
   - Add nav item with `data-page` attribute
   - Add case in `loadPageData()` function

2. **New API Endpoint:**
   - Add method in `js/api.js` SentinelAPI class
   - Add mock data in `mockData` object
   - Call from appropriate page loader

3. **New Notification Type:**
   - Add method in `js/notifications.js`
   - Call from event handler in `js/app.js`

## 🤝 Contributing

This is a university project for elderly care monitoring. Contributions welcome!

## 📄 License

See LICENSE file in repository root.

## 👥 Team

Built with ❤️ for IBM Ghost - Granite Ghost Companion Device

## 🔗 Related Projects

- **Raspberry Pi Backend**: Pattern learning and anomaly detection
- **IBM Granite Integration**: On-device AI inference
- **Sensor Integration**: PIR and voice activity detection

## 📞 Support

For issues or questions:
1. Check Troubleshooting section
2. Review browser console for errors
3. Verify backend API is running
4. Contact project team

---

**Version:** 1.0.0  
**Last Updated:** May 2026  
**Status:** MVP Complete ✅