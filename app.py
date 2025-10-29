# app.py - Quart (async) version
from quart import Quart, request, render_template, Response, jsonify, session
import httpx
import json
import argparse
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from httpx import RequestError, Limits, Timeout, AsyncHTTPTransport
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import hashlib
import bencodepy

import re
from pathlib import Path

import logging # for hypercorn logging
import sys # for stderr logging

from language_dict import language_dict

import asyncio


        

# --- SCHEDULER AND STATE SETUP ---
app = Quart(__name__)

UPSTREAM_CLIENT: httpx.AsyncClient | None = None

@app.before_serving
async def startup():
    await load_new_app_config()
    # Start scheduler...
    if not scheduler.running:
        scheduler.start()
        app.logger.info("AsyncIOScheduler started")

    # ---- Create a single shared httpx client ----
    global UPSTREAM_CLIENT
    transport = AsyncHTTPTransport(http2=True, retries=2)
    limits = Limits(max_connections=200, max_keepalive_connections=50, keepalive_expiry=120.0)
    timeout = Timeout(connect=5.0, read=15.0, write=15.0, pool=None)
    UPSTREAM_CLIENT = httpx.AsyncClient(transport=transport, limits=limits, timeout=timeout)
    app.logger.info("Shared httpx AsyncClient initialized")

@app.after_serving
async def shutdown():
    if scheduler.running:
        scheduler.shutdown()
        app.logger.info("AsyncIOScheduler shutdown")

    # ---- Close the shared client ----
    global UPSTREAM_CLIENT
    if UPSTREAM_CLIENT is not None:
        await UPSTREAM_CLIENT.aclose()
        UPSTREAM_CLIENT = None
        app.logger.info("Shared httpx AsyncClient closed")
        
        
        
# Configure logging to stderr so it shows up in Hypercorn output
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stderr
)

if __name__ != '__main__':
    # Hypercorn logging setup (similar to gunicorn)
    logger = logging.getLogger('hypercorn.error')
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logging.INFO)
else:
    # When running directly, also log to stderr
    app.logger.setLevel(logging.INFO)

# Initialize AsyncIO scheduler for Quart (but don't start it yet)
scheduler = AsyncIOScheduler()

@app.before_serving
async def startup():
    """Start the scheduler and load config when the app starts serving requests."""
    # Load config
    await load_new_app_config()
    
    # Start the scheduler
    if not scheduler.running:
        scheduler.start()
        app.logger.info("AsyncIOScheduler started")

@app.after_serving
async def shutdown():
    """Shutdown the scheduler when the app stops serving."""
    if scheduler.running:
        scheduler.shutdown()
        app.logger.info("AsyncIOScheduler shutdown")

load_dotenv()

# Define fallback values
FALLBACK_CONFIG = {
    "QUART_SECRET_KEY": os.urandom(24).hex(),
    "MAM_API_URL": "https://www.myanonamouse.net",
    "QB_URL": "http://localhost:8080",
    "QB_CATEGORY": "",
    "QB_USERNAME": "admin",
    "QB_PASSWORD": "",
    "MAM_ID": "",
    "CF_ACCESS_CLIENT_ID": None,
    "CF_ACCESS_CLIENT_SECRET": None,
    "DATA_PATH": "./data",
    "ORGANIZED_PATH": "/downloads/organized",
    "QB_PATH": "/downloads/torrents/organize-these/audiobooks",
    "AUTO_ORGANIZE_ON_ADD": False,
    "AUTO_ORGANIZE_ON_SCHEDULE": False,
}

# Set up data directory and paths
DATA_PATH = Path(os.getenv("DATA_PATH", FALLBACK_CONFIG["DATA_PATH"])).resolve()
ORGANIZED_PATH = Path(os.getenv("ORGANIZED_PATH", FALLBACK_CONFIG["ORGANIZED_PATH"])).resolve()
QB_PATH = Path(os.getenv("QB_PATH", FALLBACK_CONFIG["QB_PATH"])).resolve()

# Create data directory if it doesn't exist
DATA_PATH.mkdir(parents=True, exist_ok=True)

# Define JSON file paths within DATA_PATH
CONFIG_FILE = DATA_PATH / "config.json"
METADATA_FILE = DATA_PATH / "metadata.json"
IP_STATE_FILE = DATA_PATH / "ip_state.json"

def load_config():
    config = FALLBACK_CONFIG.copy()
    env_config = {key: os.getenv(key) for key in config.keys()}
    env_config_filtered = {k: v for k, v in env_config.items() if v is not None}
    config.update(env_config_filtered)
    
    # Handle new configuration options
    auto_organize_on_add_str = str(config.get("AUTO_ORGANIZE_ON_ADD", "false")).lower()
    config["AUTO_ORGANIZE_ON_ADD"] = auto_organize_on_add_str in ['true', '1', 'yes', 'on']
    
    auto_organize_on_schedule_str = str(config.get("AUTO_ORGANIZE_ON_SCHEDULE", "false")).lower()
    config["AUTO_ORGANIZE_ON_SCHEDULE"] = auto_organize_on_schedule_str in ['true', '1', 'yes', 'on']
    
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            try:
                config.update(json.load(f))
            except json.JSONDecodeError:
                app.logger.warning(f"Could not decode {CONFIG_FILE}.")
    return config

