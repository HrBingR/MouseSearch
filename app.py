# app.py - Quart (async) version
from quart import Quart, request, render_template, Response, jsonify, session
import httpx
import json
import argparse
import os
import time
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

from clients import get_torrent_client

# --- SCHEDULER AND STATE SETUP ---
app = Quart(__name__)

UPSTREAM_CLIENT: httpx.AsyncClient | None = None

# --- Monitoring & Caching Globals ---
monitoring_state = {} 
monitor_task = None
torrent_status_cache = {}
CACHE_TTL = 2.0 

@app.before_serving
async def startup():
    await load_new_app_config()
    if not scheduler.running:
        scheduler.start()
        app.logger.info("AsyncIOScheduler started")

    global UPSTREAM_CLIENT
    transport = AsyncHTTPTransport(http2=True, retries=2)
    limits = Limits(max_connections=200, max_keepalive_connections=50, keepalive_expiry=120.0)
    timeout = Timeout(connect=5.0, read=15.0, write=15.0, pool=None)
    UPSTREAM_CLIENT = httpx.AsyncClient(transport=transport, limits=limits, timeout=timeout)
    app.logger.info("Shared httpx AsyncClient initialized")
    
    # --- Initialize Active Monitoring on Startup ---
    metadata = load_metadata()
    unorganized = [h for h, m in metadata.items() if not m.get('organized', False)]
    if unorganized:
        app.logger.info(f"Startup: Found {len(unorganized)} unorganized torrents. Starting active monitoring.")
        current_time = time.time()
        for h in unorganized:
            monitoring_state[h] = {"added_at": current_time - 20} 
        start_monitoring_loop()


@app.after_serving
async def shutdown():
    if scheduler.running:
        scheduler.shutdown()
        app.logger.info("AsyncIOScheduler shutdown")

    global UPSTREAM_CLIENT
    if UPSTREAM_CLIENT is not None:
        await UPSTREAM_CLIENT.aclose()
        UPSTREAM_CLIENT = None
        app.logger.info("Shared httpx AsyncClient closed")
    
    global monitor_task
    if monitor_task:
        monitor_task.cancel()


# --- LOGGING CONFIGURATION (NOISY LIBS SILENCED) ---
# Configure root logger
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stderr
)

# Silence noisy libraries
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("tzlocal").setLevel(logging.WARNING)

if __name__ != '__main__':
    logger = logging.getLogger('hypercorn.error')
    app.logger.handlers = logger.handlers
    app.logger.setLevel(logging.DEBUG)
else:
    app.logger.setLevel(logging.DEBUG)

scheduler = AsyncIOScheduler()

load_dotenv()

# Define fallback values
FALLBACK_CONFIG = {
    "QUART_SECRET_KEY": os.urandom(24).hex(),
    "MAM_API_URL": "https://www.myanonamouse.net",
    "TORRENT_CLIENT_TYPE": "qbittorrent",
    "TORRENT_CLIENT_URL": "http://localhost:8080",
    "TORRENT_CLIENT_USERNAME": "admin",
    "TORRENT_CLIENT_PASSWORD": "",
    "TORRENT_CLIENT_CATEGORY": "",
    "MAM_ID": "",
    "CF_ACCESS_CLIENT_ID": None,
    "CF_ACCESS_CLIENT_SECRET": None,
    "DATA_PATH": "./data",
    "ORGANIZED_PATH": "/downloads/organized",
    "TORRENT_DOWNLOAD_PATH": "/downloads/torrents/organize-these/audiobooks",
    "AUTO_ORGANIZE_ON_ADD": False,
    "AUTO_ORGANIZE_ON_SCHEDULE": False,
    "AUTO_ORGANIZE_INTERVAL_HOURS": 1,
    "ENABLE_DYNAMIC_IP_UPDATE": False,
    "DYNAMIC_IP_UPDATE_INTERVAL_HOURS": 3
}

