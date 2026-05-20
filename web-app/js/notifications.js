/**
 * Notifications Service - Handles browser notifications and alerts
 */

class NotificationService {
    constructor() {
        this.permission = 'default';
        this.enabled = localStorage.getItem('notificationsEnabled') !== 'false';
        this.checkPermission();
    }

    /**
     * Check current notification permission
     */
    checkPermission() {
        if ('Notification' in window) {
            this.permission = Notification.permission;
        }
    }

    /**
     * Request notification permission from user
     */
    async requestPermission() {
        if (!('Notification' in window)) {
            console.warn('This browser does not support notifications');
            return false;
        }

        if (this.permission === 'granted') {
            return true;
        }

        try {
            const permission = await Notification.requestPermission();
            this.permission = permission;
            return permission === 'granted';
        } catch (error) {
            console.error('Error requesting notification permission:', error);
            return false;
        }
    }

    /**
     * Show a browser notification
     */
    async show(title, options = {}) {
        if (!this.enabled) {
            console.log('Notifications are disabled');
            return;
        }

        // Request permission if not granted
        if (this.permission !== 'granted') {
            const granted = await this.requestPermission();
            if (!granted) {
                console.warn('Notification permission denied');
                return;
            }
        }

        // Default options
        const defaultOptions = {
            icon: '👻',
            badge: '🔔',
            vibrate: [200, 100, 200],
            requireInteraction: true,
        };

        const notificationOptions = { ...defaultOptions, ...options };

        try {
            const notification = new Notification(title, notificationOptions);

            // Auto-close after 10 seconds if not requiring interaction
            if (!notificationOptions.requireInteraction) {
                setTimeout(() => notification.close(), 10000);
            }

            // Handle notification click
            notification.onclick = () => {
                window.focus();
                notification.close();
                if (options.onClick) {
                    options.onClick();
                }
            };

            return notification;
        } catch (error) {
            console.error('Error showing notification:', error);
        }
    }

    /**
     * Show alert notification
     */
    async showAlert(alert) {
        const severity = alert.severity || 'warning';
        const icon = severity === 'critical' ? '🚨' : '⚠️';

        await this.show(`${icon} Alert: ${alert.activity}`, {
            body: alert.message,
            tag: `alert-${alert.id}`,
            data: alert,
            onClick: () => {
                // Navigate to alerts page and show details
                navigateTo('alerts');
                showAlertModal(alert);
            },
        });
    }

    /**
     * Show activity completion notification
     */
    async showActivityComplete(activity) {
        await this.show(`✅ Activity Completed`, {
            body: `${activity.name} logged at ${activity.time}`,
            tag: `activity-${activity.id}`,
            requireInteraction: false,
        });
    }

    /**
     * Show connection status notification
     */
    async showConnectionStatus(connected) {
        const title = connected ? '✅ Connected' : '❌ Disconnected';
        const body = connected
            ? 'Successfully connected to Sentinel device'
            : 'Lost connection to Sentinel device';

        await this.show(title, {
            body: body,
            tag: 'connection-status',
            requireInteraction: false,
        });
    }

    /**
     * Enable notifications
     */
    enable() {
        this.enabled = true;
        localStorage.setItem('notificationsEnabled', 'true');
    }

    /**
     * Disable notifications
     */
    disable() {
        this.enabled = false;
        localStorage.setItem('notificationsEnabled', 'false');
    }

    /**
     * Check if notifications are enabled
     */
    isEnabled() {
        return this.enabled;
    }

    /**
     * Play notification sound
     */
    playSound() {
        // Create audio context for notification sound
        try {
            const audioContext = new (window.AudioContext || window.webkitAudioContext)();
            const oscillator = audioContext.createOscillator();
            const gainNode = audioContext.createGain();

            oscillator.connect(gainNode);
            gainNode.connect(audioContext.destination);

            oscillator.frequency.value = 800;
            oscillator.type = 'sine';

            gainNode.gain.setValueAtTime(0.3, audioContext.currentTime);
            gainNode.gain.exponentialRampToValueAtTime(0.01, audioContext.currentTime + 0.5);

            oscillator.start(audioContext.currentTime);
            oscillator.stop(audioContext.currentTime + 0.5);
        } catch (error) {
            console.error('Error playing notification sound:', error);
        }
    }
}

// Create global notification service instance
const notifications = new NotificationService();

/**
 * Request notification permission on page load if enabled
 */
window.addEventListener('load', () => {
    if (notifications.isEnabled()) {
        notifications.requestPermission();
    }
});

// Made with Bob