def save_config(config):
    # Ensure only known keys are saved to prevent complex objects from being written
    config_to_save = {key: config.get(key) for key in FALLBACK_CONFIG.keys()}
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_to_save, f, indent=4)

def initialize_config():
    """Initialize config.json if it doesn't exist by merging env vars with fallback config."""
    if not CONFIG_FILE.exists():
        initial_config = load_config()
        save_config(initial_config)
        print(f"Initialized {CONFIG_FILE} with default configuration.")

# Initialize config.json on startup
initialize_config()

async def load_new_app_config():
    """Reload config from files and environment."""
    new_config = load_config()

    # Continue loading config into the app
    app.secret_key = new_config["QUART_SECRET_KEY"]
    app.config.update(new_config)
    
    app.config["BASE_HEADERS"] = {
        "CF-Access-Client-Id": new_config.get("CF_ACCESS_CLIENT_ID"),
        "CF-Access-Client-Secret": new_config.get("CF_ACCESS_CLIENT_SECRET"),
    }
    app.config["BASE_HEADERS"] = {k: v for k, v in app.config["BASE_HEADERS"].items() if v is not None}
    
    global mam_session_cookies
    mam_session_cookies = {"mam_id": app.config.get("MAM_ID")}

# Load initial config synchronously
initial_config = load_config()
app.secret_key = initial_config["QUART_SECRET_KEY"]
app.config.update(initial_config)
app.config["BASE_HEADERS"] = {
    "CF-Access-Client-Id": initial_config.get("CF_ACCESS_CLIENT_ID"),
    "CF-Access-Client-Secret": initial_config.get("CF_ACCESS_CLIENT_SECRET"),
}
mam_session_cookies = {"mam_id": initial_config.get("MAM_ID")}

# --- IP STATE MANAGEMENT AND DYNAMIC IP UPDATER ---

def load_ip_state():
    """Loads the last known IP from the state file."""
    if os.path.exists(IP_STATE_FILE):
        try:
            with open(IP_STATE_FILE, "r") as f:
                return json.load(f).get("last_ip")
        except (json.JSONDecodeError, FileNotFoundError):
            app.logger.warning(f"Could not read or parse {IP_STATE_FILE}.")
    return None

def save_ip_state(ip):
    """Saves the current IP to the state file."""
    with open(IP_STATE_FILE, "w") as f:
        json.dump({"last_ip": ip}, f, indent=4)

async def force_update_ip():
    """Directly calls the MAM dynamic seedbox API to update the IP, bypassing change checks."""
    async with app.app_context():
        app.logger.info("Forcing manual IP update for dynamic seedbox.")

        if not app.config.get("MAM_ID"):
            app.logger.warning("MAM_ID not set in config. Skipping manual IP update.")
            return

        api_cookies = {"mam_id": app.config.get("MAM_ID")}

        try:
            update_url = "https://t.myanonamouse.net/json/dynamicSeedbox.php"
            async with httpx.AsyncClient() as client:
                update_response = await client.get(update_url, cookies=api_cookies, timeout=15)
                update_response.raise_for_status()
                update_data = update_response.json()

                msg = update_data.get("msg")
                success = update_data.get("Success")

                if success and msg and msg.lower() in ["completed", "no change"]:
                    app.logger.info(f"Successfully triggered dynamic seedbox IP update. API Message: '{msg}'")
                    if new_ip := update_data.get("ip"):
                        save_ip_state(new_ip)  # Keep state file in sync
                else:
                    app.logger.error(f"Failed to trigger dynamic seedbox IP update. API Message: '{msg}' (Success: {success})")

        except (RequestError, json.JSONDecodeError) as e:
            app.logger.error(f"Error calling dynamic seedbox update API during manual trigger: {e}")

async def check_and_update_ip():
    """Periodically checks public IP and updates MAM's dynamic seedbox IP if it has changed."""
    async with app.app_context():
        app.logger.info("Running scheduled job: Check and Update IP.")
        
        if not app.config.get("MAM_ID"):
            app.logger.warning("MAM_ID not set in config. Skipping dynamic IP update.")
            return

        api_cookies = {"mam_id": app.config.get("MAM_ID")}
        
        try:
            ip_check_url = f"{app.config.get('MAM_API_URL')}/json/jsonIp.php"
            async with httpx.AsyncClient() as client:
                response = await client.get(ip_check_url, cookies=api_cookies, timeout=10)
                response.raise_for_status()
                current_ip = response.json().get("ip")
                if not current_ip:
                    app.logger.error("IP check API did not return an IP address.")
                    return
        except (RequestError, json.JSONDecodeError) as e:
            app.logger.error(f"Failed to get current IP from MAM API: {e}")
            return
            
        last_ip = load_ip_state()
        app.logger.info(f"Current IP: {current_ip}, Last known IP: {last_ip}")

        if current_ip == last_ip:
            app.logger.info("IP address has not changed. No update needed.")
            return

        app.logger.info(f"IP address has changed from {last_ip} to {current_ip}. Updating dynamic seedbox IP.")
        await force_update_ip()

