/**
 * Main Application Logic
 */

// Global state
let currentPage = 'dashboard';
let refreshInterval = null;
let currentAlert = null;

// Activity category colors and icons
const activityCategories = {
    'meal': { color: '#f59e0b', icon: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm-1-13h2v6h-2zm0 8h2v2h-2z' },
    'health': { color: '#ef4444', icon: 'M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z' },
    'exercise': { color: '#10b981', icon: 'M13.49 5.48c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm-3.6 13.9l1-4.4 2.1 2v6h2v-7.5l-2.1-2 .6-3c1.3 1.5 3.3 2.5 5.5 2.5v-2c-1.9 0-3.5-1-4.3-2.4l-1-1.6c-.4-.6-1-1-1.7-1-.3 0-.5.1-.8.1l-5.2 2.2v4.7h2v-3.4l1.8-.7-1.6 8.1-4.9-1-.4 2 7 1.4z' },
    'rest': { color: '#6366f1', icon: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z' },
    'social': { color: '#8b5cf6', icon: 'M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z' },
    'cognitive': { color: '#3b82f6', icon: 'M9 11.75c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zm6 0c-.69 0-1.25.56-1.25 1.25s.56 1.25 1.25 1.25 1.25-.56 1.25-1.25-.56-1.25-1.25-1.25zM12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8 0-.29.02-.58.05-.86 2.36-1.05 4.23-2.98 5.21-5.37C11.07 8.33 14.05 10 17.42 10c.78 0 1.53-.09 2.25-.26.21.71.33 1.47.33 2.26 0 4.41-3.59 8-8 8z' },
    'other': { color: '#64748b', icon: 'M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z' }
};

// Get activity icon HTML
function getActivityIcon(category) {
    const cat = activityCategories[category] || activityCategories['other'];
    return `
        <svg width="24" height="24" viewBox="0 0 24 24" fill="${cat.color}">
            <path d="${cat.icon}"/>
        </svg>
    `;
}

/**
 * Initialize the application
 */
async function init() {
    console.log('Initializing The Sentinel Dashboard...');

    // Set up navigation
    setupNavigation();

    // Load settings
    loadSettings();

    // Check connection
    await checkConnection();

    // Load initial data
    await loadDashboard();

    // Start auto-refresh
    startAutoRefresh();

    // Set up event listeners
    setupEventListeners();

    console.log('Dashboard initialized successfully');
}

/**
 * Set up navigation between pages
 */
function setupNavigation() {
    const navItems = document.querySelectorAll('.nav-item');

    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            navigateTo(page);
        });
    });
}

/**
 * Navigate to a specific page
 */
function navigateTo(pageName) {
    // Update active nav item
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
        if (item.dataset.page === pageName) {
            item.classList.add('active');
        }
    });

    // Update active page
    document.querySelectorAll('.page').forEach(page => {
        page.classList.remove('active');
    });

    const targetPage = document.getElementById(pageName);
    if (targetPage) {
        targetPage.classList.add('active');
        currentPage = pageName;

        // Load page-specific data
        loadPageData(pageName);
    }
}

/**
 * Load data for specific page
 */
async function loadPageData(pageName) {
    switch (pageName) {
        case 'dashboard':
            await loadDashboard();
            break;
        case 'alerts':
            await loadAlerts();
            break;
        case 'timeline':
            await loadTimeline();
            break;
        case 'settings':
            loadSettings();
            break;
    }
}

/**
 * Check connection to Raspberry Pi
 */
async function checkConnection() {
    const statusIndicator = document.getElementById('connectionStatus');
    const isConnected = await api.testConnection();

    if (isConnected) {
        statusIndicator.classList.add('connected');
        statusIndicator.classList.remove('error');
        statusIndicator.querySelector('.status-text').textContent = 'Connected';
    } else {
        statusIndicator.classList.remove('connected');
        statusIndicator.classList.add('error');
        statusIndicator.querySelector('.status-text').textContent = 'Disconnected';
    }

    return isConnected;
}

/**
 * Load dashboard data
 */
