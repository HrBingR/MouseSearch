# MouseSearch

MouseSearch is a self-hosted web application that provides a clean, fast search interface for MyAnonamouse (MAM). It connects directly to the MAM API for searching and the qBittorrent Web API for one-click downloading, bridging the gap between your favorite tracker and your download client.



## Key Features

* **MAM Search:** Full-text search for torrents on MyAnonamouse.
* **Advanced Filtering:** Filter by title, author, narrator, media type, language, and advanced tracker filters (e.g., Freeleech, VIP, Active).
* **One-Click Downloading:** Send torrents directly to your qBittorrent client, assigning a category from the UI.
* **Live Status Dashboards:**
    * View your MAM user stats (username, ratio, bonus points, etc.) directly in the app.
    * Check the connection status to both MAM and to qBittorrent.
* **Dynamic IP Updater:** Automatically checks your server's public IP and updates MAM's "Dynamic Seedbox IP" setting if a change is detected. This is ideal for home servers with dynamic IPs.
* **Live Torrent Polling:** After adding a torrent, the UI polls qBittorrent to show its download status (e.g., "Downloading 50%", "Seeding") in real-time. Designates previously downloaded torrents as "Downloaded".
* **[BETA] Auto-Organization:** (See details below) Automatically hard-links completed audiobooks from your download folder to a clean, organized library structure (e.g., `Author/Title/file.m4b`).

## Technology Stack

* **Backend:** **Quart**
* **Frontend:** **Bootstrap 5** & JavaScript
* **Containerization:** **Docker**
* **APIs:** MyAnonamouse (MAM) & qBittorrent

## Installation & Configuration

The recommended setup is using Docker Compose.

### 1. Prerequisites

* Docker

### 2. Prepare the Project

1.  Clone this repository:
    '''bash
    git clone https://github.com/sevenlayercookie/MouseSearch.git
    cd MouseSearch
    '''

2.  Create your environment file from the example:
    '''bash
    cp .env.example .env
    '''

### 3. Configure Your Environment (`.env`)

Open the `.env` file you just created and fill in the details.

