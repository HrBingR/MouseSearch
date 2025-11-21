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
                        const message = `Auto VIP top-up: Added ${amount.toFixed(2)} weeks. Remaining bonus: ${data.seedbonus ? data.seedbonus.toFixed(2) : 'N/A'}`;
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
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            statusSpan.textContent = 'CONNECTED';
            statusSpan.className = 'text-success';
            if (statusIconSpan) statusIconSpan.innerHTML = greenCheckIcon;
            document.getElementById('mam-username').textContent = data.username || 'N/A';
            document.getElementById('mam-class').textContent = data.classname || 'N/A';
            document.getElementById('mam-uploaded').textContent = data.uploaded || 'N/A';
            document.getElementById('mam-downloaded').textContent = data.downloaded || 'N/A';
            document.getElementById('mam-ratio').textContent = data.ratio || 'N/A';
            document.getElementById('mam-bonus').textContent = data.seedbonus_formatted || data.seedbonus || 'N/A';
        })
        .catch(error => {
            console.error("Error fetching MAM user data:", error);
            statusSpan.textContent = 'NOT CONNECTED';
            statusSpan.className = 'text-danger';
            if (statusIconSpan) statusIconSpan.innerHTML = redXIcon;
            // Clear other fields on error
            document.getElementById('mam-username').textContent = 'N/A';
            document.getElementById('mam-class').textContent = 'N/A';
            document.getElementById('mam-uploaded').textContent = 'N/A';
            document.getElementById('mam-downloaded').textContent = 'N/A';
            document.getElementById('mam-ratio').textContent = 'N/A';
            document.getElementById('mam-bonus').textContent = 'N/A';
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

// --- Main Event Listeners ---
document.addEventListener("DOMContentLoaded", function () {
    const searchForm = document.getElementById("search-form");
    const resultsContainer = document.getElementById("results-container");
    const searchButton = document.getElementById("searchButton");
    const wrapper = document.getElementById('results-container-wrapper');
    const resultsTitle = document.getElementById('results-title');

    // Initialize SSE for real-time notifications
    initializeEventStream();

    checkClientStatus();
    loadMamUserData();
    // setInterval(checkForIpUpdate, 30000);
    // checkForIpUpdate();

    // Function to toggle dependent fields based on parent toggles
    function updateDependentFields() {
        const dynamicIpEnabled = document.getElementById('ENABLE_DYNAMIC_IP_UPDATE').checked;
        const dynamicIpIntervalInput = document.getElementById('DYNAMIC_IP_UPDATE_INTERVAL_HOURS');
        
        if (dynamicIpIntervalInput) {
            dynamicIpIntervalInput.disabled = !dynamicIpEnabled;
            if (!dynamicIpEnabled) {
                dynamicIpIntervalInput.classList.add('text-muted');
            } else {
                dynamicIpIntervalInput.classList.remove('text-muted');
            }
        }

        // VIP auto-buy interval is only enabled when auto-buy is enabled
        const autoBuyVipEnabled = document.getElementById('AUTO_BUY_VIP').checked;
        const vipIntervalInput = document.getElementById('AUTO_BUY_VIP_INTERVAL_HOURS');
        
        if (vipIntervalInput) {
            vipIntervalInput.disabled = !autoBuyVipEnabled;
            if (!autoBuyVipEnabled) {
                vipIntervalInput.classList.add('text-muted');
            } else {
                vipIntervalInput.classList.remove('text-muted');
            }
        }

        // Organization path is only enabled if at least one auto-organize option is enabled
        const autoOrganizeOnAdd = document.getElementById('AUTO_ORGANIZE_ON_ADD').checked;
        const autoOrganizeOnSchedule = document.getElementById('AUTO_ORGANIZE_ON_SCHEDULE').checked;
        const organizedPathInput = document.getElementById('ORGANIZED_PATH');
        const downloadPathInput = document.getElementById('TORRENT_DOWNLOAD_PATH');
        const organizeIntervalInput = document.getElementById('AUTO_ORGANIZE_INTERVAL_HOURS');
        
        if (organizedPathInput) {
            const shouldEnable = autoOrganizeOnAdd || autoOrganizeOnSchedule;
            organizedPathInput.disabled = !shouldEnable;
            if (!shouldEnable) {
                organizedPathInput.classList.add('text-muted');
            } else {
                organizedPathInput.classList.remove('text-muted');
            }
        }

        if (downloadPathInput) {
            const shouldEnable = autoOrganizeOnAdd || autoOrganizeOnSchedule;
            downloadPathInput.disabled = !shouldEnable;
            if (!shouldEnable) {
                downloadPathInput.classList.add('text-muted');
            } else {
                downloadPathInput.classList.remove('text-muted');
            }
        }

        // Organize interval is only enabled when scheduled re-scan is enabled
        if (organizeIntervalInput) {
            organizeIntervalInput.disabled = !autoOrganizeOnSchedule;
            if (!autoOrganizeOnSchedule) {
                organizeIntervalInput.classList.add('text-muted');
            } else {
                organizeIntervalInput.classList.remove('text-muted');
            }
        }
        
        // Upload credit - ratio threshold fields
        const autoUploadRatioEnabled = document.getElementById('AUTO_BUY_UPLOAD_ON_RATIO').checked;
        const ratioThresholdInput = document.getElementById('AUTO_BUY_UPLOAD_RATIO_THRESHOLD');
        const ratioAmountInput = document.getElementById('AUTO_BUY_UPLOAD_RATIO_AMOUNT');
        
        if (ratioThresholdInput) {
            ratioThresholdInput.disabled = !autoUploadRatioEnabled;
            if (!autoUploadRatioEnabled) {
                ratioThresholdInput.classList.add('text-muted');
            } else {
                ratioThresholdInput.classList.remove('text-muted');
            }
        }
        
        if (ratioAmountInput) {
            ratioAmountInput.disabled = !autoUploadRatioEnabled;
            if (!autoUploadRatioEnabled) {
                ratioAmountInput.classList.add('text-muted');
            } else {
                ratioAmountInput.classList.remove('text-muted');
            }
        }
        
        // Upload credit - buffer threshold fields
        const autoUploadBufferEnabled = document.getElementById('AUTO_BUY_UPLOAD_ON_BUFFER').checked;
        const bufferThresholdInput = document.getElementById('AUTO_BUY_UPLOAD_BUFFER_THRESHOLD');
        const bufferAmountInput = document.getElementById('AUTO_BUY_UPLOAD_BUFFER_AMOUNT');
        
        if (bufferThresholdInput) {
            bufferThresholdInput.disabled = !autoUploadBufferEnabled;
            if (!autoUploadBufferEnabled) {
                bufferThresholdInput.classList.add('text-muted');
            } else {
                bufferThresholdInput.classList.remove('text-muted');
            }
        }
        
        if (bufferAmountInput) {
            bufferAmountInput.disabled = !autoUploadBufferEnabled;
            if (!autoUploadBufferEnabled) {
                bufferAmountInput.classList.add('text-muted');
            } else {
                bufferAmountInput.classList.remove('text-muted');
            }
        }
        
        // Upload credit - check interval (enabled if either ratio or buffer is enabled)
        const uploadCheckIntervalInput = document.getElementById('AUTO_BUY_UPLOAD_CHECK_INTERVAL_HOURS');
        if (uploadCheckIntervalInput) {
            const shouldEnable = autoUploadRatioEnabled || autoUploadBufferEnabled;
            uploadCheckIntervalInput.disabled = !shouldEnable;
            if (!shouldEnable) {
                uploadCheckIntervalInput.classList.add('text-muted');
            } else {
                uploadCheckIntervalInput.classList.remove('text-muted');
            }
        }
    }

    // Set up event listeners for toggles
    const dynamicIpToggle = document.getElementById('ENABLE_DYNAMIC_IP_UPDATE');
    if (dynamicIpToggle) {
        dynamicIpToggle.addEventListener('change', updateDependentFields);
    }

    const autoBuyVipToggle = document.getElementById('AUTO_BUY_VIP');
    if (autoBuyVipToggle) {
        autoBuyVipToggle.addEventListener('change', updateDependentFields);
    }
    
    const autoUploadRatioToggle = document.getElementById('AUTO_BUY_UPLOAD_ON_RATIO');
    if (autoUploadRatioToggle) {
        autoUploadRatioToggle.addEventListener('change', updateDependentFields);
    }
    
    const autoUploadBufferToggle = document.getElementById('AUTO_BUY_UPLOAD_ON_BUFFER');
    if (autoUploadBufferToggle) {
        autoUploadBufferToggle.addEventListener('change', updateDependentFields);
    }

    const autoOrganizeOnAddToggle = document.getElementById('AUTO_ORGANIZE_ON_ADD');
    if (autoOrganizeOnAddToggle) {
        autoOrganizeOnAddToggle.addEventListener('change', updateDependentFields);
    }

    const autoOrganizeOnScheduleToggle = document.getElementById('AUTO_ORGANIZE_ON_SCHEDULE');
    if (autoOrganizeOnScheduleToggle) {
        autoOrganizeOnScheduleToggle.addEventListener('change', updateDependentFields);
    }

    // Initialize disabled state on page load
    updateDependentFields();

    // --- UPLOAD AMOUNT VALIDATION ---
    // Function to find nearest valid upload amount
    function findNearestValidAmount(value) {
        if (!window.VALID_UPLOAD_AMOUNTS || window.VALID_UPLOAD_AMOUNTS.length === 0) {
            return value;
        }
        
        const numValue = parseFloat(value);
        if (isNaN(numValue) || numValue < 1) {
            return window.VALID_UPLOAD_AMOUNTS[0]; // Return smallest valid amount
        }
        
        // Check if value is already valid
        if (window.VALID_UPLOAD_AMOUNTS.includes(numValue)) {
            return numValue;
        }
        
        // Find nearest valid amount
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
    
    // Add validation to upload amount inputs
    document.querySelectorAll('.upload-amount-input').forEach(input => {
        input.addEventListener('blur', function() {
            const originalValue = this.value;
            const validValue = findNearestValidAmount(originalValue);
            
            if (parseFloat(originalValue) !== validValue) {
                this.value = validValue;
                console.log(`Rounded upload amount from ${originalValue} to ${validValue} GB`);
            }
        });
        
        // Also validate on form submission
        const form = input.closest('form');
        if (form) {
            form.addEventListener('submit', function(e) {
                const validValue = findNearestValidAmount(input.value);
                input.value = validValue;
            });
        }
    });

    document.getElementById('save-settings-button').addEventListener('click', function () {
        fetch('/update_settings', { method: 'POST', body: new FormData(document.getElementById('settings-form')) })
            .then(response => response.json())
            .then(data => {
                showToast(data.message, data.status === 'success' ? 'success' : 'danger');
                if (data.status === 'success') {
                    document.getElementById('clientLink').href = document.getElementById('TORRENT_CLIENT_URL').value;
                    document.getElementById('clientLink').textContent = document.getElementById('TORRENT_CLIENT_URL').value;
                    
                    // REMOVED: The manual capitalization logic that was here
                    
                    // Update the display name using the value returned from the server
                    if (data.client_display_name) {
                        document.getElementById('client-type-display').textContent = data.client_display_name;
                    }
                    
                    checkClientStatus();
                    loadMamUserData();
                }
            })
            .catch(error => showToast("An error occurred while saving settings.", 'danger'));
    });

    // VIP Top-Up Button Handler
    const buyVipButton = document.getElementById('buy-vip-button');
    if (buyVipButton) {
        buyVipButton.addEventListener('click', function () {
            // Disable button and show loading state
            buyVipButton.disabled = true;
            const originalText = buyVipButton.innerHTML;
            buyVipButton.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Buying...';
            
            fetch('/mam/buy_vip', { method: 'POST' })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const amount = data.amount || 0;
                        const message = `VIP topped up! Added ${amount.toFixed(2)} weeks. Remaining bonus: ${data.seedbonus ? data.seedbonus.toFixed(2) : 'N/A'}`;
                        showToast(message, 'success');
                        // Refresh MAM user data to show updated bonus points
                        loadMamUserData();
                    } else {
                        showToast(data.error || 'Failed to purchase VIP credit', 'danger');
                    }
                })
                .catch(error => {
                    console.error('Error buying VIP:', error);
                    showToast('An error occurred while purchasing VIP credit', 'danger');
                })
                .finally(() => {
                    // Re-enable button and restore text
                    buyVipButton.disabled = false;
                    buyVipButton.innerHTML = originalText;
                });
        });
    }

    // Upload Credit Purchase Handler (Manual Modal)
    const uploadAmountOptions = document.getElementById('upload-amount-options');
    if (uploadAmountOptions) {
        uploadAmountOptions.addEventListener('click', function(e) {
            const button = e.target.closest('button');
            if (!button) return;
            
            const amount = button.dataset.amount;
            if (!amount) return;
            
            // Disable all buttons and show loading
            const buttons = uploadAmountOptions.querySelectorAll('button');
            buttons.forEach(btn => btn.disabled = true);
            button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Buying...';
            
            fetch('/mam/buy_upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: amount === 'max' ? 'max' : parseFloat(amount) })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const amountText = amount === 'max' ? 'Maximum affordable' : `${amount} GB`;
                        const message = `Upload credit purchased! Added ${amountText}. Remaining bonus: ${data.seedbonus ? data.seedbonus.toFixed(2) : 'N/A'}`;
                        showToast(message, 'success');
                        loadMamUserData();
                        // Close modal
                        const modal = bootstrap.Modal.getInstance(document.getElementById('uploadPurchaseModal'));
                        if (modal) modal.hide();
                    } else {
                        showToast(data.error || 'Failed to purchase upload credit', 'danger');
                    }
                })
                .catch(error => {
                    console.error('Error buying upload credit:', error);
                    showToast('An error occurred while purchasing upload credit', 'danger');
                })
                .finally(() => {
                    // Re-enable all buttons
                    buttons.forEach((btn, idx) => {
                        btn.disabled = false;
                        // Restore original text
                        const amounts = [1, 2.5, 5, 10, 20, 100, 'max'];
                        const costs = [500, 1250, 2500, 5000, 10000, 50000, 'All BP'];
                        if (amounts[idx] === 'max') {
                            btn.innerHTML = `Max Affordable <span class="badge bg-secondary float-end">${costs[idx]}</span>`;
                        } else {
                            btn.innerHTML = `${amounts[idx]} GB <span class="badge bg-secondary float-end">${costs[idx].toLocaleString()} BP</span>`;
                        }
                    });
                });
        });
    }

    // Insufficient Buffer Modal - Buy Recommended Amount Handler
    const modalBuyRecommended = document.getElementById('modal-buy-recommended');
    if (modalBuyRecommended) {
        modalBuyRecommended.addEventListener('click', function() {
            const amount = parseFloat(this.dataset.amount);
            if (!amount) return;
            
            this.disabled = true;
            const originalText = this.innerHTML;
            this.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Buying...';
            
            fetch('/mam/buy_upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ amount: amount })
            })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        showToast(`Upload credit purchased! Added ${amount} GB`, 'success');
                        loadMamUserData();
                        
                        // Close insufficient buffer modal
                        const modal = bootstrap.Modal.getInstance(document.getElementById('insufficientBufferModal'));
                        if (modal) modal.hide();
                        
                        // Retry the original download if we stored it
                        if (window.pendingDownload) {
                            const pending = window.pendingDownload;
                            window.pendingDownload = null;
                            
                            fetch('/client/add', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify(pending)
                            })
                                .then(response => response.json())
                                .then(result => {
                                    if (result.message) {
                                        showToast(result.message, 'success');
                                    } else if (result.error) {
                                        showToast(result.error, 'danger');
                                    }
                                })
                                .catch(error => console.error('Error retrying download:', error));
                        }
                    } else {
                        showToast(data.error || 'Failed to purchase upload credit', 'danger');
                    }
                })
                .catch(error => {
                    console.error('Error buying upload credit:', error);
                    showToast('An error occurred while purchasing upload credit', 'danger');
                })
                .finally(() => {
                    this.disabled = false;
                    this.innerHTML = originalText;
                });
        });
    }

    searchForm.addEventListener("submit", function (e) {
        e.preventDefault();
        searchButton.disabled = true;
        searchButton.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Searching...`;

        if (resultsTitle) {
            resultsTitle.textContent = 'Results';
        }

        // Clear hash-to-element mappings before a new search
        console.log("[SEARCH] New search submitted. Clearing hash mappings.");
        hashToElementMap.clear();

        const queryParams = new URLSearchParams(new FormData(searchForm)).toString();

        fetch(`/mam/search?${queryParams}`)
            .then(response => response.text()) // Expect HTML now, not JSON
            .then(html => {
                wrapper.style.display = 'block'; // Make the results container visible
                resultsContainer.innerHTML = html;

                const resultsCount = resultsContainer.querySelectorAll('.result-item').length;
                if (resultsTitle) {
                    resultsTitle.textContent = `Results (${resultsCount})`;
                }

                wrapper.scrollIntoView({ behavior: 'smooth', block: 'start' });
                refreshCategories();
                initializeSnatchedTorrents();
            })
            .catch(error => {
                wrapper.style.display = 'block';
                resultsContainer.innerHTML = `<div class="alert alert-danger">Search failed. See console for details.</div>`;
                console.error("Error during search request:", error);
            })
            .finally(() => {
                searchButton.disabled = false;
                searchButton.innerHTML = "Search";
            });
    });

    resultsContainer.addEventListener('click', function (event) {
        // Find the button, even if the click was on an icon inside it
        const button = event.target.closest('.add-to-client-button');
        if (button) {
            event.preventDefault();
            // Find the result item first (needed to get torrentId and category)
            const resultItem = button.closest('.result-item');
            const torrentUrl = button.dataset.torrentUrl;
            const torrentId = resultItem.dataset.torrentId;
            const author = button.dataset.author;
            const title = button.dataset.title;
            const torrentSize = button.dataset.size || '0 GiB';  // Get size from button data
            // Find the category dropdown within the same result item
            const category = resultItem.querySelector('.category-dropdown')?.value || '';

            console.log(`[ADD] 'Download' clicked for URL: ${torrentUrl} with category: '${category}'`);

            button.disabled = true;
            
            const downloadData = {
                torrent_url: torrentUrl,
                category: category,
                id: torrentId,
                author: author,
                title: title,
                size: torrentSize
            };
            
            fetch('/client/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(downloadData),
            })
                .then(response => response.json())
                .then(async data => {
                    // Check for insufficient buffer
                    if (data.status === 'insufficient_buffer') {
                        // Show insufficient buffer modal
                        document.getElementById('modal-buffer-gb').textContent = data.buffer_gb || 0;
                        document.getElementById('modal-torrent-size').textContent = data.torrent_size_gb || 0;
                        document.getElementById('modal-needed-gb').textContent = data.needed_gb || 0;
                        document.getElementById('modal-recommended-amount').textContent = data.recommended_amount || 0;
                        document.getElementById('modal-recommended-cost').textContent = (data.recommended_cost || 0).toLocaleString();
                        
                        const buyButton = document.getElementById('modal-buy-recommended');
                        buyButton.dataset.amount = data.recommended_amount || 0;
                        
                        // Store the download data for retry after purchase
                        window.pendingDownload = downloadData;
                        
                        const modal = new bootstrap.Modal(document.getElementById('insufficientBufferModal'));
                        modal.show();
                        
                        button.disabled = false;
                        return;
                    }
                    
                    showToast(data.message || data.error, data.message ? 'success' : 'danger');
                    if (data.message) {
                        console.log("[ADD] Torrent added successfully via API.");
                        button.textContent = 'Added!';
                        // With MID-based matching, hash resolution happens in the monitoring loop
                        // Show a waiting state - SSE will update once hash is resolved
                        const statusContainer = resultItem.querySelector('.torrent-status-container');
                        if (statusContainer) {
                            statusContainer.innerHTML = `<span class="badge bg-info text-wrap">Resolving torrent...</span>`;
                        }
                        console.log(`[ADD] MID ${torrentId} added - hash will be resolved by monitoring loop`);
                        
                        // Poll for hash resolution (check every 2 seconds for up to 30 seconds)
                        let attempts = 0;
                        const maxAttempts = 15;
                        const pollInterval = setInterval(async () => {
                            attempts++;
                            const hash = await getTorrentHashByMID(torrentId);
                            if (hash) {
                                console.log(`[ADD] Hash resolved for MID ${torrentId}: ${hash}`);
                                clearInterval(pollInterval);
                                pollTorrentStatus(hash, resultItem);
                                fetchAndUpdateTorrentStatus(hash, resultItem);
                            } else if (attempts >= maxAttempts) {
                                console.log(`[ADD] Hash resolution timed out for MID ${torrentId}`);
                                clearInterval(pollInterval);
                                if (statusContainer) {
                                    statusContainer.innerHTML = `<span class="badge bg-warning text-wrap">Added (status pending)</span>`;
                                }
                            }
                        }, 2000);
                    } else {
                        console.error("[ADD] Failed to add torrent:", data.error);
                    }
                })
                .catch(error => {
                    showToast("An error occurred while adding torrent.", 'danger');
                    button.disabled = false;
                });
        }
    });
});