# Set up data directory and paths
DATA_PATH = Path(os.getenv("DATA_PATH", FALLBACK_CONFIG["DATA_PATH"])).resolve()
ORGANIZED_PATH = Path(os.getenv("ORGANIZED_PATH", FALLBACK_CONFIG["ORGANIZED_PATH"])).resolve()
TORRENT_DOWNLOAD_PATH = Path(os.getenv("TORRENT_DOWNLOAD_PATH", FALLBACK_CONFIG["TORRENT_DOWNLOAD_PATH"])).resolve()

DATA_PATH.mkdir(parents=True, exist_ok=True)

CONFIG_FILE = DATA_PATH / "config.json"
METADATA_FILE = DATA_PATH / "metadata.json"
IP_STATE_FILE = DATA_PATH / "ip_state.json"

def load_config():
    config = FALLBACK_CONFIG.copy()
    json_config = {}
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
             json_config = json.load(f)

    env_config = {key: os.getenv(key) for key in config.keys() if os.getenv(key) is not None}
    config.update(env_config) 
    config.update(json_config) 
    return config

def save_config(config):
    config_to_save = {key: config.get(key) for key in FALLBACK_CONFIG.keys()}
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_to_save, f, indent=4)

def initialize_config():
    if not CONFIG_FILE.exists():
        initial_config = load_config()
        save_config(initial_config)
        print(f"Initialized {CONFIG_FILE} with default configuration.")
    else:
        # Check if QUART_SECRET_KEY is missing and needs to be generated
        existing_config = load_config()
        if not existing_config.get("QUART_SECRET_KEY") or existing_config.get("QUART_SECRET_KEY") == "":
            # Generate a new secret key and save it
            existing_config["QUART_SECRET_KEY"] = os.urandom(24).hex()
            save_config(existing_config)
            print(f"Generated and saved new QUART_SECRET_KEY to {CONFIG_FILE}.")

initialize_config()

async def load_new_app_config():
    new_config = load_config()
    app.secret_key = new_config["QUART_SECRET_KEY"]
    app.config.update(new_config)
    
    app.config["BASE_HEADERS"] = {
        "CF-Access-Client-Id": new_config.get("CF_ACCESS_CLIENT_ID"),
        "CF-Access-Client-Secret": new_config.get("CF_ACCESS_CLIENT_SECRET"),
    }
    app.config["BASE_HEADERS"] = {k: v for k, v in app.config["BASE_HEADERS"].items() if v is not None}
    
    global mam_session_cookies
    mam_session_cookies = {"mam_id": app.config.get("MAM_ID")}

    global torrent_client
    try:
        torrent_client = get_torrent_client(app.config)
        app.logger.info(f"Initialized torrent client: {app.config.get('TORRENT_CLIENT_TYPE', 'qbittorrent')}")
    except Exception as e:
        app.logger.error(f"Failed to initialize torrent client: {e}")
        torrent_client = None

initial_config = load_config()
app.secret_key = initial_config["QUART_SECRET_KEY"]
app.config.update(initial_config)
app.config["BASE_HEADERS"] = {
    "CF-Access-Client-Id": initial_config.get("CF_ACCESS_CLIENT_ID"),
    "CF-Access-Client-Secret": initial_config.get("CF_ACCESS_CLIENT_SECRET"),
}
mam_session_cookies = {"mam_id": initial_config.get("MAM_ID")}
torrent_client = None

# --- ACTIVE MONITORING & CACHING LOGIC ---

def start_monitoring_loop():
    global monitor_task
    if monitor_task is None or monitor_task.done():
        monitor_task = asyncio.create_task(monitor_downloads_loop())
        app.logger.info("Active download monitoring loop started.")