| Variable | Required | Description |
| :--- | :--- | :--- |
| `FLASK_SECRET_KEY` | **Yes** | A long, random string for session security. You can generate one with `openssl rand -hex 32` (or just smash on the keyboard a bit) |
| `MAM_ID` | **Yes** | Your `mam_id` cookie value from [MyAnonamouse](https://www.myanonamouse.net/preferences/index.php?view=security). |
| `QB_URL` | **Yes** | The full URL to your qBittorrent WebUI (e.g., `http://192.168.1.10:8080` or `http://qbittorrent:6767` if on the same Docker network). |
| `QB_USERNAME` | **Yes** | Your qBittorrent username. |
| `QB_PASSWORD` | **Yes** | Your qBittorrent password. |
| `QB_CATEGORY` | No | (Optional) A default category to assign to downloads (e.g., `audiobooks`). |
| `DATA_PATH` | No | Directory path for storing app data files (config.json, metadata.json, ip_state.json). Defaults to `./data`. |
| `ENABLE_DYNAMIC_IP_UPDATE` | No | Set to `true` to enable automatic IP checking and updating of MAM's "Dynamic Seedbox IP" setting. Defaults to `false`. |
| `DYNAMIC_IP_UPDATE_INTERVAL_HOURS` | No | Number of hours between automatic IP checks (only applies if `ENABLE_DYNAMIC_IP_UPDATE` is `true`). Defaults to `3`. |
| `AUTO_ORGANIZE_ON_ADD` | No | Set to `true` to enable auto-organization when torrents are added. Defaults to `false`. |
| `AUTO_ORGANIZE_ON_SCHEDULE` | No | Set to `true` to enable scheduled auto-organization (runs every hour). Defaults to `false`. |
| `ORGANIZED_PATH` | If auto-organization is enabled | The *container* path for your organized library (e.g., `/downloads/organized/audiobooks`). |
| `QB_PATH` | If auto-organization is enabled | The *container* path where qBittorrent saves completed files for this category (e.g., `/downloads/torrents/organize-these/audiobooks`). |

**How to find your `MAM_ID`:**
1.  Log in to MyAnonamouse in your browser.
2.  Open your browser's developer tools (F12).
3.  Go to the "Application" (Chrome/Edge) or "Storage" (Firefox) tab.
4.  Select "Cookies" -> `https://www.myanonamouse.net`.
5.  Find the cookie named `mam_id` and copy its "Value".

### 4. Configure `compose.yaml`

Your `compose.yaml` file tells Docker how to run the app and, most importantly, where your files are. You **must** map your download and data directories.

Here is a recommended `compose.yaml`:

```yaml
services:
  mousesearch:
    build: .
    container_name: mousesearch
    restart: unless-stopped
    ports:
      # Maps port 5000 on your host to port 5000 in the container
      - "5000:5000"
    env_file: .env
    volumes:
      # Persists the app's internal config, metadata, and IP state
      - ./data:/app/data

      # --- CRITICAL for Auto-Organize ---
      # Map your *entire* downloads directory to /downloads in the container.
      # This single mount point ensures hard links will work.
      #
      # Example: If your downloads are in /mnt/storage/downloads on the host:
      - /mnt/storage/downloads:/downloads
      
      #
      # If your paths are separate, you MUST ensure they are on the 
      # same physical device and mount them accordingly.
      # The single-mount method above is strongly preferred.
      # ---
    
    # Optional: Set the container's timezone to match your host
    environment:
      - TZ=America/New_York
```

### 5. Run the Application

With your `.env` and `compose.yaml` files configured, start the application:

```bash
docker compose up -d
```

The application will be available at `http://<your-server-ip>:5000`.

## Usage

1.  Open the application in your browser.
2.  The app will show "NOT CONNECTED" for MAM and qBittorrent. The app's settings can be configured live from the UI, but using the `.env` file is recommended for persistence.
3.  If your `.env` is set up correctly, the dashboards should automatically update to "CONNECTED" and populate your user info.
4.  Use the search bar to find content.
5.  In the results, select a qBittorrent category (if desired) and click "Add to qBittorrent".
6.  The torrent will be added, and a status badge will appear, polling qBittorrent for live progress.

---

## [BETA] Auto-Organization Feature

**Note:** This feature is in beta. Please back up your `metadata.json` file and test with a few torrents first.

This feature is designed to automate your media library. When enabled, it hard-links completed audio files from your "messy" download directory into a "clean" library directory, sorted by `Author/Title`.

It **uses hard links**, not copies. This means it takes up **no additional disk space**.

### Configuration Options

You can now control two separate aspects of auto-organization:

- **`AUTO_ORGANIZE_ON_ADD`**: Automatically organize files when torrents are added to qBittorrent
- **`AUTO_ORGANIZE_ON_SCHEDULE`**: Periodically check for unorganized files (runs every hour)

These can be enabled independently of each other:
- Enable only `AUTO_ORGANIZE_ON_ADD` for immediate organization when files are added
- Enable only `AUTO_ORGANIZE_ON_SCHEDULE` for batch processing on a schedule
- Enable both for maximum coverage (recommended)

### How It Works

1.  When `AUTO_ORGANIZE_ON_ADD` is enabled and you add a torrent, MouseSearch calculates its infohash and saves the Author/Title metadata to `/app/data/metadata.json`.
2.  When `AUTO_ORGANIZE_ON_SCHEDULE` is enabled, the app includes a scheduler that runs every hour to check for unorganized files.
3.  Both methods check `metadata.json` for any torrents marked as `organized: false`.
4.  For each unorganized torrent, it:
    a.  Asks qBittorrent for its file path (e.g., `/downloads/torrents/organize-these/audiobooks/Some.Book.by.Some.Author`).
    b.  Sanitizes the Author ("Some Author") and Title ("Some Book").
    c.  Creates the destination path: `/downloads/organized/audiobooks/Some Author/Some Book`.
    d.  Scans the source directory for audio files (`.m4b`, `.mp3`, etc.) and hard-links each one to the destination.
    e.  Marks the torrent as `organized: true` in `metadata.json`.

### Critical Setup Requirement

For hard links to work, your source (`QB_PATH`) and destination (`ORGANIZED_PATH`) directories **must exist on the same filesystem**.

The easiest way to ensure this is to have a single parent directory (e.g., `/mnt/storage/downloads`) on your host machine that contains *both* your torrents and your organized media. You then pass this single parent directory as a volume in your `compose.yaml`, as shown in the example.

**Correct `.env` and Host Path Example:**

* **Host Path:** `/mnt/storage/downloads`
* **Volume Mount:** `- /mnt/storage/downloads:/downloads`
* **.env `QB_PATH`:** `/downloads/torrents/organize-these/audiobooks`
* **.env `ORGANIZED_PATH`:** `/downloads/organized/audiobooks`

This setup guarantees that both container paths point to the same underlying device, allowing hard links to be created.
