/**
 * Main Application Logic
 */

// Global state
let currentPage = 'dashboard';
let refreshInterval = null;
let currentAlert = null;

// Activity icons mapping
const activityIcons = {
    'wake up': '🌅',
    'breakfast': '🍳',
    'medication': '💊',
    'walk': '🚶',
    'lunch': '🍽️',
    'dinner': '🍲',
    'bedtime': '🌙',
    'chess': '♟️',
    'read': '📖',
    'call': '📞',
    'exercise': '🏃',
    'rest': '😴',
    'social': '👥',
    'cognitive': '🧠',
    'health': '❤️',
    'meal': '🍴',
    'other': '📋',
};

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
}

/**
 * Update recent alerts section
 */
function updateRecentAlerts(alerts) {
    const container = document.getElementById('recentAlerts');

    if (!alerts || alerts.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">🎉</span>
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
                <span class="empty-icon">📅</span>
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
                <span class="alert-title">${alert.activity}</span>
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
    const icon = activityIcons[activity.name] || activityIcons[activity.category] || activityIcons['other'];
    const statusClass = activity.status || 'pending';
    const statusText = activity.status === 'completed' ? 'Completed' : 
                      activity.status === 'missed' ? 'Missed' : 'Pending';

    return `
        <div class="activity-item">
            <div class="activity-icon">${icon}</div>
            <div class="activity-details">
                <div class="activity-name">${activity.name}</div>
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
    // Close modal on background click
    document.getElementById('alertModal').addEventListener('click', (e) => {
        if (e.target.id === 'alertModal') {
            closeModal();
        }
    });

    // Handle ESC key to close modal
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModal();
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