async function loadDashboard() {
    try {
        // Load statistics
        const stats = await fetchWithFallback(
            () => api.getStatistics(),
            'statistics'
        );
        updateStatistics(stats);

        // Load recent alerts
        const alerts = await fetchWithFallback(
            () => api.getActiveAlerts(),
            'alerts'
        );
        updateRecentAlerts(alerts.slice(0, 3)); // Show only 3 most recent

        // Load today's activities
        const activities = await fetchWithFallback(
            () => api.getTodayActivities(),
            'activities'
        );
        updateTodayActivities(activities);

        // Update alert badge
        updateAlertBadge(alerts.length);

    } catch (error) {
        console.error('Error loading dashboard:', error);
        showError('Failed to load dashboard data');
    }
}

/**
 * Update statistics cards
 */
function updateStatistics(stats) {
    document.getElementById('activitiesToday').textContent = stats.activities_today || 0;
    document.getElementById('activeAlerts').textContent = stats.active_alerts || 0;
    document.getElementById('routineScore').textContent = stats.routine_score ? `${stats.routine_score}%` : '--';
    document.getElementById('lastActivity').textContent = stats.last_activity || '--';
    
    // Update last activity name
    const lastActivityNameEl = document.getElementById('lastActivityName');
    if (lastActivityNameEl) {
        lastActivityNameEl.textContent = stats.last_activity_name
            ? stats.last_activity_name.charAt(0).toUpperCase() + stats.last_activity_name.slice(1)
            : 'No recent activity';
    }
}

/**
 * Update recent alerts section
 */
function updateRecentAlerts(alerts) {
    const container = document.getElementById('recentAlerts');

    if (!alerts || alerts.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg class="empty-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                    <polyline points="22 4 12 14.01 9 11.01"></polyline>
                </svg>
                <p>No alerts - everything looks good!</p>
            </div>
        `;
        return;
    }

    container.innerHTML = alerts.map(alert => createAlertHTML(alert)).join('');
}

/**
 * Update today's activities
 */
function updateTodayActivities(activities) {
    const container = document.getElementById('todayActivities');

    if (!activities || activities.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <svg class="empty-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
                    <line x1="16" y1="2" x2="16" y2="6"></line>
                    <line x1="8" y1="2" x2="8" y2="6"></line>
                    <line x1="3" y1="10" x2="21" y2="10"></line>
                </svg>
                <p>No activities logged today</p>
            </div>
        `;
        return;
    }

    container.innerHTML = activities.map(activity => createActivityHTML(activity)).join('');
}

/**
 * Create HTML for an alert item
 */
function createAlertHTML(alert) {
    const severityClass = alert.severity === 'critical' ? 'critical' : '';
    const resolvedClass = alert.resolved ? 'resolved' : '';
    const timeAgo = getTimeAgo(alert.timestamp);

    return `
        <div class="alert-item ${severityClass} ${resolvedClass}" onclick="showAlertModal(${JSON.stringify(alert).replace(/"/g, '"')})">
            <div class="alert-header">
                <span class="alert-title">${alert.activity.charAt(0).toUpperCase() + alert.activity.slice(1)}</span>
                <span class="alert-time">${timeAgo}</span>
            </div>
            <p class="alert-message">${alert.message}</p>
        </div>
    `;
}

/**
 * Create HTML for an activity item
 */
function createActivityHTML(activity) {
    const iconHTML = getActivityIcon(activity.category);
    const statusClass = activity.status || 'pending';
    const statusText = activity.status === 'completed' ? 'Completed' :
                      activity.status === 'missed' ? 'Missed' : 'Pending';

    return `
        <div class="activity-item">
            <div class="activity-icon">${iconHTML}</div>
            <div class="activity-details">
                <div class="activity-name">${activity.name.charAt(0).toUpperCase() + activity.name.slice(1)}</div>
                <div class="activity-time">
                    Expected: ${activity.expected_time || '--'}
                    ${activity.time ? `| Actual: ${activity.time}` : ''}
                </div>
            </div>
            <span class="activity-status ${statusClass}">${statusText}</span>
        </div>
    `;
}