async def monitor_downloads_loop():
    app.logger.info("Entered monitoring loop.")
    client_session_active = False
    
    while True:
        if not monitoring_state:
            if client_session_active:
                app.logger.debug("[MONITOR] Queue empty. Going idle.")
            client_session_active = False 
            await asyncio.sleep(5)
            continue

        try:
            if not torrent_client:
                app.logger.warning("Monitor loop: Client not ready.")
                await asyncio.sleep(5)
                continue

            # OPTIMIZED LOGIN
            if not client_session_active:
                try:
                    await torrent_client.login()
                    client_session_active = True
                    app.logger.debug("[MONITOR] Session established with torrent client.")
                except Exception as e:
                    app.logger.error(f"[MONITOR] Login failed: {e}")
                    await asyncio.sleep(5)
                    continue

            active_hashes = list(monitoring_state.keys())
            torrents_info = {}
            
            # FETCH DATA
            try:
                if hasattr(torrent_client, 'get_torrent_info_batch'):
                    batch_res = await torrent_client.get_torrent_info_batch(active_hashes)
                    if 'torrents' in batch_res:
                        torrents_info = batch_res['torrents']
                else:
                    for h in active_hashes:
                        info = await torrent_client.get_torrent_info(h)
                        if info: torrents_info[h] = info
                
                if torrents_info:
                    status_summary = []
                    for h, info in torrents_info.items():
                        p = info.get('progress', 0) * 100
                        eta = info.get('eta', 8640000)
                        eta_str = f"{eta}s" if eta < 8640000 else "Unknown"
                        status_summary.append(f"{h[:6]}..: {p:.1f}% (ETA: {eta_str})")
                    
                    app.logger.debug(f"[MONITOR] Polled {len(torrents_info)} item(s): {', '.join(status_summary)}")

            except Exception as e:
                app.logger.warning(f"[MONITOR] Fetch failed (session expired?): {e}")
                client_session_active = False 
                await asyncio.sleep(1)
                continue

            finished_hashes = []
            current_time = time.time()
            
            # Logic Flags
            force_high_freq = False
            valid_etas_for_sleep = []

            for h, info in torrents_info.items():
                # UPDATE CACHE
                torrent_status_cache[h] = {
                    "data": info,
                    "timestamp": current_time
                }

                # --- HISTORY & STABILITY LOGIC ---
                # 1. Lazy Init History in monitoring_state
                # This ensures we don't crash if the key is missing
                state_entry = monitoring_state.get(h)
                if not state_entry: continue 
                eta_history = state_entry.setdefault('eta_history', [])

                state = info.get('state', 'unknown')
                progress = info.get('progress', 0)
                current_eta = info.get('eta', 8640000)
                
                # Check completion
                is_complete = state in ['uploading', 'stalledUP', 'forcedUP', 'pausedUP', 'checkingUP']
                if progress >= 1 and state not in ['error', 'missingFiles']:
                    is_complete = True

                if is_complete:
                    finished_hashes.append(h)
                    continue # Skip frequency logic for finished items

                # 2. Update Rolling History (Max 5 items)
                eta_history.append(current_eta)
                if len(eta_history) > 5:
                    eta_history.pop(0)

                # 3. Check "Initial Phase" (First 15s)
                added_at = state_entry.get('added_at', 0)
                if current_time - added_at < 15:
                    force_high_freq = True
                    continue # Must poll fast, ignore stability
                
                # 4. Check Stability (Rolling 5, min >= 80% of max)
                is_stable = False
                if len(eta_history) == 5:
                    min_eta = min(eta_history)
                    max_eta = max(eta_history)
                    # If max is 0, we are effectively finished, treat as stable
                    if max_eta == 0 or min_eta >= (0.8 * max_eta):
                        is_stable = True
                
                if not is_stable:
                    force_high_freq = True
                else:
                    # Stable: Allow this ETA to influence the sleep calculation
                    valid_etas_for_sleep.append(current_eta)

            # --- END LOOP OVER ITEMS ---

            for h in finished_hashes:
                app.logger.info(f"[MONITOR] Torrent {h} finished. Triggering Auto-Organize.")
                await _perform_organization(h)
                if h in monitoring_state:
                    del monitoring_state[h]

            for h in active_hashes:
                if h not in torrents_info and h not in finished_hashes:
                    added_at = monitoring_state.get(h, {}).get('added_at', 0)
                    if current_time - added_at > 10:
                        app.logger.warning(f"[MONITOR] Torrent {h} disappeared. Stopping monitor.")
                        del monitoring_state[h]

            if not monitoring_state:
                app.logger.info("[MONITOR] All tracked downloads finished.")
                await asyncio.sleep(2) 
                continue

            # --- SLEEP CALCULATION ---
            sleep_reason = ""
            if force_high_freq:
                sleep_time = 1
                sleep_reason = "High Freq (Initial/Unstable)"
            elif valid_etas_for_sleep:
                lowest_eta = min(valid_etas_for_sleep)
                # ETA / 2 logic
                sleep_time = max(2, int(lowest_eta / 2))
                # Configurable cap (hardcoded 30s as requested)
                sleep_time = min(sleep_time, 30)
                sleep_reason = f"Stable Backoff (min ETA: {lowest_eta}s)"
            else:
                # Fallback if we have active downloads but none fell into valid buckets
                # (e.g. all < 5 history points but > 15s old? Treat as unstable)
                sleep_time = 1
                sleep_reason = "Fallback (Insufficient Data)"
            
            app.logger.debug(f"[MONITOR] Sleeping {sleep_time}s [{sleep_reason}]")
            await asyncio.sleep(sleep_time)

        except Exception as e:
            app.logger.error(f"[MONITOR] Error in loop: {e}")
            client_session_active = False
            await asyncio.sleep(5)


