from flask import Flask, request, render_template, Response, make_response, jsonify, session
import requests
import json
import argparse
import os
import atexit
import math
from datetime import datetime, timedelta
from dotenv import load_dotenv
from requests.exceptions import RequestException
from flask_apscheduler import APScheduler

import logging # for gunicorn logging

from language_dict import language_dict

# --- SCHEDULER AND STATE SETUP ---
class Config:
    SCHEDULER_API_ENABLED = True

app = Flask(__name__)

if __name__ != '__main__':
    gunicorn_logger = logging.getLogger('gunicorn.error')
    app.logger.handlers = gunicorn_logger.handlers
    app.logger.setLevel(gunicorn_logger.level)

app.config.from_object(Config())
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

atexit.register(lambda: scheduler.shutdown())

IP_STATE_FILE = "/app/data/ip_state.json"
CONFIG_FILE = "/app/data/config.json"
load_dotenv()

# Define fallback values
FALLBACK_CONFIG = {
    "FLASK_SECRET_KEY": os.urandom(24).hex(),
    "MAM_API_URL": "https://www.myanonamouse.net",
    "QB_URL": "http://localhost:8080",
    "QB_CATEGORY": "",
    "QB_USERNAME": "admin",
    "QB_PASSWORD": "",
    "MAM_ID": "",
    "MAM_UID": "",
    "CF_ACCESS_CLIENT_ID": None,
    "CF_ACCESS_CLIENT_SECRET": None,
}

def load_config():
    config = FALLBACK_CONFIG.copy()
    env_config = {key: os.getenv(key) for key in config.keys()}
    env_config_filtered = {k: v for k, v in env_config.items() if v is not None}
    config.update(env_config_filtered)
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