/**
 * Load all alerts
 */
async function loadAlerts() {
    try {
        const alerts = await fetchWithFallback(
            () => api.getAlerts(),
            'alerts'
        );

        const container = document.getElementById('allAlerts');

        if (!alerts || alerts.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <span class="empty-icon">🎉</span>
                    <p>No alerts found</p>
                </div>
            `;
            return;
        }

        container.innerHTML = alerts.map(alert => createAlertHTML(alert)).join('');
        updateAlertBadge(alerts.filter(a => !a.resolved).length);

    } catch (error) {
        console.error('Error loading alerts:', error);
        showError('Failed to load alerts');
    }
}

/**
 * Load activity timeline
 */
async function loadTimeline() {
    try {
        const dateFilter = document.getElementById('dateFilter').value;
        let activities;

        if (dateFilter) {
            activities = await api.getActivitiesByDate(dateFilter);
        } else {
            activities = await fetchWithFallback(
                () => api.getTodayActivities(),
                'activities'
            );
        }

        const container = document.getElementById('timelineContent');

        if (!activities || activities.length === 0) {
            container.innerHTML = `
                <div class="empty-state">
                    <span class="empty-icon">📅</span>
                    <p>No activities found for this date</p>
                </div>
            `;
            return;
        }

        container.innerHTML = activities.map(activity => createTimelineItemHTML(activity)).join('');

    } catch (error) {
        console.error('Error loading timeline:', error);
        showError('Failed to load timeline');
    }
}

/**
 * Create HTML for timeline item
 */
function createTimelineItemHTML(activity) {
    const icon = activityIcons[activity.name] || activityIcons[activity.category] || activityIcons['other'];
    const time = activity.time || activity.expected_time || '--';

    return `
        <div class="timeline-item">
            <div class="timeline-content">
                <div class="timeline-time">${time}</div>
                <div class="timeline-title">${icon} ${activity.name}</div>
                <div class="timeline-description">
                    ${activity.status === 'completed' ? 'Completed successfully' : 
                      activity.status === 'missed' ? 'Missed' : 'Pending'}
                </div>
            </div>
        </div>
    `;
}

/**
 * Clear date filter
 */
function clearDateFilter() {
    document.getElementById('dateFilter').value = '';
    loadTimeline();
}

/**
 * Show alert modal
 */
function showAlertModal(alert) {
    currentAlert = alert;
    const modal = document.getElementById('alertModal');
    const modalBody = document.getElementById('modalBody');

    const severityIcon = alert.severity === 'critical' ? '🚨' : '⚠️';
    const timeAgo = getTimeAgo(alert.timestamp);

    modalBody.innerHTML = `
        <div style="margin-bottom: 1rem;">
            <h4 style="margin-bottom: 0.5rem;">${severityIcon} ${alert.activity}</h4>
            <p style="color: var(--text-secondary); font-size: 0.875rem;">${timeAgo}</p>
        </div>
        <div style="padding: 1rem; background: var(--background); border-radius: var(--radius); margin-bottom: 1rem;">
            <p><strong>Expected Time:</strong> ${alert.expected_time}</p>
            <p><strong>Actual Time:</strong> ${alert.actual_time || 'Not recorded'}</p>
            <p><strong>Status:</strong> ${alert.resolved ? 'Resolved' : 'Active'}</p>
        </div>
        <p>${alert.message}</p>
    `;

    modal.classList.add('active');
}

/**
 * Close modal
 */
function closeModal() {
    document.getElementById('alertModal').classList.remove('active');
    currentAlert = null;
}

/**
 * Acknowledge alert
 */
async function acknowledgeAlert() {
    if (!currentAlert) return;

    try {
        await api.acknowledgeAlert(currentAlert.id);
        closeModal();
        await loadAlerts();
        await loadDashboard();
        showSuccess('Alert acknowledged');
    } catch (error) {
        console.error('Error acknowledging alert:', error);
        showError('Failed to acknowledge alert');
    }
}

/**
 * Contact emergency services
 */
async function contactEmergency() {
    if (!currentAlert) return;

    const confirmed = confirm(
        'This will send an emergency alert to registered contacts. Continue?'
    );

    if (!confirmed) return;

    try {
        await api.triggerEmergency(currentAlert.id, currentAlert.message);
        closeModal();
        showSuccess('Emergency alert sent');
    } catch (error) {
        console.error('Error triggering emergency:', error);
        showError('Failed to send emergency alert');
    }
}

/**
 * Load settings
 */
function loadSettings() {
    const endpoint = api.getEndpoint();
    document.getElementById('apiEndpoint').value = endpoint;

    const notificationsEnabled = notifications.isEnabled();
    document.getElementById('enableNotifications').checked = notificationsEnabled;

    const refreshInterval = localStorage.getItem('refreshInterval') || '30';
    document.getElementById('refreshInterval').value = refreshInterval;
}

/**
 * Save settings
 */
function saveSettings() {
    const endpoint = document.getElementById('apiEndpoint').value;
    api.setEndpoint(endpoint);

    const notificationsEnabled = document.getElementById('enableNotifications').checked;
    if (notificationsEnabled) {
        notifications.enable();
        notifications.requestPermission();
    } else {
        notifications.disable();
    }

    const refreshIntervalValue = document.getElementById('refreshInterval').value;
    localStorage.setItem('refreshInterval', refreshIntervalValue);

    // Restart auto-refresh with new interval
    startAutoRefresh();

    showSuccess('Settings saved successfully');
}

/**
 * Test connection
 */
async function testConnection() {
    const isConnected = await checkConnection();

    if (isConnected) {
        showSuccess('Connection successful!');
    } else {
        showError('Connection failed. Please check the endpoint and try again.');
    }
}

/**
 * Start auto-refresh
 */
function startAutoRefresh() {
    // Clear existing interval
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }

    const intervalSeconds = parseInt(localStorage.getItem('refreshInterval') || '30');
    const intervalMs = intervalSeconds * 1000;

    refreshInterval = setInterval(async () => {
        await checkConnection();
        await loadPageData(currentPage);
    }, intervalMs);
}

/**
 * Update alert badge
 */
function updateAlertBadge(count) {
    const badge = document.getElementById('alertBadge');
    badge.textContent = count;
    badge.style.display = count > 0 ? 'block' : 'none';
}

/**
 * Get time ago string
 */
function getTimeAgo(timestamp) {
    const now = new Date();
    const time = new Date(timestamp);
    const diffMs = now - time;
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins} min ago`;

    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours} hour${diffHours > 1 ? 's' : ''} ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays} day${diffDays > 1 ? 's' : ''} ago`;
}

/**
 * Show success message
 */
function showSuccess(message) {
    // Simple alert for now - can be replaced with toast notification
    alert('✅ ' + message);
}

/**
 * Show error message
 */
function showError(message) {
    // Simple alert for now - can be replaced with toast notification
    alert('❌ ' + message);
}

/**
 * Set up event listeners
 */
function setupEventListeners() {
    // Mobile menu toggle
    const mobileMenuBtn = document.getElementById('mobileMenuBtn');
    const sidebar = document.querySelector('.sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    
    if (mobileMenuBtn) {
        mobileMenuBtn.addEventListener('click', () => {
            sidebar.classList.toggle('active');
            sidebarOverlay.classList.toggle('active');
        });
    }
    
    // Close sidebar when overlay is clicked
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => {
            sidebar.classList.remove('active');
            sidebarOverlay.classList.remove('active');
        });
    }
    
    // Close sidebar when nav item is clicked on mobile
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            if (window.innerWidth <= 768) {
                sidebar.classList.remove('active');
                sidebarOverlay.classList.remove('active');
            }
        });
    });

    // Close modal on background click
    document.getElementById('alertModal').addEventListener('click', (e) => {
        if (e.target.id === 'alertModal') {
            closeModal();
        }
    });

    // Handle ESC key to close modal and sidebar
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModal();
            sidebar.classList.remove('active');
            sidebarOverlay.classList.remove('active');
        }
    });
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Made with Bob