# --- IP STATE MANAGEMENT ---

def load_ip_state():
    if os.path.exists(IP_STATE_FILE):
        try:
            with open(IP_STATE_FILE, "r") as f:
                return json.load(f).get("last_ip")
        except (json.JSONDecodeError, FileNotFoundError):
            pass
    return None

def save_ip_state(ip):
    with open(IP_STATE_FILE, "w") as f:
        json.dump({"last_ip": ip}, f, indent=4)

async def force_update_ip():
    async with app.app_context():
        app.logger.info("Forcing manual IP update for dynamic seedbox.")
        if not app.config.get("MAM_ID"): return
        api_cookies = {"mam_id": app.config.get("MAM_ID")}
        try:
            update_url = "https://t.myanonamouse.net/json/dynamicSeedbox.php"
            async with httpx.AsyncClient() as client:
                update_response = await client.get(update_url, cookies=api_cookies, timeout=15)
                update_response.raise_for_status()
                update_data = update_response.json()
                if new_ip := update_data.get("ip"):
                    save_ip_state(new_ip)
        except Exception as e:
            app.logger.error(f"Error calling dynamic seedbox update: {e}")

async def check_and_update_ip():
    async with app.app_context():
        if not app.config.get("MAM_ID"): return
        api_cookies = {"mam_id": app.config.get("MAM_ID")}
        try:
            ip_check_url = f"{app.config.get('MAM_API_URL')}/json/jsonIp.php"
            async with httpx.AsyncClient() as client:
                response = await client.get(ip_check_url, cookies=api_cookies, timeout=10)
                response.raise_for_status()
                current_ip = response.json().get("ip")
                if not current_ip: return
        except Exception:
            return
            
        last_ip = load_ip_state()
        if current_ip != last_ip:
            await force_update_ip()

if app.config.get("ENABLE_DYNAMIC_IP_UPDATE"):
    interval_hours = int(app.config.get("DYNAMIC_IP_UPDATE_INTERVAL_HOURS", 3))
    scheduler.add_job(check_and_update_ip, 'interval', hours=interval_hours, id='ip_check_job', replace_existing=True)
    scheduler.add_job(check_and_update_ip, 'date', run_date=datetime.now() + timedelta(seconds=5), id='initial_ip_check_job')

# --- SESSION AND API HELPERS ---
def update_cookies(response):
    global mam_session_cookies
    if "set-cookie" in response.headers:
        cookies = dict(response.cookies)
        mam_session_cookies.update(cookies)

async def login_mam():
    url = app.config.get("MAM_API_URL")
    if not url or not mam_session_cookies.get("mam_id"): return False
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{url}/jsonLoad.php", cookies=mam_session_cookies, timeout=5)
            if response.status_code == 200:
                if new_cookies := dict(response.cookies): mam_session_cookies.update(new_cookies)
                return True
        except Exception:
            pass
    return False