def load_new_app_config():
    """Reload config and automatically fetch MAM_UID if it's missing."""
    new_config = load_config()

    # If MAM_UID is missing but MAM_ID is present, try to fetch it
    if not new_config.get("MAM_UID") and new_config.get("MAM_ID"):
        app.logger.info("MAM_UID is not set. Attempting to fetch from API...")
        try:
            api_url = new_config.get("MAM_API_URL", FALLBACK_CONFIG["MAM_API_URL"])
            cookies = {"mam_id": new_config["MAM_ID"]}
            response = requests.get(f"{api_url}/jsonLoad.php", cookies=cookies, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if uid := data.get("uid"):
                uid_str = str(uid)
                app.logger.info(f"Successfully fetched MAM_UID: {uid_str}")
                new_config["MAM_UID"] = uid_str
                save_config(new_config) # Save the newly fetched UID
            else:
                app.logger.warning("Fetched data from MAM API, but 'uid' key was not found.")
        except (RequestException, json.JSONDecodeError) as e:
            app.logger.error(f"Failed to fetch MAM_UID from API: {e}")

    # Continue loading config into the app
    app.secret_key = new_config["FLASK_SECRET_KEY"]
    app.config.update(new_config)
    
    app.config["BASE_HEADERS"] = {
        "CF-Access-Client-Id": new_config.get("CF_ACCESS_CLIENT_ID"),
        "CF-Access-Client-Secret": new_config.get("CF_ACCESS_CLIENT_SECRET"),
    }
    
    global mam_session_cookies
    mam_session_cookies = {"mam_id": app.config.get("MAM_ID"), "uid": app.config.get("MAM_UID")}

load_new_app_config()

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

def force_update_ip():
    """Directly calls the MAM dynamic seedbox API to update the IP, bypassing change checks."""
    with app.app_context():
        app.logger.info("Forcing manual IP update for dynamic seedbox.")

        if not app.config.get("MAM_ID"):
            app.logger.warning("MAM_ID not set in config. Skipping manual IP update.")
            return

        api_cookies = {"mam_id": app.config.get("MAM_ID")}

        try:
            update_url = "https://t.myanonamouse.net/json/dynamicSeedbox.php"
            update_response = requests.get(update_url, cookies=api_cookies, timeout=15)
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

        except (RequestException, json.JSONDecodeError) as e:
            app.logger.error(f"Error calling dynamic seedbox update API during manual trigger: {e}")

@scheduler.task('interval', id='ip_check_job', hours=3, misfire_grace_time=900)
def check_and_update_ip():
    """Periodically checks public IP and updates MAM's dynamic seedbox IP if it has changed."""
    with app.app_context():
        app.logger.info("Running scheduled job: Check and Update IP.")
        
        if not app.config.get("MAM_ID"):
            app.logger.warning("MAM_ID not set in config. Skipping dynamic IP update.")
            return

        api_cookies = {"mam_id": app.config.get("MAM_ID")}
        
        try:
            ip_check_url = f"{app.config.get('MAM_API_URL')}/json/jsonIp.php"
            response = requests.get(ip_check_url, cookies=api_cookies, timeout=10)
            response.raise_for_status()
            current_ip = response.json().get("ip")
            if not current_ip:
                app.logger.error("IP check API did not return an IP address.")
                return
        except (RequestException, json.JSONDecodeError) as e:
            app.logger.error(f"Failed to get current IP from MAM API: {e}")
            return
            
        last_ip = load_ip_state()
        app.logger.info(f"Current IP: {current_ip}, Last known IP: {last_ip}")

        if current_ip == last_ip:
            app.logger.info("IP address has not changed. No update needed.")
            return

        app.logger.info(f"IP address has changed from {last_ip} to {current_ip}. Updating dynamic seedbox IP.")
        force_update_ip()

# Schedule the IP check to run 5 seconds after startup, now that the function is defined.
with app.app_context():
    if not scheduler.get_job('initial_ip_check_job'):
        scheduler.add_job(
            id='initial_ip_check_job',
            func=check_and_update_ip,
            trigger='date',
            run_date=datetime.now() + timedelta(seconds=5)
        )
        
# --- SESSION AND API HELPERS ---
QB_SESSION = None

def update_cookies(response):
    """Extract and update cookies from the API response."""
    global mam_session_cookies
    if "set-cookie" in response.headers:
        cookies = response.cookies.get_dict()
        mam_session_cookies.update(cookies)

def login_mam():
    url = app.config.get("MAM_API_URL")
    if not url: return False
    if not all([mam_session_cookies.get("mam_id"), mam_session_cookies.get("uid")]):
        return False
    response = requests.get(f"{url}/jsonLoad.php", cookies=mam_session_cookies)
    if response.status_code == 200:
        if new_cookies := response.cookies.get_dict():
            mam_session_cookies.update(new_cookies)
        return True
    return False

def login_qbittorrent():
    qb_url, username, password = app.config.get("QB_URL"), app.config.get("QB_USERNAME"), app.config.get("QB_PASSWORD")
    if not all([qb_url, username, password]): return False
    session_obj = requests.Session()
    try:
        response = session_obj.post(f"{qb_url}/api/v2/auth/login", data={'username': username, 'password': password}, headers=app.config.get("BASE_HEADERS", {}))
        if "Ok" in response.text:
            session['qb_session'] = session_obj.cookies.get_dict()
            return True
    except RequestException: return False
    return False

# --- FLASK ROUTES ---
@app.route('/mam/status', methods=['GET'])
def mam_status(): return jsonify({'status': 'connected' if login_mam() else 'not connected'})

@app.route('/qb/status', methods=['GET'])
def qb_status():
    if 'qb_session' not in session and not login_qbittorrent():
        return jsonify({"status": "error", "message": "Unable to connect to qBittorrent."}), 503
    session_obj = requests.Session()
    session_obj.cookies.update(session['qb_session'])
    try:
        response = session_obj.get(f"{app.config['QB_URL']}/api/v2/app/version", headers=app.config.get("BASE_HEADERS", {}))
        response.raise_for_status()
        return jsonify({"status": "success", "message": "qBittorrent is connected."}), 200
    except RequestException as e:
        return jsonify({"status": "error", "message": f"Failed to connect: {e}"}), 503

@app.route('/qb/categories', methods=['GET'])
def qb_categories():
    if 'qb_session' not in session and not login_qbittorrent():
        return jsonify({'error': 'Not connected to qBittorrent'}), 401
    session_obj = requests.Session()
    session_obj.cookies.update(session['qb_session'])
    response = session_obj.get(f"{app.config['QB_URL']}/api/v2/torrents/categories", headers=app.config.get("BASE_HEADERS", {}))
    return jsonify(response.json()) if response.ok else (jsonify({'error': 'Failed to fetch categories'}), response.status_code)

@app.route('/mam/user_data', methods=['GET'])
def mam_user_data():
    """Fetches user data from the MAM API."""
    if not login_mam():
        return jsonify({'error': 'Not logged into MAM'}), 401

    try:
        api_url = f"{app.config.get('MAM_API_URL')}/jsonLoad.php"
        response = requests.get(api_url, cookies=mam_session_cookies, timeout=10)
        update_cookies(response)
        response.raise_for_status()
        
        user_data = response.json()
        
        # Optionally format numbers for better display
        if seedbonus := user_data.get("seedbonus"):
            user_data["seedbonus_formatted"] = f"{seedbonus:,}"

        return jsonify(user_data)

    except (RequestException, json.JSONDecodeError) as e:
        app.logger.error(f"Failed to fetch MAM user data: {e}")
        return jsonify({'error': 'Failed to fetch data from MAM API'}), 503

@app.route('/qb/add', methods=['POST'])
def qb_add_torrent():
    if 'qb_session' not in session and not login_qbittorrent():
        return jsonify({'error': 'Not connected to qBittorrent'}), 401

    incoming_data = request.get_json()
    if not incoming_data:
        app.logger.error("Received empty or non-JSON payload for /qb/add")
        return jsonify({'error': 'Invalid request: No JSON body found'}), 400

    app.logger.info(f"Received /qb/add request with payload: {incoming_data}")

    torrent_url = incoming_data.get('torrent_url') or incoming_data.get('url')
    
    if not torrent_url or not isinstance(torrent_url, str) or not torrent_url.strip():
        app.logger.error("FATAL: The 'torrent_url' in the request payload was empty.")
        return jsonify({'error': "An empty torrent_url was sent from the browser."}), 400

    category = incoming_data.get('category', '')
    qb_url = app.config['QB_URL']

    payload = {
        'urls': torrent_url,
        'category': category
    }

    custom_headers = app.config.get("BASE_HEADERS", {}).copy()
    custom_headers['Referer'] = qb_url

    session_obj = requests.Session()
    session_obj.cookies.update(session['qb_session'])

    try:
        app.logger.info(f"Attempting to add torrent via URL to qBittorrent: {torrent_url}")
        response = session_obj.post(
            f"{qb_url}/api/v2/torrents/add",
            data=payload,
            headers=custom_headers
        )
        response.raise_for_status()

        if "Ok." in response.text:
            app.logger.info("SUCCESS: Torrent added to qBittorrent.")
            return jsonify({'message': 'Torrent added successfully'})
        else:
            error_message = f"qBittorrent rejected the torrent. Response: {response.text or '[No Response Body]'}"
            app.logger.error(error_message)
            return jsonify({'error': error_message}), 400

    except RequestException as e:
        app.logger.error(f"Failed to send 'add torrent' request to qBittorrent: {e}")
        return jsonify({'error': f'Failed to communicate with qBittorrent: {e}'}), 503



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
        r["added"] = format_date(r.get("added", "Unknown"))
        filetype_score = {'m4b': 50, 'mp3': 30}.get(r.get('filetype'), 10)
        seeders_score = (r.get('seeders', 0) / max_seeders * 30) if max_seeders > 0 else 0
        r['score'] = round(filetype_score + seeders_score, 1)
    return sorted(results, key=lambda x: x['score'], reverse=True)

@app.route('/mam/search', methods=['GET'])
def mam_search():
    if not login_mam(): return render_template("partials/results.html", error_message="Login to MyAnonamouse failed. Check your MAM_ID and MAM_UID cookies in settings.")
    query = request.args.get("query", "")
    if not query: return render_template("partials/results.html", results=[])

    params = {
        "tor[text]": query,
        "tor[sortType]": "default", "perpage": 50, "thumbnail": "true", "dlLink": "true",
        "tor[browse_lang][]": language_dict.get(request.args.get("language", "English"), 1),
        "tor[srchIn][title]": "on" if request.args.get("search_in_title") else "off",
        "tor[srchIn][author]": "on" if request.args.get("search_in_author") else "off",
        "tor[srchIn][narrator]": "on" if request.args.get("search_in_narrator") else "off",
    }
    if (media_type := request.args.get("media_type", "13")) != "all":
        params["tor[main_cat][]"] = media_type

    headers = {"Cookie": "; ".join([f"{k}={v}" for k, v in mam_session_cookies.items()])}
    try:
        response = requests.get(f"{app.config['MAM_API_URL']}/tor/js/loadSearchJSONbasic.php", params=params, headers=headers)
        update_cookies(response)
        
        response.raise_for_status()
        json_data = response.json()
        results = json_data.get("data", [])

        # --- THIS IS THE FIX ---
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
        
        qb_status_response, status_code = qb_status()
        qb_status_json = qb_status_response.get_json()
        qb_connected = qb_status_json.get("status") == "success"
        
        categories = {}
        if qb_connected:
            categories_response = qb_categories()
            if categories_response.status_code == 200:
                categories = categories_response.get_json()
        
        return render_template("partials/results.html", results=ranked, QB_STATUS="CONNECTED" if qb_connected else "NOT CONNECTED", categories=categories, QB_CATEGORY=app.config.get("QB_CATEGORY"))
    except RequestException as e:
        return render_template("partials/results.html", error_message=f"Error connecting to MAM API: {e}")
    except json.JSONDecodeError:
        return render_template("partials/results.html", error_message="Failed to decode API response. Your session cookie might be invalid.")



@app.route("/")
def index():
    return render_template("index.html", **app.config)

@app.route("/proxy_thumbnail")
def proxy_thumbnail():
    url = request.args.get("url")
    if not url:
        return "No URL provided", 400
    
    try:
        response = requests.get(url, cookies=mam_session_cookies, stream=True, timeout=10)
        response.raise_for_status()
        
        return Response(
            response.iter_content(chunk_size=1024),
            content_type=response.headers.get("Content-Type"),
            headers={"Cache-Control": "public, max-age=86400"}
        )
    except RequestException as e:
        app.logger.error(f"Thumbnail proxy failed for URL {url}. Reason: {e}")
        return "Failed to fetch image", 500

@app.route("/update_settings", methods=["POST"])
def update_settings():
    form = request.form
    config_to_update = app.config.copy()
    
    for key in FALLBACK_CONFIG.keys():
        if key in form:
            config_to_update[key] = form[key]
    if form.get("QB_PASSWORD"):
        config_to_update["QB_PASSWORD"] = form.get("QB_PASSWORD")

    save_config(config_to_update)
    load_new_app_config()

    # Manually trigger a forced IP update after saving new credentials.
    job_id = 'manual_ip_update_job'
    run_time = datetime.now() + timedelta(seconds=2) # Run 2 seconds after the request finishes
    if scheduler.get_job(job_id):
        scheduler.reschedule_job(job_id, trigger='date', run_date=run_time)
    else:
        scheduler.add_job(id=job_id, func=force_update_ip, trigger='date', run_date=run_time)
    
    return jsonify({"status": "success", "message": "Settings updated! A manual IP update has been triggered."})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Flask app.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address.")
    parser.add_argument("--port", default=5000, type=int, help="Port number.")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=True, use_reloader=False)
