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

// New batch polling system
const activeHashes = new Set();
const hashToElementMap = new Map(); // Maps hash -> resultItem element
let batchPollingInterval = null;

async function getTorrentHash(torrentId, torrentUrl) {
    // 1. Check the cache using the STABLE torrent ID
    if (torrentHashMap[torrentId]) {
        console.log(`[CACHE] Found hash for ID ${torrentId}: ${torrentHashMap[torrentId]}`);
        return torrentHashMap[torrentId];
    }
    
    // 2. If not in cache, fetch it using the DYNAMIC URL
    try {
        console.log(`[API] Calculating hash for ID ${torrentId} using URL: ${torrentUrl}`);
        const response = await fetch('/calculate_hash', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: torrentUrl })
        });
        if (!response.ok) throw new Error('Backend failed to calculate hash');
        const data = await response.json();
        
        if (data.hash) {
            console.log(`[API] Successfully calculated hash: ${data.hash}`);
            // 3. Store the new hash in the cache with the STABLE ID as the key
            torrentHashMap[torrentId] = data.hash;
            return data.hash;
        } else {
            console.error(`[API] Hash calculation failed:`, data.error);
        }
    } catch (error) {
        console.error("Error getting torrent hash:", error);
    }
    return null;
}

/**
 * Performs a single batch poll of all active torrents.
 */
async function performBatchPoll() {
    if (activeHashes.size === 0) {
        console.log('[BATCH-POLL] No active hashes, stopping batch polling');
        stopBatchPolling();
        return;
    }
    
    const hashArray = Array.from(activeHashes);
    console.log(`[BATCH-POLL] Polling ${hashArray.length} torrent(s)`);
    
    try {
        const response = await fetch('/qb/info/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ hashes: hashArray })
        });
        
        if (!response.ok) {
            console.error(`[BATCH-POLL] HTTP error! status: ${response.status}`);
            return;
        }
        
        const data = await response.json();
        
        if (data.error) {
            console.error('[BATCH-POLL] Error from server:', data.error);
            return;
        }
        
        const torrents = data.torrents || {};
        
        // Update UI for each active hash
        for (const hash of hashArray) {
            const resultItem = hashToElementMap.get(hash);
            if (!resultItem) {
                console.warn(`[BATCH-POLL] No result item found for hash ${hash}`);
                continue;
            }
            
            const torrentData = torrents[hash];
            if (!torrentData) {
                // Torrent not found in qBittorrent
                const statusContainer = resultItem.querySelector('.torrent-status-container');
                if (statusContainer) {
                    statusContainer.innerHTML = `<span class="badge bg-danger text-wrap">Torrent not found in qBittorrent</span>`;
                }
                removeHashFromPolling(hash);
                continue;
            }
            
            updateTorrentUI(hash, torrentData, resultItem);
        }
        
    } catch (error) {
        console.error('[BATCH-POLL] Polling error:', error);
    }
}

/**
 * Starts the global batch polling interval if not already running.
 * Makes an immediate poll before starting the interval.
 */
function startBatchPolling() {
    if (batchPollingInterval !== null) {
        console.log('[BATCH-POLL] Batch polling already running');
        return;
    }
    
    console.log('[BATCH-POLL] Starting batch polling interval');
    
    // Make immediate poll before starting interval
    performBatchPoll();
    
    // Then start the interval
    batchPollingInterval = setInterval(performBatchPoll, 2000);
}

/**
 * Stops the global batch polling interval.
 */
function stopBatchPolling() {
    if (batchPollingInterval !== null) {
        console.log('[BATCH-POLL] Stopping batch polling interval');
        clearInterval(batchPollingInterval);
        batchPollingInterval = null;
    }
}

/**
 * Adds a hash to the active polling list.
 */
function addHashToPolling(hash, resultItem) {
    console.log(`[BATCH-POLL] Adding hash ${hash} to active polling`);
    activeHashes.add(hash);
    hashToElementMap.set(hash, resultItem);
    startBatchPolling();
}

/**
 * Removes a hash from the active polling list.
 */
function removeHashFromPolling(hash) {
    console.log(`[BATCH-POLL] Removing hash ${hash} from active polling`);
    activeHashes.delete(hash);
    hashToElementMap.delete(hash);
    if (activeHashes.size === 0) {
        stopBatchPolling();
    }
}

/**
 * Updates the UI for a specific torrent based on its data.
 */
function updateTorrentUI(hash, data, resultItem) {
    const statusContainer = resultItem.querySelector('.torrent-status-container');
    if (!statusContainer) {
        console.error(`[BATCH-POLL] Could not find status container for hash ${hash}`);
        return;
    }
    
    const state = data.state || 'unknown';
    const progress = ((data.progress || 0) * 100).toFixed(0);
    let badgeType;
    let simplifiedState = 'Unknown';
    
    // Simplified state mapping
    if (['error', 'missingFiles'].includes(state)) {
        simplifiedState = 'Error';
        badgeType = 'danger';
    } else if (['uploading', 'stalledUP', 'checkingUP', 'forcedUP', 'pausedUP'].includes(state)) {
        simplifiedState = 'Seeding';
        badgeType = 'success';
    } else if (['downloading', 'metaDL', 'stalledDL', 'checkingDL', 'forcedDL', 'allocating', 'moving', 'checkingResumeData'].includes(state)) {
        simplifiedState = 'Downloading';
        badgeType = 'primary';
    } else if (['pausedDL'].includes(state)) {
        simplifiedState = 'Paused';
        badgeType = 'secondary';
    } else if (['queuedUP', 'queuedDL'].includes(state)) {
        simplifiedState = 'Queued';
        badgeType = 'info';
    }
    
    const statusHtml = `
        <div class="small lh-sm">
            <div class="d-flex align-items-center">Status: <div class="badge bg-${badgeType} m-1"><b>${simplifiedState}</b></div></div>
            <div class="d-flex align-items-center">Downloaded: <div class="badge bg-${badgeType} m-1"><b>${progress}%</b></div></div>
        </div>
    `;
    statusContainer.innerHTML = statusHtml;
    
    // Stop polling on terminal states
    const terminalStates = ['error', 'missingFiles', 'uploading', 'pausedUP', 'stalledUP', 'forcedUP', 'pausedDL'];
    if (terminalStates.includes(state)) {
        console.log(`[BATCH-POLL] Stopping poll for hash ${hash} because its state is terminal: ${state}`);
        removeHashFromPolling(hash);
    }
}

