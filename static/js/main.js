// main.js
/**
 * Displays a toast message on the screen.
 * @param {string} message - The message to display in the toast.
 * @param {string} type - The Bootstrap contextual class, e.g., 'success', 'danger'.
 */
function showToast(message, type = 'primary') {
    const toastElement = document.getElementById('server-response-toast');
    const toastMessage = document.getElementById('toast-message');
    if (!toastElement || !toastMessage) return;

    toastMessage.innerText = message;
    toastElement.className = `toast align-items-center text-bg-${type} border-0`;
    const toast = new bootstrap.Toast(toastElement);
    toast.show();
}

// Icon definitions using SVG files from static/icons
const greenCheckIcon = `<img src="/static/icons/check_circle.svg" alt="connected" style="height: 16px; width: 16px;">`;
const redXIcon = `<img src="/static/icons/x_circle.svg" alt="not connected" style="height: 16px; width: 16px;">`;

// Legacy: kept for backward compatibility if needed
const pollingIntervals = {};
const torrentHashMap = {};

// Hash tracking for SSE updates
const hashToElementMap = new Map(); // Maps hash -> resultItem element

// State tracking to prevent unnecessary DOM updates
let lastClientStatus = null;
let lastMamStats = null;

// Global storage for VIP expiry date (updated by loadMamUserData)
window.currentVipUntil = null;
window.currentBonusPoints = 0;


/**
 * Initializes Server-Sent Events (SSE) connection for real-time toast notifications.
 */
function initializeEventStream() {
    const eventSource = new EventSource('/events');
    
    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            
            switch(data.event) {
                case 'toast':
                    showToast(data.message, data.type);
                    break;
                    
                case 'torrent-progress':
                    // Update UI for each torrent
                    const torrents = data.torrents || {};
                    for (const [hash, torrentData] of Object.entries(torrents)) {
                        // Find the DOM element for this hash
                        const resultItem = hashToElementMap.get(hash);
                        if (resultItem) {
                            updateTorrentUI(hash, torrentData, resultItem);
                        }
                    }
                    break;
                    
                case 'client-status':
                    // Only update DOM if status actually changed
                    if (lastClientStatus === data.status) {
                        break; // No change, skip DOM updates
                    }
                    lastClientStatus = data.status;
                    
                    const statusSpan = document.getElementById("client-status");
                    const statusIconSpan = document.getElementById("client-status-icon");
                    const clientTypeDisplay = document.getElementById('client-type-display');
                    
                    const isConnected = data.status === "connected";
                    if (statusSpan) {
                        statusSpan.textContent = isConnected ? "CONNECTED" : "NOT CONNECTED";
                        statusSpan.className = isConnected ? "text-success" : "text-danger";
                    }
                    if (statusIconSpan) {
                        statusIconSpan.innerHTML = isConnected ? greenCheckIcon : redXIcon;
                    }
                    if (isConnected && data.display_name && clientTypeDisplay) {
                        clientTypeDisplay.textContent = data.display_name;
                    }
                    break;
                    
                case 'mam-stats':
                    const userData = data.data || {};
                    const fields = {
                        'mam-username': 'username',
                        'mam-class': 'classname',
                        'mam-uploaded': 'uploaded',
                        'mam-downloaded': 'downloaded',
                        'mam-ratio': 'ratio',
                        'mam-bonus': 'seedbonus_formatted'
                    };
                    
                    for (const [elementId, dataKey] of Object.entries(fields)) {
                        const element = document.getElementById(elementId);
                        if (element) {
                            element.textContent = userData[dataKey] || userData['seedbonus'] || 'N/A';
                        }
                    }
                    break;
                    
                case 'vip_purchase':
                    // Handle automatic VIP purchase notifications
                    if (data.success) {
                        const amount = data.amount || 0;
                        const message = `Auto VIP top-up: Added ${amount.toFixed(1)} weeks. Remaining bonus points: ${data.seedbonus ? data.seedbonus.toFixed(0) : 'N/A'}`;
                        showToast(message, 'success');
                        // Refresh MAM stats to show updated bonus
                        loadMamUserData();
                    }
                    break;
                    
                case 'upload_purchase':
                    // Handle automatic upload credit purchase notifications
                    if (data.success) {
                        const amount = data.amount || 0;
                        const reason = data.reason || 'manual';
                        const reasonText = reason === 'ratio' ? 'low ratio' : reason === 'buffer' ? 'low buffer' : 'manual';
                        const message = `Upload credit purchased (${reasonText}): Added ${amount} GB. Remaining bonus: ${data.seedbonus ? data.seedbonus.toFixed(2) : 'N/A'}`;
                        showToast(message, 'success');
                        // Refresh MAM stats to show updated bonus
                        loadMamUserData();
                    }
                    break;
                    
                default:
                    console.warn('[SSE] Unknown event type:', data.event);
            }
        } catch (error) {
            console.error('[SSE] Failed to parse event data:', error);
        }
    };
    
    eventSource.onerror = function(error) {
        console.error('[SSE] EventSource error:', error);
        // EventSource will automatically reconnect
    };
    
    console.log('[SSE] Event stream initialized');
}

