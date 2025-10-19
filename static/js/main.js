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

// Icon definitions using the provided base64 strings
const greenCheckIcon = `<img src="data:image/png;base64,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" alt="connected" style="height: 16px; width: 16px;">`;
const redXIcon = `<img src="data:image/png;base64,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" alt="not connected" style="height: 16px; width: 16px;">`;

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

        const queryParams = new URLSearchParams(new FormData(searchForm)).toString();

        fetch(`/mam/search?${queryParams}`)
            .then(response => response.text()) // Expect HTML now, not JSON
            .then(html => {
                wrapper.style.display = 'block'; // Make the results container visible
                resultsContainer.innerHTML = html;

                const resultsCount = resultsContainer.querySelectorAll('.row.my-3').length;
                if (resultsTitle) {
                    resultsTitle.textContent = `Results (${resultsCount})`;
                }
                
                wrapper.scrollIntoView({ behavior: 'smooth', block: 'start' });
                refreshCategories();
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
            const torrentUrl = button.dataset.torrentUrl;
            // Find the category dropdown within the same result item
            const category = button.closest('.col-12.col-md-3').querySelector('.category-dropdown')?.value || '';

            button.disabled = true;
            fetch('/qb/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({ torrent_url: torrentUrl, category: category }),
            })
            .then(response => response.json())
            .then(data => {
                showToast(data.message || data.error, data.message ? 'success' : 'danger');
                if(data.message) button.textContent = 'Added!';
            })
            .catch(error => {
                showToast("An error occurred while adding torrent.", 'danger');
                button.disabled = false;
            });
        }
    });
});