# --- QUART ROUTES ---
@app.route('/mam/status', methods=['GET'])
async def mam_status(): 
    return jsonify({'status': 'connected' if await login_mam() else 'not connected'})

@app.route('/mam/user_data', methods=['GET'])
async def mam_user_data():
    if not await login_mam(): return jsonify({'error': 'Not logged into MAM'}), 401
    try:
        api_url = f"{app.config.get('MAM_API_URL')}/jsonLoad.php"
        async with httpx.AsyncClient() as client:
            response = await client.get(api_url, cookies=mam_session_cookies, timeout=10)
            update_cookies(response)
            response.raise_for_status()
            user_data = response.json()
            if seedbonus := user_data.get("seedbonus"):
                user_data["seedbonus_formatted"] = f"{seedbonus:,}"
            return jsonify(user_data)
    except Exception:
        return jsonify({'error': 'Failed to fetch data'}), 503
    
# --- GENERIC TORRENT CLIENT ROUTES ---
@app.route('/client/status', methods=['GET'])
async def client_status():
    if not torrent_client: return jsonify({"status": "error", "message": "Client not initialized"}), 500
    # Only login if needed (handled by client usually, but we force login in other places)
    try:
        return jsonify(await torrent_client.get_status())
    except:
        await torrent_client.login()
        return jsonify(await torrent_client.get_status())

@app.route('/client/categories', methods=['GET'])
async def client_categories():
    if not torrent_client: return jsonify({'error': 'Not connected'}), 401
    # Try fetch, if fail login
    try:
        categories = await torrent_client.get_categories()
    except:
        await torrent_client.login()
        categories = await torrent_client.get_categories()
    return jsonify(categories) if categories else (jsonify({'error': 'Failed'}), 500)

@app.route('/client/add', methods=['POST'])
async def client_add_torrent():
    """Add a torrent to the configured client and REGISTER FOR MONITORING."""
    if not torrent_client:
        return jsonify({'error': 'Client not initialized'}), 500
    
    await torrent_client.login()
    incoming_data = await request.get_json()
    
    torrent_url = incoming_data.get('torrent_url') or incoming_data.get('url')
    author = incoming_data.get('author', 'Unknown')
    title = incoming_data.get('title', 'Unknown')
    id = incoming_data.get('id', '0')
    
    auto_organize_warning = None
    hash_val = await calculate_torrent_hash_from_url(torrent_url)
    
    if app.config.get("AUTO_ORGANIZE_ON_ADD"):
        if not hash_val:
            auto_organize_warning = "Unable to calculate hash - auto-organization will not work."
        else:
            metadata = load_metadata()
            metadata[hash_val] = {
                "id": id, "author": author, "title": title,
                "added_on": datetime.now().isoformat(),
                "organized": False, "retry_count": 0
            }
            save_metadata(metadata)
            app.logger.info(f"Saved metadata for torrent hash: {hash_val}")
    
    category = incoming_data.get('category', app.config.get("TORRENT_CLIENT_CATEGORY", ""))
    result = await torrent_client.add_torrent(torrent_url, category)
    
    if result['status'] == 'success':
        # Start Monitoring
        if hash_val and app.config.get("AUTO_ORGANIZE_ON_ADD"):
            monitoring_state[hash_val] = {
                "added_at": time.time()
            }
            start_monitoring_loop()
            app.logger.info(f"Registered {hash_val} for active monitoring.")

        response_data = {'message': result['message']}
        if auto_organize_warning: response_data['warning'] = auto_organize_warning
        return jsonify(response_data)
    else:
        return jsonify({'error': result.get('message', 'Unknown error')}), 400

@app.route('/client/info/<hash_val>', methods=['GET'])
async def client_torrent_info(hash_val):
    if hash_val in torrent_status_cache:
        entry = torrent_status_cache[hash_val]
        if time.time() - entry['timestamp'] < CACHE_TTL:
            return jsonify(entry['data'])

    if not torrent_client: return jsonify({'error': 'Client not initialized'}), 500
    
    # Optimistic fetch, fallback to login
    try:
        info = await torrent_client.get_torrent_info(hash_val)
    except:
        await torrent_client.login()
        info = await torrent_client.get_torrent_info(hash_val)

    if info:
        torrent_status_cache[hash_val] = {"data": info, "timestamp": time.time()}
        return jsonify(info)
    return jsonify({'error': 'Not found'}), 404

