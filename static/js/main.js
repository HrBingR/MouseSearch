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

/**
 * Checks the connection status of QBittorrent and updates the UI.
 */
function checkQBStatus() {
    fetch('/qb/status', { cache: "no-store" })
        .then(response => response.json())
        .then(data => {
            const statusSpan = document.querySelector("#qbAccordionCollapse span");
            if (statusSpan) {
                statusSpan.textContent = data.status === "success" ? "CONNECTED" : "NOT CONNECTED";
                statusSpan.className = data.status === "success" ? "text-success" : "text-danger";
            }
            if (data.status === "success") {
                refreshCategories();
            }
        })
        .catch(error => console.error("Error fetching QB_STATUS:", error));
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
                }
            })
            .catch(error => showToast("An error occurred while saving settings.", 'danger'));
    });

    searchForm.addEventListener("submit", function (e) {
        e.preventDefault();
        searchButton.disabled = true;
        searchButton.innerHTML = `<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> Searching...`;

        const queryParams = new URLSearchParams(new FormData(searchForm)).toString();
        
        // ##### THIS IS THE CORRECTED LINE #####
        fetch(`/mam/search?${queryParams}`)
            .then(response => response.text()) // Expect HTML now, not JSON
            .then(html => {
                resultsContainer.innerHTML = html;
                wrapper.scrollIntoView({ behavior: 'smooth', block: 'start' });
                refreshCategories();
                const tooltipTriggerList = resultsContainer.querySelectorAll('[data-bs-toggle="tooltip"]');
                [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
            })
            .catch(error => {
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