# Schedule the IP check to run every 3 hours and 5 seconds after startup
scheduler.add_job(check_and_update_ip, 'interval', hours=3, id='ip_check_job', replace_existing=True)
scheduler.add_job(check_and_update_ip, 'date', run_date=datetime.now() + timedelta(seconds=5), id='initial_ip_check_job')

# --- SESSION AND API HELPERS ---
QB_SESSION = None

def update_cookies(response):
    """Extract and update cookies from the API response."""
    global mam_session_cookies
    if "set-cookie" in response.headers:
        cookies = dict(response.cookies)
        mam_session_cookies.update(cookies)

async def login_mam():
    url = app.config.get("MAM_API_URL")
    if not url: return False
    if not mam_session_cookies.get("mam_id"):
        return False
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{url}/jsonLoad.php", cookies=mam_session_cookies)
        if response.status_code == 200:
            if new_cookies := dict(response.cookies):
                mam_session_cookies.update(new_cookies)
            return True
    return False

async def login_qbittorrent():
    qb_url, username, password = app.config.get("QB_URL"), app.config.get("QB_USERNAME"), app.config.get("QB_PASSWORD")
    if not all([qb_url, username, password]): return False
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{qb_url}/api/v2/auth/login", 
                data={'username': username, 'password': password}, 
                headers=app.config.get("BASE_HEADERS", {})
            )
            if "Ok" in response.text:
                session['qb_session'] = dict(response.cookies)
                return True
    except RequestError: 
        return False
    return False

# --- QUART ROUTES ---
@app.route('/mam/status', methods=['GET'])
async def mam_status(): 
    return jsonify({'status': 'connected' if await login_mam() else 'not connected'})

@app.route('/mam/user_data', methods=['GET'])
async def mam_user_data():
    """Fetches user data from the MAM API."""
    if not await login_mam():
        return jsonify({'error': 'Not logged into MAM'}), 401

    try:
        api_url = f"{app.config.get('MAM_API_URL')}/jsonLoad.php"
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, cookies=mam_session_cookies, timeout=10)
            update_cookies(response)
            response.raise_for_status()
            
            user_data = response.json()
            
            # Optionally format numbers for better display
            if seedbonus := user_data.get("seedbonus"):
                user_data["seedbonus_formatted"] = f"{seedbonus:,}"

            return jsonify(user_data)

    except (RequestError, json.JSONDecodeError) as e:
        app.logger.error(f"Failed to fetch MAM user data: {e}")
        return jsonify({'error': 'Failed to fetch data from MAM API'}), 503
    
# --- QBITTORRENT ROUTES ---
@app.route('/qb/status', methods=['GET'])
async def qb_status():
    if 'qb_session' not in session and not await login_qbittorrent():
        return jsonify({"status": "error", "message": "Unable to connect to qBittorrent."}), 503
    try:
        async with httpx.AsyncClient(cookies=session['qb_session']) as client:
            response = await client.get(
                f"{app.config['QB_URL']}/api/v2/app/version", 
                headers=app.config.get("BASE_HEADERS", {})
            )
            response.raise_for_status()
            return jsonify({"status": "success", "message": "qBittorrent is connected."}), 200
    except RequestError as e:
        return jsonify({"status": "error", "message": f"Failed to connect: {e}"}), 503

@app.route('/qb/categories', methods=['GET'])
async def qb_categories():
    if 'qb_session' not in session and not await login_qbittorrent():
        return jsonify({'error': 'Not connected to qBittorrent'}), 401
    async with httpx.AsyncClient(cookies=session['qb_session']) as client:
        response = await client.get(
            f"{app.config['QB_URL']}/api/v2/torrents/categories", 
            headers=app.config.get("BASE_HEADERS", {})
        )
        return jsonify(response.json()) if response.is_success else (jsonify({'error': 'Failed to fetch categories'}), response.status_code)

