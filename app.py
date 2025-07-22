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

from language_dict import language_dict

# --- SCHEDULER AND STATE SETUP ---
class Config:
    SCHEDULER_API_ENABLED = True

app = Flask(__name__)
app.config.from_object(Config())
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

IP_STATE_FILE = "ip_state.json"
CONFIG_FILE = "config.json"
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

QB_SESSION = None

def update_cookies(response):
    """Extract and update cookies from the API response."""
    global mam_session_cookies
    if "set-cookie" in response.headers:
        cookies = response.cookies.get_dict()
        mam_session_cookies.update(cookies)


# Function to login to MyAnonamouse
def login_mam():
    url = app.config.get("MAM_API_URL")
    if not url: return False
    # Make sure we have both cookies before trying to log in
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

@app.route('/qb/add', methods=['POST'])
def qb_add_torrent():
    if 'qb_session' not in session and not login_qbittorrent():
        return jsonify({'error': 'Not connected to qBittorrent'}), 401
    data = {'urls': request.json.get('torrent_url'), 'category': request.json.get('category', '')}
    session_obj = requests.Session()
    session_obj.cookies.update(session['qb_session'])
    response = session_obj.post(f"{app.config['QB_URL']}/api/v2/torrents/add", data=data, headers=app.config.get("BASE_HEADERS", {}))
    return jsonify({'message': 'Torrent added successfully'}) if response.ok else (jsonify({'error': 'Failed to add torrent'}), response.status_code)

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
        update_cookies(response)  # Update cookies
        
        response.raise_for_status()
        results = response.json().get("data", [])

        # ─── thumbnail fallback: use category icon if none provided ───
        for item in results:
            if not item.get('thumbnail'):
                cat = item.get('category', '')
                item['thumbnail'] = f"https://static.myanonamouse.net/pic/cats/3/{cat}.png"

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
    # Create a copy of the current config to modify
    config_to_update = app.config.copy()
    
    # Update values from the form
    for key in FALLBACK_CONFIG.keys():
        if key in form:
            config_to_update[key] = form[key]
    if form.get("QB_PASSWORD"):
        config_to_update["QB_PASSWORD"] = form.get("QB_PASSWORD")

    # Save the updated configuration
    save_config(config_to_update)
    # Reload all settings, which will also trigger the UID fetch if needed
    load_new_app_config()

    # Manually trigger an IP check after saving new credentials
    job_id = 'ip_check_job_manual'
    run_time = datetime.now() + timedelta(seconds=2)
    if scheduler.get_job(job_id):
        scheduler.reschedule_job(job_id, trigger='date', run_date=run_time)
    else:
        scheduler.add_job(id=job_id, func=check_and_update_ip, trigger='date', run_date=run_time)
    
    return jsonify({"status": "success", "message": "Settings updated successfully!"})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Flask app.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address.")
    parser.add_argument("--port", default=5000, type=int, help="Port number.")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=True)