/**
 * Initiates polling for a torrent by adding it to the batch polling system.
 * @param {string} hash - The torrent hash
 * @param {HTMLElement} resultItem - The DOM element for this result item
 */
function pollTorrentStatus(hash, resultItem) {
    const statusContainer = resultItem.querySelector('.torrent-status-container');
    if (!statusContainer) {
        console.error("Could not find status container for item:", resultItem);
        return;
    }

    console.log(`[POLL] Starting to poll status for hash: ${hash}`);
    
    // Add to batch polling system
    addHashToPolling(hash, resultItem);
}

/**
 * Checks the connection status of QBittorrent and updates the UI.
 */
function checkQBStatus() {
    const statusSpan = document.getElementById("qb-status");
    const statusIconSpan = document.getElementById("qb-status-icon");

    fetch('/qb/status', { cache: "no-store" })
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
            if (isSuccess) {
                refreshCategories();
            }
        })
        .catch(error => {
            console.error("Error fetching QB_STATUS:", error);
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
 * Refreshes qBittorrent categories and populates dropdowns.
 */
function refreshCategories() {
    fetch('/qb/categories', { cache: "no-store" })
        .then(response => response.json())
        .then(data => {
            const dropdowns = document.querySelectorAll('.category-dropdown');
            const defaultCategory = document.getElementById('QB_CATEGORY')?.value || '';
            dropdowns.forEach(dropdown => {
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
        const torrentUrl = item.dataset.torrentUrl;
        const torrentId = item.dataset.torrentId; // Get the new ID
        console.log("[INIT] Found snatched item:", item);
        if (torrentId && torrentUrl) {
            // Pass both arguments
            const hash = await getTorrentHash(torrentId, torrentUrl);
            if (hash) {
                pollTorrentStatus(hash, item);
            }
        }
    });
}

// --- Main Event Listeners ---
document.addEventListener("DOMContentLoaded", function () {
    const searchForm = document.getElementById("search-form");
    const resultsContainer = document.getElementById("results-container");
    const searchButton = document.getElementById("searchButton");
    const wrapper = document.getElementById('results-container-wrapper');
    const resultsTitle = document.getElementById('results-title');

    checkQBStatus();
    loadMamUserData();
    // setInterval(checkForIpUpdate, 30000);
    // checkForIpUpdate();

    document.getElementById('save-settings-button').addEventListener('click', function () {
        fetch('/update_settings', { method: 'POST', body: new FormData(document.getElementById('settings-form')) })
            .then(response => response.json())
            .then(data => {
                showToast(data.message, data.status === 'success' ? 'success' : 'danger');
                if (data.status === 'success') {
                    document.getElementById('qbLink').href = document.getElementById('QB_URL').value;
                    document.getElementById('qbLink').textContent = document.getElementById('QB_URL').value;
                    checkQBStatus();
                    loadMamUserData();
                }
            })
            .catch(error => showToast("An error occurred while saving settings.", 'danger'));
    });

    searchForm.addEventListener("submit", function (e) {
        e.preventDefault();
        searchButton.disabled = true;
        searchButton.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Searching...`;

        if (resultsTitle) {
            resultsTitle.textContent = 'Results';
        }

        // Clear all existing polling intervals before a new search
        console.log("[SEARCH] New search submitted. Clearing all active polling.");
        stopBatchPolling();
        activeHashes.clear();
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
        const button = event.target.closest('.add-to-qbittorrent-button');
        if (button) {
            event.preventDefault();
            // Find the result item first (needed to get torrentId and category)
            const resultItem = button.closest('.result-item');
            const torrentUrl = button.dataset.torrentUrl;
            const torrentId = resultItem.dataset.torrentId;
            const author = button.dataset.author;
            const title = button.dataset.title;
            // Find the category dropdown within the same result item
            const category = resultItem.querySelector('.category-dropdown')?.value || '';

            console.log(`[ADD] 'Add to qBittorrent' clicked for URL: ${torrentUrl} with category: '${category}'`);

            button.disabled = true;
            fetch('/qb/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    torrent_url: torrentUrl,
                    category: category,
                    author: author,
                    title: title
                }),
            })
                .then(response => response.json())
                .then(async data => {
                    showToast(data.message || data.error, data.message ? 'success' : 'danger');
                    if (data.message) {
                        console.log("[ADD] Torrent added successfully via API.");
                        button.textContent = 'Added!';
                        const hash = await getTorrentHash(torrentId, torrentUrl);
                        if (hash) {
                            pollTorrentStatus(hash, resultItem);
                        }
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