async function getTorrentHashByMID(torrentId) {
    // 1. Check the cache using the STABLE torrent ID (MID)
    if (torrentHashMap[torrentId]) {
        console.log(`[CACHE] Found hash for MID ${torrentId}: ${torrentHashMap[torrentId]}`);
        return torrentHashMap[torrentId];
    }
    
    // 2. Query backend to resolve MID to hash from client's torrent list
    try {
        console.log(`[API] Resolving hash for MID ${torrentId} from client`);
        const response = await fetch('/client/resolve_mid', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mid: torrentId })
        });
        if (!response.ok) {
            console.log(`[API] MID resolution endpoint not available or failed`);
            return null;
        }
        const data = await response.json();
        
        if (data.hash) {
            console.log(`[API] Successfully resolved MID ${torrentId} to hash: ${data.hash}`);
            // Store the hash in the cache with the MID as the key
            torrentHashMap[torrentId] = data.hash;
            return data.hash;
        } else {
            console.log(`[API] MID ${torrentId} not found in client yet`);
        }
    } catch (error) {
        console.error("Error resolving MID to hash:", error);
    }
    return null;
}

/**
 * Formats seconds into a human-readable string (e.g., 1h 5m 30s)
 * Imported from progressBarETA branch
 */
function formatDuration(seconds) {
    if (seconds >= 8640000) return '∞'; // Backend sends 8640000 for unknown/infinite
    if (seconds <= 0) return '0s';

    const units = [
        { label: 'd', value: 86400 },
        { label: 'h', value: 3600 },
        { label: 'm', value: 60 },
        { label: 's', value: 1 }
    ];

    let result = [];
    for (const unit of units) {
        if (seconds >= unit.value) {
            const count = Math.floor(seconds / unit.value);
            seconds %= unit.value;
            result.push(count + unit.label);
        }
    }
    // Return top 2 units for brevity (e.g., "1h 30m" instead of "1h 30m 15s")
    return result.slice(0, 2).join(' ');
}

/**
 * Updates the UI for a specific torrent based on its data.
 * MERGED: Uses the visual style of progressBarETA
 */
function updateTorrentUI(hash, data, resultItem) {
    const statusContainer = resultItem.querySelector('.torrent-status-container');
    if (!statusContainer) {
        console.error(`[UI-UPDATE] Could not find status container for hash ${hash}`);
        return;
    }

    const state = data.state || 'unknown';
    // Progress comes as decimal (0.0 to 1.0)
    const progressPercent = Math.floor((data.progress || 0) * 100);
    const etaSeconds = data.eta || 0;

    // Define state groups
    const errorStates = ['error', 'missingFiles'];
    const seedingStates = ['uploading', 'stalledUP', 'checkingUP', 'forcedUP', 'pausedUP', 'queuedUP'];
    const downloadingStates = ['downloading', 'metaDL', 'stalledDL', 'checkingDL', 'forcedDL', 'allocating', 'moving', 'checkingResumeData', 'queuedDL', 'pausedDL'];

    let htmlContent = '';

    if (downloadingStates.includes(state)) {
        // --- RENDER BOOTSTRAP PROGRESS BAR FOR DOWNLOADING ---
        const isPaused = state.includes('paused');
        const animatedClass = isPaused ? '' : 'progress-bar-striped progress-bar-animated';
        const bgClass = isPaused ? 'bg-secondary' : 'bg-primary';
        const etaText = isPaused ? 'Paused' : `ETA: ${formatDuration(etaSeconds)}`;
        const stateLabel = state === 'metaDL' ? 'Metadata' : (isPaused ? 'Paused' : 'Downloading');

        htmlContent = `
            <div class="d-flex justify-content-between small mb-1 text-muted">
                <span>${stateLabel}</span>
                <span>${etaText}</span>
            </div>
            <div class="progress" role="progressbar" aria-label="Download progress" aria-valuenow="${progressPercent}" aria-valuemin="0" aria-valuemax="100" style="height: 20px;">
                <div class="progress-bar ${animatedClass} ${bgClass}" style="width: ${progressPercent}%">
                    ${progressPercent}%
                </div>
            </div>
        `;
    } else if (seedingStates.includes(state) || progressPercent >= 100) {
        // --- RENDER SUCCESS BADGE/BAR FOR SEEDING/COMPLETED ---
        htmlContent = `
             <div class="d-flex justify-content-between small mb-1 text-success">
                <span>Complete</span>
                <span><i class="bi bi-check-all"></i></span>
            </div>
            <div class="progress" role="progressbar" aria-label="Seeding" aria-valuenow="100" aria-valuemin="0" aria-valuemax="100" style="height: 20px;">
                <div class="progress-bar bg-success" style="width: 100%">
                    Seeding
                </div>
            </div>
        `;
    } else if (errorStates.includes(state)) {
        // --- RENDER ERROR STATE ---
        htmlContent = `
            <div class="alert alert-danger py-1 px-2 mb-0 small text-center">
                <i class="bi bi-exclamation-triangle-fill"></i> Error: ${state}
            </div>
        `;
    } else {
        // --- FALLBACK ---
        htmlContent = `<div class="badge bg-secondary">State: ${state}</div>`;
    }

    statusContainer.innerHTML = htmlContent;
}

/**
 * Registers a torrent hash for SSE updates by mapping it to its UI element.
 * @param {string} hash - The torrent hash
 * @param {HTMLElement} resultItem - The DOM element for this result item
 */