@app.route('/qb/add', methods=['POST'])
async def qb_add_torrent():
    if 'qb_session' not in session and not await login_qbittorrent():
        return jsonify({'error': 'Not connected to qBittorrent'}), 401

    incoming_data = await request.get_json()
    if not incoming_data:
        app.logger.error("Received empty or non-JSON payload for /qb/add")
        return jsonify({'error': 'Invalid request: No JSON body found'}), 400

    app.logger.info(f"Received /qb/add request with payload: {incoming_data}")

    torrent_url = incoming_data.get('torrent_url') or incoming_data.get('url')
    author = incoming_data.get('author', 'Unknown Author')
    title = incoming_data.get('title', 'Unknown Title')
    id = incoming_data.get('id', '0')
    
    auto_organize_warning = None  # Track if hash calculation failed
    
    if app.config.get("AUTO_ORGANIZE_ON_ADD"):
        hash_val = await calculate_torrent_hash_from_url(torrent_url)
        if not hash_val:
            auto_organize_warning = "Unable to calculate torrent hash - auto-organization on add will not work for this torrent."
            app.logger.warning(f"AUTO_ORGANIZE_ON_ADD is enabled, but could not calculate hash for {torrent_url}.")
        else:
            metadata = load_metadata()
            metadata[hash_val] = {
                "id": id,
                "author": author,
                "title": title,
                "added_on": datetime.now().isoformat(),
                "organized": False,
                "retry_count": 0
            }
            save_metadata(metadata)
            app.logger.info(f"Saved metadata for torrent hash: {hash_val}")
    
    # --- The rest of the function remains the same ---
    category = incoming_data.get('category', app.config.get("QB_CATEGORY", ""))
    qb_url = app.config['QB_URL']
    payload = {'urls': torrent_url, 'category': category}
    custom_headers = app.config.get("BASE_HEADERS", {}).copy()
    custom_headers['Referer'] = qb_url

    try:
        app.logger.info(f"Attempting to add torrent via URL to qBittorrent: {torrent_url}")
        async with httpx.AsyncClient(cookies=session['qb_session']) as client:
            response = await client.post(f"{qb_url}/api/v2/torrents/add", data=payload, headers=custom_headers)
            response.raise_for_status()

            if "Ok." in response.text:
                app.logger.info("SUCCESS: Torrent added to qBittorrent.")
                response_data = {'message': 'Torrent added successfully'}
                if auto_organize_warning:
                    response_data['warning'] = auto_organize_warning
                return jsonify(response_data)
            else:
                error_message = f"qBittorrent rejected the torrent. Response: {response.text or '[No Response Body]'}"
                app.logger.error(error_message)
                return jsonify({'error': error_message}), 400

    except RequestError as e:
        app.logger.error(f"Failed to send 'add torrent' request to qBittorrent: {e}")
        return jsonify({'error': f'Failed to communicate with qBittorrent: {e}'}), 503
    