@app.route('/client/info/batch', methods=['POST'])
async def client_torrent_info_batch():
    data = await request.get_json()
    hash_list = data.get('hashes', [])
    if not hash_list: return jsonify({'torrents': []})
    
    cached_response = {}
    hashes_to_fetch = []
    current_time = time.time()
    
    for h in hash_list:
        if h in torrent_status_cache and (current_time - torrent_status_cache[h]['timestamp'] < CACHE_TTL):
            cached_response[h] = torrent_status_cache[h]['data']
        else:
            hashes_to_fetch.append(h)
    
    if not hashes_to_fetch:
        return jsonify({'torrents': cached_response})

    if not torrent_client: return jsonify({'error': 'Client not initialized'}), 500
    
    try:
        fetched_results = {}
        if hasattr(torrent_client, 'get_torrent_info_batch'):
            result = await torrent_client.get_torrent_info_batch(hashes_to_fetch)
            fetched_results = result.get('torrents', {})
        else:
            for hash_val in hashes_to_fetch:
                info = await torrent_client.get_torrent_info(hash_val)
                if info: fetched_results[hash_val] = info
        
        for h, info in fetched_results.items():
            torrent_status_cache[h] = {"data": info, "timestamp": current_time}
            cached_response[h] = info
            
        return jsonify({'torrents': cached_response})
    except Exception as e:
        # Retry once with login
        try:
            await torrent_client.login()
            if hasattr(torrent_client, 'get_torrent_info_batch'):
                result = await torrent_client.get_torrent_info_batch(hashes_to_fetch)
                fetched_results = result.get('torrents', {})
            else:
                for hash_val in hashes_to_fetch:
                    info = await torrent_client.get_torrent_info(hash_val)
                    if info: fetched_results[hash_val] = info
            return jsonify({'torrents': fetched_results})
        except Exception as e2:
            return jsonify({'error': str(e2)}), 503
    
def load_metadata():
    if not os.path.exists(METADATA_FILE): return {}
    try:
        with open(METADATA_FILE, "r") as f: return json.load(f)
    except: return {}

def save_metadata(data):
    with open(METADATA_FILE, "w") as f: json.dump(data, f, indent=4)

def sanitize_filename(name: str) -> str:
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    return sanitized.strip('. ') if sanitized else "Untitled"
    
@app.route('/calculate_hash', methods=['POST'])
async def get_torrent_hash():
    data = await request.get_json()
    url = data.get('url')
    if not url: return jsonify({'error': 'URL required'}), 400
    hash_val = await calculate_torrent_hash_from_url(url)
    return jsonify({'hash': hash_val}) if hash_val else (jsonify({'error': 'Failed'}), 500)

async def calculate_torrent_hash_from_url(url: str) -> str | None:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            torrent_data = bencodepy.decode(response.content)
            if b'info' not in torrent_data: return None
            bencoded_info = bencodepy.encode(torrent_data[b'info'])
            return hashlib.sha1(bencoded_info).hexdigest()
    except Exception as e:
        app.logger.error(f"Hash calc error: {e}")
        return None

# --- SEARCH ROUTES & HELPERS ---
def parse_author_info(info):
    try: return ", ".join(json.loads(info).values())
    except: return "Unknown"

def format_date(date_string):
    try: return datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
    except: return "Unknown"

def rank_results(results):
    if not results: return []
    max_seeders = max(r.get('seeders', 0) for r in results) if results else 1
    for r in results:
        r["author_info"] = parse_author_info(r.get("author_info", ""))
        r["narrator_info"] = parse_author_info(r.get("narrator_info", ""))
        try:
            series_json = json.loads(r.get("series_info", ""))
            series_name, book_number = next(iter(series_json.values()))
            r["series_display"] = f"{series_name}, Book {book_number}" if book_number else series_name
        except:
            r["series_display"] = ""
        r["added"] = format_date(r.get("added", "Unknown"))
        filetype_score = {'m4b': 50, 'mp3': 30}.get(r.get('filetype'), 10)
        seeders_score = (r.get('seeders', 0) / max_seeders * 30) if max_seeders > 0 else 0
        r['score'] = round(filetype_score + seeders_score, 1)
    return sorted(results, key=lambda x: x['score'], reverse=True)