function pollTorrentStatus(hash, resultItem) {
    const statusContainer = resultItem.querySelector('.torrent-status-container');
    if (!statusContainer) {
        console.error("Could not find status container for item:", resultItem);
        return;
    }

    console.log(`[SSE-REGISTER] Registering hash ${hash} for SSE updates`);
    
    // Map hash to element so SSE updates can find it
    hashToElementMap.set(hash, resultItem);
    
    // Show initial waiting state
    statusContainer.innerHTML = `<span class="badge bg-info text-wrap">Waiting for updates...</span>`;
}

/**
 * Checks the connection status of the torrent client and updates the UI.
 */
function checkClientStatus() {
    const statusSpan = document.getElementById("client-status");
    const statusIconSpan = document.getElementById("client-status-icon");
    const clientTypeDisplay = document.getElementById('client-type-display');

    fetch('/client/status', { cache: "no-store" })
        .then(response => response.json())
        .then(data => {
            const isSuccess = data.status === "success";
            if (statusSpan) {
                statusSpan.textContent = isSuccess ? "CONNECTED" : "NOT CONNECTED";
                statusSpan.className = isSuccess ? "text-success" : "text-danger";
            }
            if (statusIconSpan) {
                statusIconSpan.innerHTML = isSuccess ? greenCheckIcon : redXIcon;
            }
            // Update display name from the client module
            if (isSuccess && data.display_name && clientTypeDisplay) {
                clientTypeDisplay.textContent = data.display_name;
            }
            if (isSuccess) {
                refreshCategories();
            }
        })
        .catch(error => {
            console.error("Error fetching CLIENT_STATUS:", error);
            if (statusSpan) {
                statusSpan.textContent = "NOT CONNECTED";
                statusSpan.className = "text-danger";
            }
            if (statusIconSpan) {
                statusIconSpan.innerHTML = redXIcon;
            }
        });
}

/**
 * Refreshes torrent client categories and populates dropdowns.
 */
function refreshCategories() {
    fetch('/client/categories', { cache: "no-store" })
        .then(response => response.json())
        .then(data => {
            // 1. Update Result Dropdowns
            const resultDropdowns = document.querySelectorAll('.category-dropdown');
            const defaultCategory = document.getElementById('TORRENT_CLIENT_CATEGORY')?.value || '';
            resultDropdowns.forEach(dropdown => {
                const currentVal = dropdown.value;
                dropdown.innerHTML = '<option value="">Category</option>';
                if (data && typeof data === 'object') {
                    for (const key in data) {
                        const category = data[key];
                        const option = new Option(category.name, category.name);
                        dropdown.add(option);
                    }
                }
                dropdown.value = currentVal || defaultCategory;
            });

            // 2. Update Settings Dropdown
            const settingsDropdown = document.getElementById('TORRENT_CLIENT_CATEGORY');
            if (settingsDropdown) {
                const currentValue = settingsDropdown.dataset.currentValue || '';
                settingsDropdown.innerHTML = '<option value="">None</option>'; // Default empty option
                if (data && typeof data === 'object') {
                    for (const key in data) {
                        const category = data[key];
                        const option = new Option(category.name, category.name);
                        if (category.name === currentValue) {
                            option.selected = true;
                        }
                        settingsDropdown.add(option);
                    }
                }
                // If the current value wasn't found in the list but exists, append it as a manual entry
                // (Optional, but good if the client doesn't report the category yet or it's new)
                if (currentValue && ![...settingsDropdown.options].some(o => o.value === currentValue)) {
                     const option = new Option(currentValue, currentValue);
                     option.selected = true;
                     settingsDropdown.add(option);
                }
            }
        })
        .catch(error => console.error("Error refreshing categories:", error));
}

/**
 * Checks for and displays status messages from the backend IP updater.
 */
function checkForIpUpdate() {
    fetch('/ip_update_status')
        .then(response => response.ok ? response.json() : null)
        .then(data => {
            if (data?.message) {
                showToast(data.message, data.success ? 'success' : 'danger');
            }
        })
        .catch(error => console.error('Error checking IP update status:', error));
}

/**
 * Fetches MAM user data and populates the accordion.
 */
function loadMamUserData() {
    const statusSpan = document.getElementById('mam-status');
    const statusIconSpan = document.getElementById('mam-status-icon');

    fetch('/mam/user_data', { cache: "no-store" })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            // ... (Existing UI updates for username, class, etc.) ...
            statusSpan.textContent = 'CONNECTED';
            statusSpan.className = 'text-success';
            if (statusIconSpan) statusIconSpan.innerHTML = greenCheckIcon;
            
            document.getElementById('mam-username').textContent = data.username || 'N/A';
            document.getElementById('mam-class').textContent = data.classname || 'N/A';
            document.getElementById('mam-uploaded').textContent = data.uploaded || 'N/A';
            document.getElementById('mam-downloaded').textContent = data.downloaded || 'N/A';
            document.getElementById('mam-ratio').textContent = data.ratio || 'N/A';
            document.getElementById('mam-bonus').textContent = data.seedbonus_formatted || 'N/A';

            // --- NEW: Store data globally for the modal calculations ---
            window.currentVipUntil = data.vip_until; // e.g., "2025-01-15 12:00:00"
            window.currentBonusPoints = parseFloat(data.seedbonus || 0);

            // Calculate and display VIP weeks remaining in the accordion
            const vipWeeksContainer = document.getElementById('vip-weeks-container');
            const vipWeeksSpan = document.getElementById('vip-weeks-remaining');
            
            if (data.vip_until && vipWeeksContainer && vipWeeksSpan) {
                const now = new Date();
                const vipDate = new Date(data.vip_until.replace(' ', 'T')); // Fix for some browser date parsing
                const diffMs = vipDate - now;
                const diffWeeks = diffMs / (1000 * 60 * 60 * 24 * 7);

                if (diffWeeks > 0) {
                    vipWeeksSpan.textContent = `${diffWeeks.toFixed(1)} weeks`;
                    vipWeeksContainer.style.display = 'block';
                } else {
                    vipWeeksSpan.textContent = 'Expired';
                    vipWeeksContainer.style.display = 'block';
                }
            }
        })
        .catch(error => {
            console.error("Error fetching MAM user data:", error);
            statusSpan.textContent = 'NOT CONNECTED';
            statusSpan.className = 'text-danger';
        });
}

