/**
 * API Service - Handles all communication with the Raspberry Pi backend
 */

class SentinelAPI {
    constructor() {
        // Default to same-origin so the web app works on whatever port the
        // server runs on (avoids the macOS port-5000 / AirPlay collision).
        // Setting an absolute URL via Settings (e.g. the Pi's IP) overrides this.
        this.baseURL = localStorage.getItem('apiEndpoint') || '';
        this.isConnected = false;
    }

    /**
     * Set the API endpoint
     */
    setEndpoint(url) {
        this.baseURL = url.replace(/\/$/, ''); // Remove trailing slash
        localStorage.setItem('apiEndpoint', this.baseURL);
    }

    /**
     * Get the current API endpoint
     */
    getEndpoint() {
        return this.baseURL;
    }

    /**
     * Make a GET request to the API
     */
    async get(endpoint) {
        try {
            const response = await fetch(`${this.baseURL}${endpoint}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            this.isConnected = true;
            return await response.json();
        } catch (error) {
            this.isConnected = false;
            console.error('API GET Error:', error);
            throw error;
        }
    }

    /**
     * Make a POST request to the API
     */
    async post(endpoint, data) {
        try {
            const response = await fetch(`${this.baseURL}${endpoint}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify(data),
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            this.isConnected = true;
            return await response.json();
        } catch (error) {
            this.isConnected = false;
            console.error('API POST Error:', error);
            throw error;
        }
    }

    /**
     * Make a DELETE request to the API
     */
    async delete(endpoint) {
        try {
            const response = await fetch(`${this.baseURL}${endpoint}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                },
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            this.isConnected = true;
            return await response.json();
        } catch (error) {
            this.isConnected = false;
            console.error('API DELETE Error:', error);
            throw error;
        }
    }

    /**
     * Test connection to the API
     */
    async testConnection() {
        try {
            const response = await fetch(`${this.baseURL}/health`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                },
            });

            this.isConnected = response.ok;
            return this.isConnected;
        } catch (error) {
            this.isConnected = false;
            return false;
        }
    }

    // ===== Activity Endpoints =====

    /**
     * Get all activities
     */
    async getActivities() {
        return await this.get('/api/activities');
    }

    /**
     * Get today's activities
     */
    async getTodayActivities() {
        const today = new Date().toISOString().split('T')[0];
        return await this.get(`/api/activities/date/${today}`);
    }

    /**
     * Get activities for a specific date
     */
    async getActivitiesByDate(date) {
        return await this.get(`/api/activities/date/${date}`);
    }

    /**
     * Log a manual activity
     */
    async logActivity(activityName, time) {
        return await this.post('/api/activities/log', {
            activity: activityName,
            time: time || new Date().toISOString(),
        });
    }

    // ===== Alert Endpoints =====

    /**
     * Get all alerts
     */
    async getAlerts() {
        return await this.get('/api/alerts');
    }

    /**
     * Get active (unresolved) alerts
     */
    async getActiveAlerts() {
        return await this.get('/api/alerts/active');
    }

    /**
     * Acknowledge an alert
     */
    async acknowledgeAlert(alertId) {
        return await this.post(`/api/alerts/${alertId}/acknowledge`, {});
    }

    /**
     * Mark alert as false alarm
     */
    async markFalseAlarm(alertId) {
        return await this.post(`/api/alerts/${alertId}/false-alarm`, {});
    }

    // ===== Routine Endpoints =====

    /**
     * Get routine template (expected times)
     */
    async getRoutineTemplate() {
        return await this.get('/api/routine/template');
    }

    /**
     * Update routine template
     */
    async updateRoutineTemplate(activityId, expectedTime) {
        return await this.post('/api/routine/template', {
            activity_id: activityId,
            expected_time: expectedTime,
        });
    }

    // ===== Statistics Endpoints =====

    /**
     * Get dashboard statistics
     */
    async getStatistics() {
        return await this.get('/api/statistics/dashboard');
    }

    /**
     * Get activity patterns
     */
    async getPatterns() {
        return await this.get('/api/statistics/patterns');
    }

    // ===== Emergency Endpoints =====

    /**
     * Trigger emergency alert
     */
    async triggerEmergency(alertId, message) {
        return await this.post('/api/emergency/trigger', {
            alert_id: alertId,
            message: message,
        });
    }
}

// Create global API instance
const api = new SentinelAPI();

// Mock data for development/testing when backend is not available
const mockData = {
    activities: [
        {
            id: 1,
            name: 'wake up',
            category: 'rest',
            time: '07:30',
            status: 'completed',
            expected_time: '07:00',
        },
        {
            id: 2,
            name: 'breakfast',
            category: 'meal',
            time: '08:15',
            status: 'completed',
            expected_time: '08:00',
        },
        {
            id: 3,
            name: 'medication',
            category: 'health',
            time: '09:05',
            status: 'completed',
            expected_time: '09:00',
        },
        {
            id: 4,
            name: 'lunch',
            category: 'meal',
            time: null,
            status: 'pending',
            expected_time: '12:30',
        },
    ],

    alerts: [
        {
            id: 1,
            activity: 'medication',
            expected_time: '09:00',
            actual_time: null,
            severity: 'warning',
            message: 'Medication time passed without confirmation',
            timestamp: new Date(Date.now() - 3600000).toISOString(),
            resolved: false,
        },
        {
            id: 2,
            activity: 'breakfast',
            expected_time: '08:00',
            actual_time: null,
            severity: 'critical',
            message: 'No activity detected for 2 hours past expected breakfast time',
            timestamp: new Date(Date.now() - 7200000).toISOString(),
            resolved: false,
        },
    ],

    statistics: {
        activities_today: 3,
        active_alerts: 2,
        routine_score: 85,
        last_activity: '09:05',
        last_activity_name: 'medication',
    },

    patterns: {
        wake_up: { mean: '07:15', std_dev: 30 },
        breakfast: { mean: '08:30', std_dev: 45 },
        medication: { mean: '09:00', std_dev: 15 },
        lunch: { mean: '12:30', std_dev: 60 },
    },
};

/**
 * Get mock data when API is unavailable
 */
function getMockData(type) {
    console.log('Using mock data for:', type);
    return new Promise((resolve) => {
        setTimeout(() => {
            resolve(mockData[type] || []);
        }, 500); // Simulate network delay
    });
}

/**
 * Wrapper function to use mock data as fallback.
 * Toggles a global "demo data" banner so it's obvious in the UI when
 * we're not actually talking to the backend.
 */
async function fetchWithFallback(apiCall, mockType) {
    try {
        const result = await apiCall();
        toggleMockBanner(false);
        return result;
    } catch (error) {
        console.warn('API call failed, using mock data:', error.message);
        toggleMockBanner(true);
        return getMockData(mockType);
    }
}

function toggleMockBanner(show) {
    let banner = document.getElementById('mock-data-banner');
    if (!banner) {
        banner = document.createElement('div');
        banner.id = 'mock-data-banner';
        banner.setAttribute('role', 'status');
        banner.style.cssText = [
            'position: fixed',
            'top: 0',
            'left: 0',
            'right: 0',
            'z-index: 9999',
            'padding: 6px 12px',
            'background: #f59e0b',
            'color: #1f2937',
            'font: 600 13px/1.4 system-ui, sans-serif',
            'text-align: center',
            'box-shadow: 0 2px 6px rgba(0,0,0,.15)',
        ].join(';');
        banner.textContent =
            'Demo data — backend unreachable. Check Settings or start the API.';
        document.body.appendChild(banner);
    }
    banner.style.display = show ? 'block' : 'none';
}

// Made with Bob