@app.route('/mam/search', methods=['GET'])
async def mam_search():
    if not await login_mam(): 
        return await render_template("partials/results.html", error_message="Login failed")
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
            response = await client.get(f"{app.config['MAM_API_URL']}/tor/js/loadSearchJSONbasic.php", params=params, headers=headers)
            update_cookies(response)
            response.raise_for_status()
            json_data = response.json()
            results = json_data.get("data", [])
            base_dl_url = f"{app.config['MAM_API_URL']}/tor/download.php/"
            for item in results:
                if dl_hash := item.get('dl'): item['download_link'] = base_dl_url + dl_hash
                else: item['download_link'] = '' 
                if not item.get('thumbnail'):
                    cat = item.get('category', '')
                    item['thumbnail'] = f"https://static.myanonamouse.net/pic/cats/3/{cat}.png"

            ranked = rank_results(results)
            client_status_data = await torrent_client.get_status() if torrent_client else {"status": "error"}
            client_connected = client_status_data.get("status") == "success"
            categories = await torrent_client.get_categories() if client_connected else {}
            
            return await render_template("partials/results.html", results=ranked, CLIENT_STATUS="CONNECTED" if client_connected else "NOT CONNECTED", categories=categories, TORRENT_CLIENT_CATEGORY=app.config.get("TORRENT_CLIENT_CATEGORY", ""))
    except Exception as e:
        return await render_template("partials/results.html", error_message=f"Error: {e}")

@app.route("/")
async def index():
    return await render_template("index.html", **app.config)

FETCH_SEMAPHORE = asyncio.Semaphore(200)

@app.route("/proxy_thumbnail")
async def proxy_thumbnail():
    url = request.args.get("url")
    if not url or UPSTREAM_CLIENT is None: return "Error", 400
    fwd_headers = {h: request.headers.get(h) for h in ("If-None-Match", "If-Modified-Since", "Range") if request.headers.get(h)}
    async with FETCH_SEMAPHORE:
        req = UPSTREAM_CLIENT.build_request("GET", url, headers=fwd_headers, cookies=mam_session_cookies)
        r = await UPSTREAM_CLIENT.send(req, stream=True)
        passthrough = {h: r.headers.get(h) for h in ("Content-Type", "Content-Length", "Cache-Control", "ETag", "Last-Modified", "Accept-Ranges", "Content-Range") if r.headers.get(h)}
        passthrough.setdefault("Cache-Control", "public, max-age=31536000, immutable")
        if r.status_code == 304:
            await r.aclose()
            return Response(status=304, headers=passthrough)
        async def body():
            try:
                async for chunk in r.aiter_bytes(): yield chunk
            finally: await r.aclose()
        return Response(body(), status=r.status_code, headers=passthrough)

@app.route("/update_settings", methods=["POST"])
async def update_settings():
    form = await request.form
    config_to_update = app.config.copy()
    boolean_fields = {"AUTO_ORGANIZE_ON_ADD", "AUTO_ORGANIZE_ON_SCHEDULE", "ENABLE_DYNAMIC_IP_UPDATE"}
    for key in FALLBACK_CONFIG.keys():
        if key in boolean_fields: config_to_update[key] = key in form
        elif key in form: config_to_update[key] = form[key]
    if form.get("TORRENT_CLIENT_PASSWORD"): config_to_update["TORRENT_CLIENT_PASSWORD"] = form.get("TORRENT_CLIENT_PASSWORD")
    save_config(config_to_update)
    await load_new_app_config()
    if app.config.get("ENABLE_DYNAMIC_IP_UPDATE"):
        scheduler.add_job(id='manual_ip_update_job', func=force_update_ip, trigger='date', run_date=datetime.now() + timedelta(seconds=2))
    return jsonify({"status": "success", "message": "Settings updated!"})