function initializeSnatchedTorrents() {
    console.log("[INIT] Checking for snatched torrents to begin polling.");
    document.querySelectorAll('.result-item[data-snatched="1"]').forEach(async (item) => {
        const torrentId = item.dataset.torrentId;
        console.log("[INIT] Found snatched item with MID:", torrentId);
        if (torrentId) {
            // Try to resolve MID to hash from client
            const hash = await getTorrentHashByMID(torrentId);
            if (hash) {
                pollTorrentStatus(hash, item);
                // Fetch initial status immediately
                fetchAndUpdateTorrentStatus(hash, item);
            } else {
                console.log(`[INIT] Hash not yet available for MID ${torrentId} - will update via SSE when ready`);
            }
        }
    });
}

/**
 * Fetches torrent status from the backend and updates the UI immediately.
 * @param {string} hash - The torrent hash
 * @param {HTMLElement} resultItem - The DOM element for this result item
 */
async function fetchAndUpdateTorrentStatus(hash, resultItem) {
    try {
        const response = await fetch(`/client/info/${hash}`, { cache: "no-store" });
        if (response.ok) {
            const data = await response.json();
            updateTorrentUI(hash, data, resultItem);
        }
    } catch (error) {
        console.error(`[FETCH] Error fetching status for hash ${hash}:`, error);
    }
}