def load_metadata():
    """Loads the torrent metadata store."""
    if not os.path.exists(METADATA_FILE):
        return {}
    try:
        with open(METADATA_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def save_metadata(data):
    """Saves the torrent metadata store."""
    with open(METADATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def sanitize_filename(name: str) -> str:
    """Removes characters that are invalid for directory or file names."""
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    sanitized = sanitized.strip('. ')
    return sanitized if sanitized else "Untitled"

    
@app.route('/qb/info/<hash_val>', methods=['GET'])
async def qb_torrent_info(hash_val):
    app.logger.info(f"Request received for torrent info with hash: {hash_val}")
    if 'qb_session' not in session and not await login_qbittorrent():
        app.logger.error("Failed to get torrent info: Not connected to qBittorrent.")
        return jsonify({'error': 'Not connected to qBittorrent'}), 401
    
    try:
        # --- FIX: Call the /info endpoint, not /properties ---
        # Note the parameter is 'hashes' (plural)
        async with httpx.AsyncClient(cookies=session['qb_session']) as client:
            response = await client.get(
                f"{app.config['QB_URL']}/api/v2/torrents/info",
                params={'hashes': hash_val},
                headers=app.config.get("BASE_HEADERS", {})
            )
            response.raise_for_status()
            
            # The /info endpoint returns a LIST of torrents.
            torrent_list = response.json()
            app.logger.debug(f"Received info for hash {hash_val}: {json.dumps(torrent_list)}")
            
            # If the list is empty, the torrent doesn't exist in the client.
            if not torrent_list:
                 app.logger.warning(f"qBittorrent returned no info for hash {hash_val}. Torrent may not exist in client.")
                 return jsonify({'error': 'Torrent not found in qBittorrent'}), 404

            # Return the first (and only) object from the list.
            return jsonify(torrent_list[0])
        
    except RequestError as e:
        app.logger.error(f"Failed to fetch torrent info for hash {hash_val}: {e}")
        return jsonify({'error': f'Failed to fetch torrent info: {e}'}), 503
    except json.JSONDecodeError as e:
        app.logger.error(f"Failed to decode qBittorrent info response for hash {hash_val}: {e}")
        return jsonify({'error': 'Failed to decode response from qBittorrent'}), 500

@app.route('/qb/info/batch', methods=['POST'])
async def qb_torrent_info_batch():
    """
    Batch endpoint for getting torrent info for multiple hashes at once.
    Accepts: {"hashes": ["hash1", "hash2", ...]}
    Returns: {"torrents": [{torrent1_data}, {torrent2_data}, ...]}
    """
    data = await request.get_json()
    hash_list = data.get('hashes', [])
    
    if not hash_list:
        return jsonify({'torrents': []})
    
    app.logger.info(f"Batch request received for {len(hash_list)} torrent(s)")
    
    if 'qb_session' not in session and not await login_qbittorrent():
        app.logger.error("Failed to get batch torrent info: Not connected to qBittorrent.")
        return jsonify({'error': 'Not connected to qBittorrent'}), 401
    
    try:
        # Join hashes with pipe separator as per qBittorrent API spec
        hashes_param = '|'.join(hash_list)
        
        async with httpx.AsyncClient(cookies=session['qb_session']) as client:
            response = await client.get(
                f"{app.config['QB_URL']}/api/v2/torrents/info",
                params={'hashes': hashes_param},
                headers=app.config.get("BASE_HEADERS", {})
            )
            response.raise_for_status()
            
            torrent_list = response.json()
            app.logger.debug(f"Received batch info for {len(torrent_list)} torrent(s)")
            
            # Return the list of torrents indexed by hash for easy lookup
            torrents_by_hash = {t['hash']: t for t in torrent_list}
            return jsonify({'torrents': torrents_by_hash})
        
    except RequestError as e:
        app.logger.error(f"Failed to fetch batch torrent info: {e}")
        return jsonify({'error': f'Failed to fetch batch torrent info: {e}'}), 503
    except json.JSONDecodeError as e:
        app.logger.error(f"Failed to decode qBittorrent batch info response: {e}")
        return jsonify({'error': 'Failed to decode response from qBittorrent'}), 500

@app.route('/calculate_hash', methods=['POST'])
async def get_torrent_hash():
    data = await request.get_json()
    url = data.get('url')
    app.logger.info(f"Received request to calculate hash for URL: {url}")
    if not url:
        app.logger.error("Hash calculation failed: No URL provided.")
        return jsonify({'error': 'URL is required'}), 400
    
    hash_val = await calculate_torrent_hash_from_url(url)
    
    if hash_val:
        app.logger.info(f"Successfully calculated hash for {url}: {hash_val}")
        return jsonify({'hash': hash_val})
    else:
        app.logger.error(f"Failed to calculate hash for URL: {url}")
        return jsonify({'error': 'Failed to calculate hash'}), 500

# torrent hash calculation utility
async def calculate_torrent_hash_from_url(url: str) -> str | None:
    """
    Downloads a .torrent file from a URL and calculates its info hash.
    """
    try:
        app.logger.debug(f"Fetching .torrent file from: {url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            
            torrent_content = response.content
            torrent_data = bencodepy.decode(torrent_content)
            
            if b'info' not in torrent_data:
                app.logger.error("'info' dictionary not found in torrent file.")
                return None
                
            info_dict = torrent_data[b'info']
            bencoded_info = bencodepy.encode(info_dict)
            sha1_hash = hashlib.sha1(bencoded_info).hexdigest()
            
            return sha1_hash

    except RequestError as e:
        app.logger.error(f"Error fetching the URL for hash calculation: {e}")
        return None
    except bencodepy.BencodeDecodeError as e:
        app.logger.error(f"Error decoding the torrent file for hash calculation: {e}")
        return None
    except Exception as e:
        app.logger.error(f"An unexpected error occurred during hash calculation: {e}")
        return None

def parse_author_info(info):
    try: return ", ".join(json.loads(info).values())
    except (json.JSONDecodeError, TypeError): return "Unknown"

def format_date(date_string):
    try: return datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except (ValueError, TypeError): return "Unknown"

def rank_results(results):
    if not results: return []
    max_seeders = max(r.get('seeders', 0) for r in results) if results else 1
    for r in results:
        r["author_info"] = parse_author_info(r.get("author_info", ""))
        r["narrator_info"] = parse_author_info(r.get("narrator_info", ""))
        
        series_data = r.get("series_info", "")
        try:
            series_json = json.loads(series_data)
            # Example: {"2887": ["The Inheritance Cycle", "5"]} -> "The Inheritance Cycle, Book 5"
            series_name, book_number = next(iter(series_json.values()))
            r["series_display"] = f"{series_name}, Book {book_number}" if book_number else series_name
        except (json.JSONDecodeError, TypeError, StopIteration):
            r["series_display"] = ""
            
        r["added"] = format_date(r.get("added", "Unknown"))
        filetype_score = {'m4b': 50, 'mp3': 30}.get(r.get('filetype'), 10)
        seeders_score = (r.get('seeders', 0) / max_seeders * 30) if max_seeders > 0 else 0
        r['score'] = round(filetype_score + seeders_score, 1)
    return sorted(results, key=lambda x: x['score'], reverse=True)

@app.route('/mam/search', methods=['GET'])
async def mam_search():
    if not await login_mam(): 
        return await render_template("partials/results.html", error_message="Login to MyAnonamouse failed. Check your MAM_ID cookie in settings.")
    query = request.args.get("query", "")
    if not query: 
        return await render_template("partials/results.html", results=[])

    params = {
        "tor[text]": query,
        "tor[sortType]": "default", "perpage": 50, "thumbnail": "true", "dlLink": "true",
        "tor[browse_lang][]": language_dict.get(request.args.get("language", "English"), 1),
        "tor[srchIn][title]": "on" if request.args.get("search_in_title") else "off",
        "tor[srchIn][author]": "on" if request.args.get("search_in_author") else "off",
        "tor[srchIn][narrator]": "on" if request.args.get("search_in_narrator") else "off",
        "tor[searchType]": request.args.get("searchType", "all"),
    }
    if (media_type := request.args.get("media_type", "13")) != "all":
        params["tor[main_cat][]"] = media_type

    headers = {"Cookie": "; ".join([f"{k}={v}" for k, v in mam_session_cookies.items()])}
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{app.config['MAM_API_URL']}/tor/js/loadSearchJSONbasic.php", 
                params=params, 
                headers=headers
            )
            update_cookies(response)
            
            response.raise_for_status()
            json_data = response.json()
            results = json_data.get("data", [])

            # The API returns a 'dl' hash. We must construct the full download_link for the template.
            base_dl_url = f"{app.config['MAM_API_URL']}/tor/download.php/"
            for item in results:
                if dl_hash := item.get('dl'):
                    # This line creates the full URL and adds it to the dictionary
                    item['download_link'] = base_dl_url + dl_hash
                else:
                    # This is a good practice to prevent errors if 'dl' is missing
                    item['download_link'] = '' 

                if not item.get('thumbnail'):
                    cat = item.get('category', '')
                    item['thumbnail'] = f"https://static.myanonamouse.net/pic/cats/3/{cat}.png"        # --- END FIX ---

            ranked = rank_results(results)
            
            # Check qBittorrent status
            qb_status_response, status_code = await qb_status()
            qb_status_json = await qb_status_response.get_json()
            qb_connected = qb_status_json.get("status") == "success"
            
            categories = {}
            if qb_connected:
                categories_response = await qb_categories()
                if categories_response.status_code == 200:
                    categories = await categories_response.get_json()
            
            return await render_template("partials/results.html", results=ranked, QB_STATUS="CONNECTED" if qb_connected else "NOT CONNECTED", categories=categories, QB_CATEGORY=app.config.get("QB_CATEGORY"))
    except RequestError as e:
        return await render_template("partials/results.html", error_message=f"Error connecting to MAM API: {e}")
    except json.JSONDecodeError:
        return await render_template("partials/results.html", error_message="Failed to decode API response. Your session cookie might be invalid.")



@app.route("/")
async def index():
    return await render_template("index.html", **app.config)

FETCH_SEMAPHORE = asyncio.Semaphore(200)  # tune if needed

@app.route("/proxy_thumbnail")
async def proxy_thumbnail():
    url = request.args.get("url")
    if not url:
        return "No URL provided", 400
    if UPSTREAM_CLIENT is None:
        return "Upstream client not ready", 503

    # Forward only headers useful for conditional/partial requests
    fwd_headers = {}
    for h in ("If-None-Match", "If-Modified-Since", "Range"):
        v = request.headers.get(h)
        if v:
            fwd_headers[h] = v

    # If the CDN images are PUBLIC, set cookies=None to maximize CDN cache hits
    upstream_cookies = mam_session_cookies  # or: None

    async with FETCH_SEMAPHORE:
        # Build request and keep the response OPEN until we finish streaming it.
        req = UPSTREAM_CLIENT.build_request("GET", url, headers=fwd_headers, cookies=upstream_cookies)
        r = await UPSTREAM_CLIENT.send(req, stream=True)

        # Prepare downstream headers
        passthrough = {}
        for h in (
            "Content-Type", "Content-Length", "Cache-Control",
            "ETag", "Last-Modified", "Accept-Ranges", "Content-Range"
        ):
            hv = r.headers.get(h)
            if hv:
                passthrough[h] = hv
        passthrough.setdefault("Cache-Control", "public, max-age=31536000, immutable")

        # 304 passthrough (no body)
        if r.status_code == 304:
            await r.aclose()
            return Response(status=304, headers=passthrough)

        async def body():
            try:
                async for chunk in r.aiter_bytes():
                    yield chunk
            finally:
                # CRITICAL: close upstream stream no matter what (client disconnects, errors, etc.)
                await r.aclose()

        return Response(body(), status=r.status_code, headers=passthrough)


@app.route("/update_settings", methods=["POST"])
async def update_settings():
    form = await request.form
    config_to_update = app.config.copy()
    
    for key in FALLBACK_CONFIG.keys():
        if key in form:
            config_to_update[key] = form[key]
    if form.get("QB_PASSWORD"):
        config_to_update["QB_PASSWORD"] = form.get("QB_PASSWORD")

    save_config(config_to_update)
    await load_new_app_config()

    # Manually trigger a forced IP update after saving new credentials.
    job_id = 'manual_ip_update_job'
    run_time = datetime.now() + timedelta(seconds=2) # Run 2 seconds after the request finishes
    if scheduler.get_job(job_id):
        scheduler.reschedule_job(job_id, trigger='date', run_date=run_time)
    else:
        scheduler.add_job(id=job_id, func=force_update_ip, trigger='date', run_date=run_time)
    
    return jsonify({"status": "success", "message": "Settings updated! A manual IP update has been triggered."})

if app.config.get("AUTO_ORGANIZE_ON_ADD") or app.config.get("AUTO_ORGANIZE_ON_SCHEDULE"):
    app.logger.info("Auto-organization is enabled. Registering webhook and/or scheduled job.")

    async def _perform_organization(hash_val: str) -> tuple[bool, str]:
        """
        Performs the file organization for a given torrent hash.
        Returns a tuple of (success_boolean, message_string).
        """
        # 1. Load metadata and perform checks
        metadata = load_metadata()
        if hash_val not in metadata:
            return False, f"Cannot organize: No metadata found for hash {hash_val}."
        
        if metadata[hash_val].get('organized', False):
            return True, f"Skipping: Torrent {hash_val} is already marked as organized."

        # Check retry count to avoid infinite retries
        retry_count = metadata[hash_val].get('retry_count', 0)
        if retry_count >= 3:
            return True, f"Skipping: Torrent {hash_val} has exceeded maximum retry attempts ({retry_count})."

        # 2. Get torrent info from qBittorrent to find its content path
        if not await login_qbittorrent():
            return False, "qBittorrent login failed."
        
        try:
            async with httpx.AsyncClient(cookies=session['qb_session']) as client:
                response = await client.get(
                    f"{app.config['QB_URL']}/api/v2/torrents/properties",
                    params={'hash': hash_val},
                    headers=app.config.get("BASE_HEADERS", {})
                )
                response.raise_for_status()
                properties = response.json()
                # must make sure save_path matches between qBittorrent and MouseSearch 
                content_path = Path(QB_PATH) / properties.get('name')
                # content_path = Path(properties.get('save_path')) / properties.get('name')

                # 3. Define paths and perform the linking
                organized_path = Path(ORGANIZED_PATH)
                
                torrent_meta = metadata[hash_val]
                s_author = sanitize_filename(torrent_meta['author'])
                s_title = sanitize_filename(torrent_meta['title'])
                dest_path = organized_path / s_author / s_title

                # Check if source exists
                if not content_path.exists():
                    # Don't increment retry counter - this might be a timing issue
                    return False, f"Source path does not exist: {content_path}"
                
                # Handle destination creation errors
                try:
                    dest_path.mkdir(parents=True, exist_ok=True)
                except (OSError, PermissionError) as e:
                    return False, f"Cannot create destination directory '{dest_path}': {e}"
                
                files_linked = 0
                files_already_exist = 0
                audio_extensions = ['.m4b', '.mp3', '.flac', '.ogg', '.opus', '.m4a']

                # Handle directory vs file correctly
                if content_path.is_dir():
                    source_files = content_path.rglob('*')
                else:
                    source_files = [content_path]

                for source_file in source_files:
                    if source_file.is_file() and source_file.suffix.lower() in audio_extensions:
                        # Preserve the original torrent folder structure
                        relative_path = source_file.relative_to(content_path)
                        dest_file = dest_path / relative_path
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        
                        if dest_file.exists():
                            # Count existing files separately
                            files_already_exist += 1
                            app.logger.debug(f"[ORGANIZE] Skipped (already exists): {dest_file}")
                        else:
                            try:
                                os.link(source_file, dest_file)
                                files_linked += 1
                                app.logger.info(f"[ORGANIZE] Linked: {source_file} -> {dest_file}")
                            except (OSError, PermissionError) as e:
                                # Handle individual file link errors
                                app.logger.error(f"[ORGANIZE] Failed to link {source_file} -> {dest_file}: {e}")
                                # Continue processing other files

                # 4. Update metadata based on results
                total_audio_files = files_linked + files_already_exist
                
                if total_audio_files == 0:
                    # No audio files found at all - increment retry
                    metadata[hash_val]['retry_count'] = retry_count + 1
                    save_metadata(metadata)
                    return False, f"No compatible audio files found for '{s_title}' (attempt {retry_count + 1}/3)."
                
                # Success if files were linked OR already existed
                if files_linked > 0 or files_already_exist > 0:
                    metadata[hash_val]['organized'] = True
                    save_metadata(metadata)
                    
                    if files_linked > 0 and files_already_exist > 0:
                        msg = f"SUCCESS: '{s_title}' by {s_author} - {files_linked} new files linked, {files_already_exist} already existed (total: {total_audio_files} files in '{dest_path}')."
                    elif files_linked > 0:
                        msg = f"SUCCESS: '{s_title}' by {s_author} - {files_linked} files linked to '{dest_path}'."
                    else:
                        msg = f"SUCCESS: '{s_title}' by {s_author} - All {files_already_exist} files already organized in '{dest_path}'."
                    
                    app.logger.info(f"[ORGANIZE] {msg}")
                    return True, msg
                
                # This should never happen given the logic above, but as a safety net:
                return False, "Unexpected error: No files processed."

        except RequestError as e:
            return False, f"API error during organization: {e}"
        except json.JSONDecodeError as e:
            return False, f"Failed to parse qBittorrent response: {e}"
        except Exception as e:
            # Catch-all for unexpected errors
            app.logger.exception(f"Unexpected error organizing {hash_val}")
            return False, f"Unexpected error: {e}"

    @app.route('/organize', methods=['POST'])
    @app.route('/organize/<hash_val>', methods=['POST'])
    async def organize_torrent_webhook(hash_val=None):
        """
        Webhook endpoint for torrent organization.
        - If hash_val is provided: organizes that specific torrent
        - If no hash_val: iterates through all unorganized torrents in metadata.json
        """
        async with app.app_context():
            if hash_val:
                # Single torrent organization
                app.logger.info(f"Received webhook organization request for hash: {hash_val}")
                success, message = await _perform_organization(hash_val)
                
                if success:
                    app.logger.info(message)
                    return jsonify({'status': 'success', 'message': message}), 200
                else:
                    app.logger.error(message)
                    return jsonify({'status': 'error', 'message': message}), 500
            else:
                # Batch organization of all unorganized torrents
                app.logger.info("Received batch organization request (no hash provided)")
                metadata = load_metadata()
                unorganized_hashes = [h for h, m in metadata.items() if not m.get('organized', False)]
                
                if not unorganized_hashes:
                    message = "No unorganized torrents found in metadata."
                    app.logger.info(message)
                    return jsonify({'status': 'success', 'message': message, 'processed': 0}), 200
                
                app.logger.info(f"Found {len(unorganized_hashes)} unorganized torrent(s). Processing...")
                
                results = {
                    'total': len(unorganized_hashes),
                    'succeeded': 0,
                    'failed': 0,
                    'skipped': 0,
                    'details': []
                }
                
                for hash_val in unorganized_hashes:
                    success, message = await _perform_organization(hash_val)
                    
                    if success:
                        if "Skipping" in message:
                            results['skipped'] += 1
                            app.logger.info(f"Batch organize - Skipped: {hash_val} - {message}")
                        else:
                            results['succeeded'] += 1
                            app.logger.info(f"Batch organize - Success: {hash_val} - {message}")
                    else:
                        results['failed'] += 1
                        # Check if it's a "source path does not exist" error
                        if "Source path does not exist" in message:
                            app.logger.warning(f"Batch organize - Source missing: {hash_val} - {message}")
                        else:
                            app.logger.error(f"Batch organize - Failed: {hash_val} - {message}")
                    
                    results['details'].append({
                        'hash': hash_val,
                        'success': success,
                        'message': message
                    })
                
                summary = f"Batch organization complete: {results['succeeded']} succeeded, {results['failed']} failed, {results['skipped']} skipped (out of {results['total']} total)"
                app.logger.info(summary)
                
                return jsonify({
                    'status': 'success',
                    'message': summary,
                    'results': results
                }), 200

    async def check_for_unorganized_torrents():
        """Periodically checks for any torrents that were missed by the webhook."""
        async with app.app_context():
            app.logger.info("Running scheduled job: Safety net for unorganized torrents.")
            metadata = load_metadata()
            unorganized_hashes = [h for h, m in metadata.items() if not m.get('organized', False)]

            if not unorganized_hashes:
                app.logger.info("Safety net job: No unorganized torrents found.")
                return

            app.logger.info(f"Safety net job: Found {len(unorganized_hashes)} unorganized torrent(s). Processing now.")
            for hash_val in unorganized_hashes:
                success, message = await _perform_organization(hash_val)
                if success:
                    app.logger.info(f"Safety net: {message}")
                else:
                    app.logger.error(f"Safety net failed for {hash_val}: {message}")
    
    # Only schedule the periodic job if AUTO_ORGANIZE_ON_SCHEDULE is enabled
    if app.config.get("AUTO_ORGANIZE_ON_SCHEDULE"):
        scheduler.add_job(check_for_unorganized_torrents, 'interval', hours=1, id='organize_safety_net_job', replace_existing=True)
        app.logger.info("Scheduled auto-organization job registered (runs every hour).")
    else:
        app.logger.info("AUTO_ORGANIZE_ON_SCHEDULE is disabled. No scheduled organization job will run.")
else:
    app.logger.info("Auto-organization is disabled. Skipping organization feature setup.")

    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Quart app.")
    parser.add_argument("--host", default="0.0.0.0", help="Host address.")
    parser.add_argument("--port", default=5000, type=int, help="Port number.")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
