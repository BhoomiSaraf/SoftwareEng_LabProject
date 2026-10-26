/**
 * Smart Attendance System - Main Frontend Utilities
 */

// Show floating toast notifications
function showToast(message, type = 'info', title = '') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const iconMap = {
        success: 'bi-check-circle-fill text-success',
        danger: 'bi-exclamation-triangle-fill text-danger',
        warning: 'bi-exclamation-circle-fill text-warning',
        info: 'bi-info-circle-fill text-info'
    };

    const icon = iconMap[type] || iconMap.info;
    const headerTitle = title || (type.charAt(0).toUpperCase() + type.slice(1));
    const toastId = 'toast_' + Date.now() + '_' + Math.floor(Math.random() * 1000);

    const toastHtml = `
        <div id="${toastId}" class="toast align-items-center text-white bg-dark-card border border-subtle shadow-lg" role="alert" aria-live="assertive" aria-atomic="true" data-bs-delay="4500">
            <div class="toast-header bg-dark-glass text-white border-bottom border-subtle d-flex align-items-center">
                <i class="bi ${icon} me-2 fs-6"></i>
                <strong class="me-auto fs-xs text-uppercase tracking-wider">${headerTitle}</strong>
                <small class="text-muted fs-xxs">just now</small>
                <button type="button" class="btn-close btn-close-white shadow-none ms-2" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
            <div class="toast-body fs-sm">
                ${message}
            </div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);
    const toastElement = document.getElementById(toastId);
    if (toastElement && window.bootstrap) {
        const bsToast = new bootstrap.Toast(toastElement);
        bsToast.show();
        toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
    }
}

// Global API Fetch helper with consistent error handling
async function fetchJson(url, options = {}) {
    const defaultHeaders = {
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    };

    const config = {
        ...options,
        headers: {
            ...defaultHeaders,
            ...(options.headers || {})
        }
    };

    try {
        const response = await fetch(url, config);
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            const errorMsg = data.error || data.message || `Request failed with status ${response.status}`;
            throw new Error(errorMsg);
        }

        return data;
    } catch (err) {
        console.error(`API Error on [${url}]:`, err);
        throw err;
    }
}

// Quick helper to format ISO dates or timestamps
function formatTime(isoString) {
    if (!isoString) return '--:--';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function formatDate(isoString) {
    if (!isoString) return '--/--/----';
    const date = new Date(isoString);
    if (isNaN(date.getTime())) return isoString;
    return date.toLocaleDateString([], { year: 'numeric', month: 'short', day: 'numeric' });
}