function sanitizeFilename(name) {
    if (!name) return "Untitled";
    // Regex matches characters invalid in Windows/Linux filenames: < > : " / \ | ? *
    return name.replace(/[<>:"/\\|?*]/g, '').trim();
}

// --- Main Event Listeners ---
document.addEventListener("DOMContentLoaded", function () {
    const searchForm = document.getElementById("search-form");
    const resultsContainer = document.getElementById("results-container");
    const searchButton = document.getElementById("searchButton");
    const wrapper = document.getElementById('results-container-wrapper');
    const resultsTitle = document.getElementById('results-title');

    // --- Helper: Sanitize Filenames for Default Path Proposal ---
    function sanitizeFilename(name) {
        if (!name) return "Unknown";
        // Remove characters invalid in folders: < > : " / \ | ? *
        return name.replace(/[<>:"/\\|?*]/g, '').trim();
    }

    // --- Initialize SSE for real-time notifications ---
    initializeEventStream();

    // --- Initialize Bootstrap tooltips ---
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));

    // --- Initial Data Loads ---
    checkClientStatus();
    loadMamUserData();

    // ============================================================
    //  SETTINGS & UI LOGIC
    // ============================================================

    // Function to toggle dependent fields based on parent toggles
    function updateDependentFields() {
        const dynamicIpEnabled = document.getElementById('ENABLE_DYNAMIC_IP_UPDATE')?.checked;
        const dynamicIpIntervalInput = document.getElementById('DYNAMIC_IP_UPDATE_INTERVAL_HOURS');

        if (dynamicIpIntervalInput) {
            dynamicIpIntervalInput.disabled = !dynamicIpEnabled;
            dynamicIpIntervalInput.classList.toggle('text-muted', !dynamicIpEnabled);
        }

        const autoBuyVipEnabled = document.getElementById('AUTO_BUY_VIP')?.checked;
        const vipIntervalInput = document.getElementById('AUTO_BUY_VIP_INTERVAL_HOURS');

        if (vipIntervalInput) {
            vipIntervalInput.disabled = !autoBuyVipEnabled;
            vipIntervalInput.classList.toggle('text-muted', !autoBuyVipEnabled);
        }

        const autoOrganizeOnAdd = document.getElementById('AUTO_ORGANIZE_ON_ADD')?.checked;
        const autoOrganizeOnSchedule = document.getElementById('AUTO_ORGANIZE_ON_SCHEDULE')?.checked;
        const organizedPathInput = document.getElementById('ORGANIZED_PATH');
        const downloadPathInput = document.getElementById('TORRENT_DOWNLOAD_PATH');
        const organizeIntervalInput = document.getElementById('AUTO_ORGANIZE_INTERVAL_HOURS');
        const shouldEnablePaths = autoOrganizeOnAdd || autoOrganizeOnSchedule;

        if (organizedPathInput) {
            organizedPathInput.disabled = !shouldEnablePaths;
            organizedPathInput.classList.toggle('text-muted', !shouldEnablePaths);
        }
        if (downloadPathInput) {
            downloadPathInput.disabled = !shouldEnablePaths;
            downloadPathInput.classList.toggle('text-muted', !shouldEnablePaths);
        }
        if (organizeIntervalInput) {
            organizeIntervalInput.disabled = !autoOrganizeOnSchedule;
            organizeIntervalInput.classList.toggle('text-muted', !autoOrganizeOnSchedule);
        }

        // Upload credit toggles
        const autoUploadRatioEnabled = document.getElementById('AUTO_BUY_UPLOAD_ON_RATIO')?.checked;
        const ratioThresholdInput = document.getElementById('AUTO_BUY_UPLOAD_RATIO_THRESHOLD');
        const ratioAmountInput = document.getElementById('AUTO_BUY_UPLOAD_RATIO_AMOUNT');

        if (ratioThresholdInput) {
            ratioThresholdInput.disabled = !autoUploadRatioEnabled;
            ratioThresholdInput.classList.toggle('text-muted', !autoUploadRatioEnabled);
        }
        if (ratioAmountInput) {
            ratioAmountInput.disabled = !autoUploadRatioEnabled;
            ratioAmountInput.classList.toggle('text-muted', !autoUploadRatioEnabled);
        }

        const autoUploadBufferEnabled = document.getElementById('AUTO_BUY_UPLOAD_ON_BUFFER')?.checked;
        const bufferThresholdInput = document.getElementById('AUTO_BUY_UPLOAD_BUFFER_THRESHOLD');
        const bufferAmountInput = document.getElementById('AUTO_BUY_UPLOAD_BUFFER_AMOUNT');

        if (bufferThresholdInput) {
            bufferThresholdInput.disabled = !autoUploadBufferEnabled;
            bufferThresholdInput.classList.toggle('text-muted', !autoUploadBufferEnabled);
        }
        if (bufferAmountInput) {
            bufferAmountInput.disabled = !autoUploadBufferEnabled;
            bufferAmountInput.classList.toggle('text-muted', !autoUploadBufferEnabled);
        }

        const uploadCheckIntervalInput = document.getElementById('AUTO_BUY_UPLOAD_CHECK_INTERVAL_HOURS');
        if (uploadCheckIntervalInput) {
            const shouldEnable = autoUploadRatioEnabled || autoUploadBufferEnabled;
            uploadCheckIntervalInput.disabled = !shouldEnable;
            uploadCheckIntervalInput.classList.toggle('text-muted', !shouldEnable);
        }
    }

    // Attach listeners to all toggles
    ['ENABLE_DYNAMIC_IP_UPDATE', 'AUTO_BUY_VIP', 'AUTO_BUY_UPLOAD_ON_RATIO', 
     'AUTO_BUY_UPLOAD_ON_BUFFER', 'AUTO_ORGANIZE_ON_ADD', 'AUTO_ORGANIZE_ON_SCHEDULE'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', updateDependentFields);
    });

    // Initialize UI state
    updateDependentFields();

    // --- UPLOAD AMOUNT VALIDATION (Rounding logic) ---
    function findNearestValidAmount(value) {
        if (!window.VALID_UPLOAD_AMOUNTS || window.VALID_UPLOAD_AMOUNTS.length === 0) return value;
        const numValue = parseFloat(value);
        if (isNaN(numValue) || numValue < 1) return window.VALID_UPLOAD_AMOUNTS[0];
        if (window.VALID_UPLOAD_AMOUNTS.includes(numValue)) return numValue;

        let nearest = window.VALID_UPLOAD_AMOUNTS[0];
        let minDiff = Math.abs(numValue - nearest);
        for (const validAmount of window.VALID_UPLOAD_AMOUNTS) {
            const diff = Math.abs(numValue - validAmount);
            if (diff < minDiff) {
                minDiff = diff;
                nearest = validAmount;
            }
        }
        return nearest;
    }

    document.querySelectorAll('.upload-amount-input').forEach(input => {
        input.addEventListener('blur', function() {
            const valid = findNearestValidAmount(this.value);
            if (parseFloat(this.value) !== valid) this.value = valid;
        });
    });

    // ============================================================
    //  BUTTON HANDLERS (Settings, VIP, Upload)
    // ============================================================

    // Save Settings
    document.getElementById('save-settings-button').addEventListener('click', function () {
        fetch('/update_settings', { method: 'POST', body: new FormData(document.getElementById('settings-form')) })
            .then(response => response.json())
            .then(data => {
                showToast(data.message, data.status === 'success' ? 'success' : 'danger');
                if (data.status === 'success') {
                    document.getElementById('clientLink').href = document.getElementById('TORRENT_CLIENT_URL').value;
                    document.getElementById('clientLink').textContent = document.getElementById('TORRENT_CLIENT_URL').value;
                    if (data.client_display_name) {
                        document.getElementById('client-type-display').textContent = data.client_display_name;
                    }
                    checkClientStatus();
                    loadMamUserData();
                }
            })
            .catch(error => showToast("An error occurred while saving settings.", 'danger'));
    });

    // Buy VIP Logic
    const buyVipButton = document.getElementById('buy-vip-button');
    const vipModalEl = document.getElementById('vipPurchaseModal');
    const vipModal = vipModalEl ? new bootstrap.Modal(vipModalEl) : null;
    const VIP_COST_PER_WEEK = 1250;
    const MAX_VIP_WEEKS = 12.85; // Using 12.85 to provide a tiny buffer for floating point comparisons

    if (buyVipButton && vipModal) {
        buyVipButton.addEventListener('click', function () {
            // 1. Calculate Current VIP Weeks
            let currentWeeks = 0;
            if (window.currentVipUntil) {
                const now = new Date();
                const vipDate = new Date(window.currentVipUntil.replace(' ', 'T'));
                if (vipDate > now) {
                    const diffMs = vipDate - now;
                    currentWeeks = diffMs / (1000 * 60 * 60 * 24 * 7);
                }
            }

            // 2. Update Modal Context Info
            document.getElementById('vip-modal-current-bp').textContent = window.currentBonusPoints.toLocaleString();
            document.getElementById('vip-modal-current-weeks').textContent = currentWeeks > 0 ? `${currentWeeks.toFixed(1)} weeks` : "0 weeks";

            // 3. Configure "Max" Button Logic
            const weeksToCap = Math.max(0, MAX_VIP_WEEKS - currentWeeks);
            const weeksAffordable = window.currentBonusPoints / VIP_COST_PER_WEEK;
            
            // The actual purchase is the smaller of: what you need to hit limit vs what you can afford
            let purchaseWeeks = Math.min(weeksToCap, weeksAffordable);
            
            // Round to 1 decimal place (MAM allows 0.1 increments)
            purchaseWeeks = Math.floor(purchaseWeeks * 10) / 10;
            
            const maxBtn = document.getElementById('vip-buy-max-btn');
            const maxTitle = document.getElementById('vip-max-title');
            const maxSubtitle = document.getElementById('vip-max-subtitle');
            const maxCostBadge = document.getElementById('vip-max-cost');

            // Reset Max Button State
            maxBtn.disabled = false; // Always enabled
            maxBtn.classList.remove('btn-secondary');

            if (purchaseWeeks < 0.1) {
                // User is already practically at the limit
                maxTitle.textContent = "Top Up Max";
                maxSubtitle.textContent = "You are already at the limit (90 days)";
                maxCostBadge.textContent = "0 BP"; 
                // We keep it enabled, but make it look neutral since it won't do much
                // maxBtn.classList.add('btn-secondary');
            } else {
                // Valid purchase calculation
                const purchaseCost = Math.ceil(purchaseWeeks * VIP_COST_PER_WEEK);
                maxTitle.textContent = `Top Up +${purchaseWeeks.toFixed(1)} Weeks`;
                maxSubtitle.textContent = weeksAffordable < weeksToCap ? "Limited by your points" : "To reach 12.8 week limit";
                maxCostBadge.textContent = `${purchaseCost.toLocaleString()} BP`;
                maxBtn.classList.add('btn-success');
            }

            // 4. Configure Fixed Options (4 and 8 weeks)
            document.querySelectorAll('.vip-buy-btn[data-duration="4"], .vip-buy-btn[data-duration="8"]').forEach(btn => {
                const weeks = parseInt(btn.dataset.duration);
                const cost = weeks * VIP_COST_PER_WEEK;
                
                // Check 1: Can they afford it?
                const canAfford = window.currentBonusPoints >= cost;
                
                // Check 2: Does it exceed the hard limit?
                // Using 12.85 allows a tiny bit of wiggle room so users at 0 can buy 4+8 without strict floating point errors blocking them
                const wouldExceed = (currentWeeks + weeks) > MAX_VIP_WEEKS; 

                if (!canAfford) {
                    btn.disabled = true;
                    btn.querySelector('.badge').className = 'badge bg-danger';
                    btn.querySelector('.badge').textContent = 'Not enough BP';
                } else if (wouldExceed) {
                    btn.disabled = true;
                    btn.querySelector('.badge').className = 'badge bg-warning text-dark';
                    btn.querySelector('.badge').textContent = 'Exceeds Limit';
                } else {
                    btn.disabled = false;
                    btn.querySelector('.badge').className = 'badge bg-secondary';
                    btn.querySelector('.badge').textContent = `${cost.toLocaleString()} BP`;
                }
            });

            vipModal.show();
        });

        // Handle Click on Options
        document.querySelectorAll('.vip-buy-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                if(this.disabled) return;

                const duration = this.dataset.duration; // '4', '8', or 'max'
                
                // Lock UI
                const originalHtml = this.innerHTML;
                this.disabled = true;
                this.innerHTML = `<div class="d-flex align-items-center"><span class="spinner-border spinner-border-sm me-2"></span> Processing...</div>`;
                
                // Disable siblings
                const allBtns = document.querySelectorAll('.vip-buy-btn');
                allBtns.forEach(b => b.classList.add('disabled'));

                fetch('/mam/buy_vip', { 
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ duration: duration }) 
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const added = data.amount || (duration === 'max' ? 'Max' : duration);
                        // If amount is 0 (already at max), change the message slightly
                        if (parseFloat(data.amount) === 0 && duration === 'max') {
                            showToast(`You are already at the VIP limit.`, 'success');
                        } else {
                            showToast(`Success! Added ${added} weeks. Remaining: ${data.seedbonus} BP`, 'success');
                        }
                        loadMamUserData(); // Refresh global data
                        vipModal.hide();
                    } else {
                        showToast(data.error || 'Purchase failed', 'danger');
                    }
                })
                .catch(err => {
                    console.error(err);
                    showToast('Connection error', 'danger');
                })
                .finally(() => {
                    // Restore UI
                    this.disabled = false;
                    this.innerHTML = originalHtml;
                    allBtns.forEach(b => b.classList.remove('disabled'));
                });
            });
        });
    }

    // Buy Upload (Pre-defined amounts)
    const uploadAmountOptions = document.getElementById('upload-amount-options');
    if (uploadAmountOptions) {
        uploadAmountOptions.addEventListener('click', function(e) {
            const button = e.target.closest('button');
            if (!button) return;
            const amount = button.dataset.amount;
            
            const buttons = uploadAmountOptions.querySelectorAll('button');
            buttons.forEach(btn => btn.disabled = true);
            const originalHtml = button.innerHTML;
            button.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Buying...';

            fetch('/mam/buy_upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: amount === 'max' ? 'max' : parseFloat(amount) })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast(`Purchased ${data.amount} GB.`, 'success');
                    loadMamUserData();
                    bootstrap.Modal.getInstance(document.getElementById('uploadPurchaseModal'))?.hide();
                } else {
                    showToast(data.error || 'Failed', 'danger');
                }
            })
            .catch(() => showToast('Error purchasing upload', 'danger'))
            .finally(() => {
                buttons.forEach(btn => btn.disabled = false);
                button.innerHTML = originalHtml;
            });
        });
    }

    // Buy Custom Upload
    const buyCustomUploadButton = document.getElementById('buy-custom-upload-button');
    const customAmountInput = document.getElementById('custom-upload-amount');
    
    if (customAmountInput) {
        customAmountInput.addEventListener('input', function() {
            const val = parseFloat(this.value);
            const costInfo = document.getElementById('custom-amount-cost-info');
            if (!val || val < 1) { costInfo.textContent = ''; return; }
            const valid = findNearestValidAmount(val);
            costInfo.textContent = `Cost: ${(valid * 500).toLocaleString()} BP`;
        });
    }

    if (buyCustomUploadButton && customAmountInput) {
        const handleCustomBuy = () => {
            const raw = customAmountInput.value;
            if (!raw || parseFloat(raw) < 1) return showToast('Enter valid amount', 'warning');
            
            const valid = findNearestValidAmount(raw);
            if (parseFloat(raw) !== valid) showToast(`Rounding to ${valid} GB`, 'info');

            buyCustomUploadButton.disabled = true;
            const originalText = buyCustomUploadButton.innerHTML;
            buyCustomUploadButton.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Buying...';

            fetch('/mam/buy_upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: valid })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast(`Purchased ${valid} GB.`, 'success');
                    loadMamUserData();
                    customAmountInput.value = '';
                    bootstrap.Modal.getInstance(document.getElementById('uploadPurchaseModal'))?.hide();
                } else {
                    showToast(data.error || 'Failed', 'danger');
                }
            })
            .catch(() => showToast('Error purchasing upload', 'danger'))
            .finally(() => {
                buyCustomUploadButton.disabled = false;
                buyCustomUploadButton.innerHTML = originalText;
            });
        };

        buyCustomUploadButton.addEventListener('click', handleCustomBuy);
        customAmountInput.addEventListener('keypress', (e) => { if(e.key === 'Enter') handleCustomBuy(); });
    }

    // Insufficient Buffer Modal - Buy Recommended
    const modalBuyRecommended = document.getElementById('modal-buy-recommended');
    if (modalBuyRecommended) {
        modalBuyRecommended.addEventListener('click', function() {
            const amount = parseFloat(this.dataset.amount);
            this.disabled = true;
            this.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Buying...';

            fetch('/mam/buy_upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: amount })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast(`Purchased ${amount} GB`, 'success');
                    loadMamUserData();
                    bootstrap.Modal.getInstance(document.getElementById('insufficientBufferModal'))?.hide();

                    // Retry pending download
                    if (window.pendingDownload) {
                        performDownload(window.pendingDownload, null); 
                        window.pendingDownload = null;
                    }
                } else {
                    showToast(data.error || 'Failed', 'danger');
                }
            })
            .finally(() => {
                this.disabled = false;
                this.innerHTML = `Buy ${amount} GB`;
            });
        });
    }

    // ============================================================
    //  SEARCH SUBMISSION
    // ============================================================
    searchForm.addEventListener("submit", function (e) {
        e.preventDefault();
        searchButton.disabled = true;
        searchButton.innerHTML = `<span class="spinner-border spinner-border-sm"></span> Searching...`;
        if (resultsTitle) resultsTitle.textContent = 'Results';

        // Clear hash mappings on new search
        hashToElementMap.clear();

        const queryParams = new URLSearchParams(new FormData(searchForm)).toString();

        fetch(`/mam/search?${queryParams}`)
            .then(response => response.text())
            .then(html => {
                wrapper.style.display = 'block';
                resultsContainer.innerHTML = html;
                const count = resultsContainer.querySelectorAll('.result-item').length;
                if (resultsTitle) resultsTitle.textContent = `Results (${count})`;
                wrapper.scrollIntoView({ behavior: 'smooth', block: 'start' });
                refreshCategories();
                initializeSnatchedTorrents();
            })
            .catch(error => {
                wrapper.style.display = 'block';
                resultsContainer.innerHTML = `<div class="alert alert-danger">Search failed.</div>`;
                console.error(error);
            })
            .finally(() => {
                searchButton.disabled = false;
                searchButton.innerHTML = "Search";
            });
    });

    // ============================================================
    //  DOWNLOAD & PATH CONFIRMATION LOGIC
    // ============================================================

    // State for the confirmation modal
    let pendingDownloadData = null; 
    let pendingButton = null;

    // References to Modal Elements
    const confirmModalEl = document.getElementById('downloadConfirmModal');
    const confirmModal = confirmModalEl ? new bootstrap.Modal(confirmModalEl) : null;
    const confirmInput = document.getElementById('confirm-path-input');
    const previewSpan = document.getElementById('full-path-preview');
    const confirmBtn = document.getElementById('confirm-download-btn');

    // Live update of path preview in modal
    if (confirmInput && previewSpan) {
        confirmInput.addEventListener('input', function() {
            previewSpan.textContent = this.value;
        });
    }

    // Handle "Start Download" inside the Modal
    if (confirmBtn) {
        confirmBtn.addEventListener('click', function() {
            if (!pendingDownloadData) return;
            // Inject user's custom path into payload
            pendingDownloadData.custom_relative_path = confirmInput.value;
            confirmModal.hide();
            performDownload(pendingDownloadData, pendingButton);
        });
    }

    /**
     * Core function to execute the API call to add the torrent.
     * Handles success, failure, and insufficient buffer scenarios.
     */
    function performDownload(downloadData, button) {
        if(button) button.disabled = true;

        fetch('/client/add', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(downloadData),
        })
        .then(response => response.json())
        .then(async data => {
            // Case 1: Insufficient Buffer
            if (data.status === 'insufficient_buffer') {
                document.getElementById('modal-buffer-gb').textContent = data.buffer_gb || 0;
                document.getElementById('modal-torrent-size').textContent = data.torrent_size_gb || 0;
                document.getElementById('modal-needed-gb').textContent = data.needed_gb || 0;
                document.getElementById('modal-recommended-amount').textContent = data.recommended_amount || 0;
                document.getElementById('modal-recommended-cost').textContent = (data.recommended_cost || 0).toLocaleString();
                
                const buyBtn = document.getElementById('modal-buy-recommended');
                buyBtn.dataset.amount = data.recommended_amount || 0;

                // Save for retry after purchase
                window.pendingDownload = downloadData;
                
                new bootstrap.Modal(document.getElementById('insufficientBufferModal')).show();
                
                if(button) button.disabled = false;
                return;
            }

            // Case 2: Success or Generic Error
            showToast(data.message || data.error, data.message ? 'success' : 'danger');

            if (data.message && button) {
                button.textContent = 'Added!';
                
                // Show temporary status on the result item
                const resultItem = button.closest('.result-item');
                const statusContainer = resultItem.querySelector('.torrent-status-container');
                if (statusContainer) {
                    statusContainer.innerHTML = `<span class="badge bg-info text-wrap">Resolving torrent...</span>`;
                }

                // Poll for hash resolution (MID -> Hash)
                const torrentId = downloadData.id;
                let attempts = 0;
                const maxAttempts = 15;
                const pollInterval = setInterval(async () => {
                    attempts++;
                    const hash = await getTorrentHashByMID(torrentId);
                    if (hash) {
                        clearInterval(pollInterval);
                        pollTorrentStatus(hash, resultItem);
                        fetchAndUpdateTorrentStatus(hash, resultItem);
                    } else if (attempts >= maxAttempts) {
                        clearInterval(pollInterval);
                        if (statusContainer) statusContainer.innerHTML = `<span class="badge bg-warning">Added (pending)</span>`;
                    }
                }, 2000);

            } else if (button) {
                button.disabled = false;
            }
        })
        .catch(error => {
            console.error("Download Error:", error);
            showToast("An error occurred while adding torrent.", 'danger');
            if(button) button.disabled = false;
        });
    }

    // Main Result List Click Listener
    resultsContainer.addEventListener('click', function (event) {
        const button = event.target.closest('.add-to-client-button');
        if (button) {
            event.preventDefault();

            // Extract Data
            const resultItem = button.closest('.result-item');
            const downloadData = {
                torrent_url: button.dataset.torrentUrl,
                category: resultItem.querySelector('.category-dropdown')?.value || '',
                id: resultItem.dataset.torrentId,
                author: button.dataset.author || "Unknown",
                title: button.dataset.title || "Unknown",
                size: button.dataset.size || '0 GiB',
                main_cat: button.dataset.mainCat || ''
            };

            // Check Settings
            const autoOrganizeEnabled = document.getElementById('AUTO_ORGANIZE_ON_ADD')?.checked;

            if (autoOrganizeEnabled && confirmModal) {
                // Show Path Confirmation Modal
                const cleanAuthor = sanitizeFilename(downloadData.author);
                const cleanTitle = sanitizeFilename(downloadData.title);
                const defaultPath = `${cleanAuthor}/${cleanTitle}`;

                confirmInput.value = defaultPath;
                previewSpan.textContent = defaultPath;

                pendingDownloadData = downloadData;
                pendingButton = button;

                confirmModal.show();
            } else {
                // Default immediate download
                performDownload(downloadData, button);
            }
        }
    });

});