# --- ORGANIZE LOGIC ---

async def _perform_organization(hash_val: str) -> tuple[bool, str]:
    """Performs the file organization for a given torrent hash."""
    metadata = load_metadata()
    if hash_val not in metadata: return False, f"No metadata for hash {hash_val}."
    if metadata[hash_val].get('organized', False): return True, f"Already organized: {hash_val}."
    if metadata[hash_val].get('retry_count', 0) >= 3: return True, "Max retries exceeded."
    
    if not torrent_client: return False, "Client not initialized."
    # Try to rely on session, fall back to explicit login
    try:
        info = await torrent_client.get_torrent_info(hash_val)
    except:
        await torrent_client.login()
        try:
            info = await torrent_client.get_torrent_info(hash_val)
        except Exception as e:
            return False, f"Client fetch error: {e}"

    if not info: return False, f"Torrent {hash_val} not found in client."
    
    content_path = Path(TORRENT_DOWNLOAD_PATH) / info.get('name')
    organized_path = Path(ORGANIZED_PATH)
    torrent_meta = metadata[hash_val]
    dest_path = organized_path / sanitize_filename(torrent_meta['author']) / sanitize_filename(torrent_meta['title'])
    
    if not content_path.exists(): 
        app.logger.debug(f"[ORGANIZE] Source path missing: {content_path}")
        return False, f"Source missing: {content_path}"
    
    try: dest_path.mkdir(parents=True, exist_ok=True)
    except Exception as e: return False, f"Dest create failed: {e}"
    
    files_linked, files_exist = 0, 0
    source_files = content_path.rglob('*') if content_path.is_dir() else [content_path]
    
    for source_file in source_files:
        if source_file.is_file():
            # NO FILTERING: Link everything found in the torrent
            rel_path = source_file.relative_to(content_path)
            dest_file = dest_path / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            if dest_file.exists(): 
                files_exist += 1
                app.logger.debug(f"[ORGANIZE] Exists: {dest_file}")
            else:
                try: 
                    os.link(source_file, dest_file)
                    files_linked += 1
                    app.logger.debug(f"[ORGANIZE] Linked: {source_file} -> {dest_file}")
                except Exception as e:
                    app.logger.error(f"[ORGANIZE] Link error {source_file}: {e}")

    total = files_linked + files_exist
    if total == 0:
        metadata[hash_val]['retry_count'] += 1
        save_metadata(metadata)
        return False, "No files found."
    
    metadata[hash_val]['organized'] = True
    save_metadata(metadata)
    return True, f"Success: {files_linked} linked, {files_exist} existed."

@app.route('/organize', methods=['POST'])
@app.route('/organize/<hash_val>', methods=['POST'])
async def organize_torrent_webhook(hash_val=None):
    async with app.app_context():
        if hash_val:
            success, msg = await _perform_organization(hash_val)
            return jsonify({'status': 'success' if success else 'error', 'message': msg}), 200 if success else 500
        else:
            metadata = load_metadata()
            unorganized = [h for h, m in metadata.items() if not m.get('organized', False)]
            results = {'succeeded': 0, 'failed': 0}
            for h in unorganized:
                s, m = await _perform_organization(h)
                if s: results['succeeded'] += 1
                else: results['failed'] += 1
            return jsonify({'status': 'success', 'results': results}), 200

async def check_for_unorganized_torrents():
    """Safety net job."""
    async with app.app_context():
        app.logger.info("Running safety net organization job.")
        metadata = load_metadata()
        unorganized = [h for h, m in metadata.items() if not m.get('organized', False)]
        for h in unorganized:
            await _perform_organization(h)

if app.config.get("AUTO_ORGANIZE_ON_SCHEDULE"):
    hours = int(app.config.get("AUTO_ORGANIZE_INTERVAL_HOURS", 1))
    scheduler.add_job(check_for_unorganized_torrents, 'interval', hours=hours, id='organize_safety_net_job', replace_existing=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", default=5000, type=int)
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)