# MouseSearch: AI Agent Instructions

## Project Overview

MouseSearch is a Flask web app for searching MyAnonamouse (MAM) torrents and sending them to qBittorrent. It's designed to run in Docker with persistent data storage and automated background tasks.

**Core Architecture:**
- Single-file Flask application (`app.py`) with ~750 lines handling all backend logic
- Session-based authentication for both MAM (cookies) and qBittorrent (session tokens)
- APScheduler for background jobs (IP updates, file organization)
- HTMX-style partial templates for dynamic search results
- Bootstrap 5 frontend with vanilla JavaScript

## Directory Structure

```
myanonamouse-docker/
├── app.py                  # Main Flask application (all backend logic)
├── language_dict.py        # MAM language ID mappings (60+ languages)
├── requirements.txt        # Python dependencies
├── package.json            # Frontend dependencies (Bootstrap, ESLint)
├── Dockerfile              # Container build definition
├── compose.yaml            # Docker Compose configuration
├── buildImage.sh           # Build script with versioning
├── .env                    # Environment variables (gitignored, user-created)
├── data/                   # Persistent storage (gitignored)
│   ├── config.json         # User settings from web UI
│   ├── ip_state.json       # Dynamic seedbox IP cache
│   ├── metadata.json       # Torrent hash → metadata mapping
│   └── organized/          # Auto-organized audiobooks (Author/Title/)
├── static/
│   ├── js/main.js          # Torrent polling, UI interactions
│   ├── style.css           # Custom styles
│   ├── bootstrap/          # Bootstrap 5 assets
│   └── icons/              # SVG icons
└── templates/
    ├── index.html          # Main page layout
    └── partials/
        └── results.html    # Search results template (HTMX-style)
```

## Development Environment Setup

### Prerequisites
- **Python 3.10+** (app uses modern syntax like `str | None`)
- **Docker & Docker Compose** (for containerized deployment)

### Local Development
```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install Python dependencies
pip install -r requirements.txt

# Create .env file with your credentials (see compose.yaml for required vars)
cp .env.example .env  # If example exists, or create manually

# Run development server
python app.py --host 0.0.0.0 --port 5000

# Production mode (with Gunicorn)
pip install gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 8 app:app
```

**Key Points:**
- Use `python3` explicitly (not `python`) for consistency across environments
- Virtual environment recommended but not required for Docker builds
- `data/` directory auto-created on first run if missing
- `.env` file may be used in bare metal and Docker environments

## Critical Configuration Patterns

### Config Loading Hierarchy (read `load_config()` carefully)
1. Environment variables (from Docker or `.env`)
2. Persistent `data/config.json` (written by web UI settings)
3. Hardcoded `FALLBACK_CONFIG` dictionary

**Key Insight:** MAM_UID auto-fetches from API if missing but MAM_ID exists. When modifying config logic, preserve this bootstrap behavior in `load_new_app_config()`.

### State Files (always in `/app/data/` when containerized)
- `config.json`: User-editable settings (QB/MAM credentials)
- `ip_state.json`: Last known dynamic seedbox IP
- `metadata.json`: Torrent hash → author/title mapping for organization
- `organized/`: Hardlinked audio files organized as `Author/Title/`

## External Service Integration

### MyAnonamouse API
- **Authentication:** Requires `mam_id` cookie AND `uid` (user ID)
- **Search endpoint:** `/tor/js/loadSearchJSONbasic.php` returns `dl` hash that must be joined with base URL
- **Critical:** Always call `update_cookies(response)` after API requests to maintain session
- **Dynamic IP:** `/json/dynamicSeedbox.php` endpoint updates tracker IP (called every 3 hours + on config save)

### qBittorrent API
- **Session Management:** Login creates session cookies stored in Flask session, expires frequently
- **Hash calculation:** Backend calculates torrent info_hash via bencodepy for status polling
- **Webhook endpoint:** `/organize/<hash>` called by qBittorrent on completion when AUTO_ORGANIZE=true

## File Organization Feature

**Activation:** Set `AUTO_ORGANIZE=true` in environment or config.

**Flow:**
1. User adds torrent → metadata saved with hash as key
2. qBittorrent downloads → calls webhook `/organize/<hash>` on completion
3. Backend hardlinks audio files from QB_PATH to `organized/Author/Title/`
4. Safety net job runs hourly to catch missed webhooks (retry limit: 3)

**Path Assumptions:**
- `QB_PATH` must match qBittorrent's download location
- Only audio extensions hardlinked: `.m4b`, `.mp3`, `.flac`, `.ogg`, `.opus`, `.m4a`
- Handles both single-file and directory torrents (see `_perform_organization()`)

## Development Workflows

### Running Locally
```bash
# Development with Flask
python app.py --host 0.0.0.0 --port 5000

# Production with Gunicorn (as in Dockerfile)
gunicorn --bind 0.0.0.0:5000 --workers 1 --threads 8 app:app
```

### Docker Build & Deploy
```bash
# Build script with semver tags
./buildImage.sh -v v0.1.2 -u sevenlayercookie

# Compose up (reads .env file for secrets)
docker compose up -d
```

**Volume Mounts:**
- `./data:/app/data` - Persists all state (config, metadata, organized files) between container restarts
- `/mnt/sda/audiobooks:/audiobooks/` - Host audiobook library accessible to container (adjust path for your setup). Contains both `organized/` and raw Qbittorrent downloads (on same volume so hard links can be created)

## JavaScript Conventions

### Torrent Status Polling (`main.js`)
- **Hash Caching:** `torrentHashMap` keyed by stable torrent ID (not URL which rotates)
- **Polling Lifecycle:** Starts on "Add to qBittorrent" click, cleared when torrent completes/errors
- **State Simplification:** Maps 15+ qBittorrent states to 5 UI states (Queued, Downloading, Seeding, Complete, Error)

### HTMX-Style Partial Updates
Search results (`/mam/search`) return only the `partials/results.html` template, which JavaScript inserts into `#results` div.

## Language Support

The `language_dict.py` maps 60+ language names to MAM API language IDs. When adding UI language filters, reference this dictionary - don't hardcode IDs.

## Security Notes

- **Secrets in Config:** `data/config.json` contains plaintext passwords (MAM_ID cookie, QB credentials)
- **Cloudflare Access:** Optional `CF_ACCESS_CLIENT_ID/SECRET` headers for Zero Trust setups
- **Session Keys:** `FLASK_SECRET_KEY` generates on first run if not provided (insecure for multi-container)

## Common Pitfalls

1. **Forgot to call `login_qbittorrent()`:** QB session expires - always check `qb_session` in Flask session first
2. **Torrent URL construction:** API returns `dl` hash only - must prepend `{MAM_API_URL}/tor/download.php/`
3. **Path mismatches:** QB_PATH must be container's view of qBittorrent download location (when containerized), not host path
4. **Scheduler jobs on reload:** APScheduler persists in memory - use `scheduler.get_job()` to check existence before adding
5. **File vs Directory handling:** Torrent content can be single file OR directory - check `content_path.is_dir()`

## Testing Changes

No automated tests exist. Manual validation checklist:
1. Search returns results with thumbnails
2. "Add to qBittorrent" creates download + starts polling
3. Status badge updates (check console logs for hash calculation)
4. Settings save persists after container restart
5. If AUTO_ORGANIZE: verify hardlinks appear in `ORGANIZED_PATH` after completion
