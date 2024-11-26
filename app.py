from flask import Flask, request, render_template, Response, make_response, jsonify, session
import requests, json, argparse, os
import math
from datetime import datetime
from dotenv import load_dotenv
from requests.exceptions import RequestException

from language_dict import language_dict

app = Flask(__name__)

# Load .env file
load_dotenv()

# Set the secret key for sessions
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24)) 

# Base API URL
app.config["MAM_URL"] = os.getenv("MAM_API_URL", "https://www.myanonamouse.net")
app.config["QB_URL"] = os.getenv("QB_URL", "http://localhost:8080")  # Default example
app.config["QB_USERNAME"] = os.getenv("QB_USERNAME", "admin")
app.config["QB_PASSWORD"] = os.getenv("QB_PASSWORD", "")
app.config["MAM_ID"] = os.getenv("MAM_ID", "")
app.config["MAM_UID"] = os.getenv("MAM_UID", "")

app.config['BASE_HEADERS'] = {
    "CF-Access-Client-Id": os.environ.get("CFAccessClientId"),
    "CF-Access-Client-Secret": os.environ.get("CFAccessClientSecret")
}

mam_session_cookies = {
    "mam_id": app.config["MAM_ID"],
    "uid": app.config["MAM_UID"],
}

# QBITTORRENT SESSION
QB_SESSION = None

def update_cookies(response):
    """Extract and update cookies from the API response."""
    global mam_session_cookies
    if "set-cookie" in response.headers:
        cookies = response.cookies.get_dict()
        mam_session_cookies.update(cookies)


# Function to login to MyAnonamouse
def login_mam():
    url = app.config["MAM_URL"]
    response = requests.get(
        f"{url}/jsonLoad.php",
        cookies=mam_session_cookies,
    )
    if response.status_code == 200:
        # Update cookies if the server sends new ones
        new_cookies = response.cookies.get_dict()
        mam_session_cookies.update(new_cookies)
        return True
    return False

# Function to login to qBittorrent
def login_qbittorrent():
    qb_url = app.config["QB_URL"]
    data = {
        'username': app.config["QB_USERNAME"],
        'password': app.config["QB_PASSWORD"],
    }
    session_obj = requests.Session()
    headers = app.config.get("BASE_HEADERS", {})
    response = session_obj.post(f"{qb_url}/api/v2/auth/login", data=data, headers=headers)
    if response.status_code == 200 and "Ok" in response.text:
        session['qb_session'] = session_obj.cookies.get_dict()
        return True
    return False

@app.route('/mam/status', methods=['GET'])
def mam_status():
    if login_mam():
        return jsonify({'status': 'connected'})
    else:
        return jsonify({'status': 'not connected'})
    
@app.route('/qb/status', methods=['GET'])
def qb_status():
    qb_url = app.config["QB_URL"]
    if 'qb_session' not in session:
        if not login_qbittorrent():
            return jsonify({'status': 'not connected'})
    session_obj = requests.Session()
    session_obj.cookies.update(session['qb_session'])
    headers = app.config.get("BASE_HEADERS", {})
    response = session_obj.get(f"{qb_url}/api/v2/app/version", headers=headers)
    if response.status_code == 200:
        return jsonify({'status': 'connected'})
    return jsonify({'status': 'not connected'})

@app.route('/qb/categories', methods=['GET'])
def qb_categories():
    qb_url = app.config["QB_URL"]
    if 'qb_session' not in session:
        if not login_qbittorrent():
            return jsonify({'error': 'Not connected to qBittorrent'}), 401
    session_obj = requests.Session()
    session_obj.cookies.update(session['qb_session'])
    headers = app.config.get("BASE_HEADERS", {})
    response = session_obj.get(f"{qb_url}/api/v2/torrents/categories", headers=headers)
    if response.status_code == 200:
        return jsonify(response.json())
    return jsonify({'error': 'Failed to fetch categories'}), response.status_code

@app.route('/qb/add', methods=['POST'])
def qb_add_torrent():
    qb_url = app.config["QB_URL"]
    if 'qb_session' not in session:
        if not login_qbittorrent():
            return jsonify({'error': 'Not connected to qBittorrent'}), 401
    torrent_url = request.json.get('torrent_url')
    category = request.json.get('category', '')
    session_obj = requests.Session()
    session_obj.cookies.update(session['qb_session'])
    headers = app.config.get("BASE_HEADERS", {})
    data = {
        'urls': torrent_url,
        'category': category,
    }
    response = session_obj.post(f"{qb_url}/api/v2/torrents/add", data=data, headers=headers)
    if response.status_code == 200:
        return jsonify({'message': 'Torrent added successfully'})
    return jsonify({'error': 'Failed to add torrent'}), response.status_code

@app.route('/mam/search', methods=['GET'])
def mam_search():
    """
    Perform a search on MyAnonamouse (MAM) API with filters.
    Query parameters:
      - query: The search term
      - search_in_title: Search in title (default: off)
      - search_in_author: Search in author (default: off)
      - search_in_narrator: Search in narrator (default: off)
      - media_type: Media type filter (default: 13, Audiobooks)
      - language: Language filter (default: English)
      - perpage: Results per page (default: 10)
      - page: Page number (default: 1)
    """
    if not login_mam():
        return jsonify({'error': 'Failed to connect to MyAnonamouse'}), 401

    # Retrieve query parameters
    search_query = request.args.get("query", "")
    if not search_query:
        return jsonify({'error': 'Search query is required'}), 400

    search_in_title = request.args.get("search_in_title", "off") == "on"
    search_in_author = request.args.get("search_in_author", "off") == "on"
    search_in_narrator = request.args.get("search_in_narrator", "off") == "on"
    media_type = request.args.get("media_type", "13")  # Default to Audiobooks
    language = request.args.get("language", "English")
    per_page = int(request.args.get("perpage", 10))
    page = int(request.args.get("page", 1))
    start_number = (page - 1) * per_page

    # Map language to its corresponding ID
    language_id = language_dict.get(language, 1)  # Default to English

    # Prepare API parameters
    params = {
        "tor[text]": search_query,
        "tor[sortType]": "default",
        "tor[startNumber]": start_number,
        "perpage": per_page,
        "thumbnail": "true",
        "dlLink": "true",
        "tor[browse_lang][]": language_id,
        "tor[srchIn][title]": search_in_title,
        "tor[srchIn][author]": search_in_author,
        "tor[srchIn][narrator]": search_in_narrator,
    }

    if media_type != "all":
        params["tor[main_cat][]"] = media_type

    # Send request to MAM API
    headers = app.config.get("BASE_HEADERS", {})
    headers["Cookie"] = "; ".join([f"{k}={v}" for k, v in mam_session_cookies.items()])
    response = requests.get(f"{app.config['MAM_URL']}/tor/js/loadSearchJSONbasic.php", params=params, headers=headers)

    if response.status_code == 200:
        results = response.json()
        return jsonify({
            "results": results.get("data", []),
            "total_results": results.get("total", 0),
            "page": page,
            "total_pages": -(-results.get("total", 0) // per_page),  # Ceiling division
        })
    else:
        return jsonify({
            'error': 'Failed to perform search',
            'status_code': response.status_code,
            'message': response.text,
        }), response.status_code
    
@app.route("/", methods=["GET", "POST"])
def search():
    global QB_SESSION
    categories = {}
    # Get search parameters, if present
    search_query = request.args.get("query", "")
    search_in_title = request.args.get("search_in_title", "off") == "on"
    search_in_author = request.args.get("search_in_author", "off") == "on"
    search_in_narrator = request.args.get("search_in_narrator", "off") == "on"
    media_type = request.args.get("media_type", "13")  # Default to Audiobooks
    language = request.args.get("language", "English")  # Default to English
    per_page = int(request.args.get("perpage", 10))  # number of results
    page = int(request.args.get("page", 1))
    start_number = (page - 1) * per_page

    # Map the language to its corresponding integer
    language_id = language_dict.get(language, 1)  # Default to English (1)

    # Prepare API parameters
    params = {
        "tor[text]": search_query,
        "tor[sortType]": "default",
        "tor[startNumber]": start_number,
        "perpage": per_page,
        "thumbnail": "true",  # Always include thumbnails,
        "dlLink": "true", # show a torrent link that doesn't require auth
        "tor[browse_lang][]": language_id, 
    }

    # Add filters
    params["tor[srchIn][title]"] = search_in_title
    params["tor[srchIn][author]"] = search_in_author
    params["tor[srchIn][narrator]"] = search_in_narrator

    if media_type != "all":
        params["tor[main_cat][]"] = media_type

    headers = {
        "Cookie": "; ".join([f"{k}={v}" for k, v in mam_session_cookies.items()])
    }
    QB_STATUS = "not connected"
    if not QB_SESSION:
        login_response = login_qbittorrent()

        if login_response is None:
            QB_STATUS = "not connected (login failed)"
        elif login_response.status_code == 200 and login_response.text == "Ok.":
            QB_STATUS = "CONNECTED"
        else:
            QB_STATUS = "not connected (authentication failed)"
            

    if search_query:
        response = requests.get("{app.config['MAM_URL']}/tor/js/loadSearchJSONbasic.php", headers=headers, params=params)
        categories = get_categories()
        # Update cookies
        update_cookies(response)

        if response.status_code == 200:
            results = response.json()
            total_results = results.get("total", 0)
            total_pages = math.ceil(total_results / per_page)
            data = results.get("data", [])

            # Parse author and narrator info
            for item in data:
                item["author_info"] = parse_author_info(item.get("author_info", ""))
                item["narrator_info"] = parse_author_info(item.get("narrator_info", ""))
                item["added"] = format_date(item.get("added", "Unknown"))
            ranked_results = rank_results(data)
            data = ranked_results
            # data = check_existing_torrents(ranked_results)
        else:
            total_results = 0
            total_pages = 0
            data = []
    else:
        total_results = 0
        total_pages = 0
        data = []

    # AJAX request for search query
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":

        if total_results == 0:
            # If no results, render a "No results" message
            return render_template("partials/results.html", no_results=True)

        ajax_response = make_response(render_template(
            "partials/results.html",  # Create a partial template for the results
            results=data,
            categories=categories
        ))
        # Set Cache-Control header for 1 day (86400 seconds)
        ajax_response.headers["Cache-Control"] = "public, max-age=86400"
        ajax_response.headers["Vary"] = "Accept-Encoding"
        return ajax_response
        
    # response for initial page load
    response = make_response(render_template(
        "index.html",
        query=search_query,
        search_in_title=search_in_title,
        search_in_author=search_in_author,
        search_in_narrator=search_in_narrator,
        media_type=media_type,
        language=language,
        results=data,
        page=page,
        total_pages=total_pages,
        categories=categories,
        QB_URL=app.config["QB_URL"],
        QB_USERNAME=app.config["QB_USERNAME"],
        QB_PASSWORD="",
        QB_STATUS=QB_STATUS,
        MAM_ID=app.config["MAM_ID"],
        MAM_UID=app.config["MAM_UID"],
    ))

    # Set Cache-Control header for 1 day (86400 seconds)
    response.headers["Cache-Control"] = "public, max-age=86400"
    response.headers["Vary"] = "Accept-Encoding"
    return response

def parse_author_info(info):
    """Parse JSON fields like author or narrator info."""
    try:
        authors = json.loads(info)  # Use the standard `json` module
        return ", ".join(authors.values())
    except (json.JSONDecodeError, TypeError):
        return "Unknown"
def format_date(date_string):
    """Convert the API date string to YYYY-MM-DD format."""
    try:
        # Assuming the API returns the date in ISO 8601 format or similar
        date_object = datetime.strptime(date_string, "%Y-%m-%d %H:%M:%S")  # Adjust if needed
        return date_object.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return "Unknown"
    
def calculate_score(result, max_seeders, max_normalized_downloads, newest_date):
    from datetime import datetime

    # Filetype scoring (max 50 points)
    filetype_scores = {'m4b': 50, 'mp3': 30}
    filetype_score = filetype_scores.get(result['filetype'], 10)
    
    # Seeders scoring (max 30 points)
    seeders_score = (result['seeders'] / max_seeders) * 30 if max_seeders > 0 else 0
    
    # Age of torrent in years
    torrent_date = datetime.strptime(result['added'], '%Y-%m-%d')
    torrent_age_years = max((newest_date - torrent_date).days / 365.25, 0.1)  # Prevent division by zero
    
    # Downloads per year
    downloads_per_year = result['times_completed'] / torrent_age_years
    
    # Normalize downloads per year to a 20-point scale
    normalized_downloads_score = (downloads_per_year / max_normalized_downloads) * 20 if max_normalized_downloads > 0 else 0
    
    # Composite score
    total_score = filetype_score + seeders_score + normalized_downloads_score
    
    return {
        'filetype_score': filetype_score,
        'seeders_score': seeders_score,
        'normalized_downloads_score': normalized_downloads_score,
        'total_score': total_score
    }

def rank_results(search_results):
    from datetime import datetime

    # Get newest date
    added_dates = [datetime.strptime(result['added'], '%Y-%m-%d') for result in search_results]
    newest_date = max(added_dates) if added_dates else datetime.now()
    
    # Determine maximum seeders and downloads per year
    max_seeders = max(result['seeders'] for result in search_results) if search_results else 0
    
    # Calculate max downloads per year
    max_normalized_downloads = 0
    for result in search_results:
        torrent_date = datetime.strptime(result['added'], '%Y-%m-%d')
        torrent_age_years = max((newest_date - torrent_date).days / 365.25, 0.1)
        downloads_per_year = result['times_completed'] / torrent_age_years
        if downloads_per_year > max_normalized_downloads:
            max_normalized_downloads = downloads_per_year
    
    # Add scores to results
    for result in search_results:
        score_data = calculate_score(result, max_seeders, max_normalized_downloads, newest_date)
        score_data['total_score'] = round(score_data['total_score'], 1)  # Round total_score to one decimal place
        result['score'] = score_data

    # Sort results by total_score (descending)
    ranked_results = sorted(search_results, key=lambda x: x['score']['total_score'], reverse=True)
    return ranked_results

def check_existing_torrents(search_results):
    """Check if torrents from the API results are already in qBittorrent."""
    # Authenticate with qBittorrent
    session = requests.Session()
    login_response = session.post(f"{app.config['QB_URL']}/api/v2/auth/login", data={
        "username": app.config["QB_USERNAME"],
        "password": app.config["QB_PASSWORD"]
    },headers=app.config['BASE_HEADERS'])

    if login_response.status_code != 200 or login_response.text != "Ok.":
        raise Exception("Failed to authenticate with qBittorrent")

    # Collect all hashes from the search results
    hashes = [result.get("hash", "").upper() for result in search_results if result.get("hash")]
    #if not hashes:
        #return search_results  # No hashes to check

    # Query qBittorrent for these hashes
    hash_filter = "|".join(hashes)  # Join hashes with "|" as required by the API
    torrents_response = session.get(f"{app.config['QB_URL']}/api/v2/torrents/info", params={"hashes": hash_filter})

    if torrents_response.status_code != 200:
        raise Exception("Failed to fetch filtered torrents from qBittorrent")

    # Extract existing hashes from the qBittorrent response
    existing_hashes = {torrent["hash"] for torrent in torrents_response.json()}

    # Mark results as inClient based on existing hashes
    for result in search_results:
        result_hash = result.get("hash", "").upper()
        result["inClient"] = result_hash in existing_hashes

    return search_results

@app.route("/proxy_thumbnail")
def proxy_thumbnail():
    """Proxy thumbnails to handle cookies and bypass CORS issues."""
    url = request.args.get("url")
    if not url:
        return "No URL provided", 400

    headers = {"Cookie": "; ".join([f"{k}={v}" for k, v in mam_session_cookies.items()])}
    response = requests.get(url, headers=headers, stream=True)

    if response.status_code == 200:
        proxy_response = Response(response.content, content_type=response.headers.get("Content-Type"))
        # Add Cache-Control headers for the browser
        proxy_response.headers["Cache-Control"] = "public, max-age=86400"  # Cache for 1 day
        return proxy_response
    else:
        return "Failed to fetch image", 500

# def login_qbittorrent():
#     global QB_SESSION
#     if not QB_SESSION:
#         QB_SESSION = requests.Session()
    
#     try:
#         login_response = QB_SESSION.post(
#             f"{app.config['QB_URL']}/api/v2/auth/login", 
#             data={
#                 "username": app.config["QB_USERNAME"],
#                 "password": app.config["QB_PASSWORD"]
#             },
#             headers=app.config['BASE_HEADERS']
#         )
        
#         if login_response.status_code != 200 or login_response.text != "Ok.":
#             raise Exception("Failed to authenticate with qBittorrent")
        
#         return login_response

#     except requests.exceptions.ConnectionError as e:
#         # Handle connection errors
#         print(f"Connection error: {e}")
#         return None
#     except requests.exceptions.RequestException as e:
#         # Handle other types of HTTP errors
#         print(f"HTTP error occurred: {e}")
#         return None
#     except Exception as e:
#         # Catch-all for any other exceptions
#         print(f"Unexpected error: {e}")
#         return None
    
@app.route('/get_qb_status', methods=['GET'])
def get_qb_status():
    global QB_SESSION
    if QB_SESSION:
        qb_status = "CONNECTED"
    else:
        qb_status = "DISCONNECTED"
    return jsonify({"status": qb_status})

@app.route("/add_to_qbittorrent", methods=["POST"])
def add_to_qbittorrent():
    torrent_url = request.form.get("torrent_url")
    category = request.form.get("category", "").strip()  # Optional category

    if not torrent_url:
        return {"error": "No torrent URL provided"}, 400

    session = requests.Session()
    login_response = session.post(f"{app.config['QB_URL']}/api/v2/auth/login", data={
        "username": app.config["QB_USERNAME"],
        "password": app.config["QB_PASSWORD"]
    },
    headers=app.config['BASE_HEADERS']
    )

    if login_response.status_code != 200 or login_response.text != "Ok.":
        return {"error": "Failed to authenticate with qBittorrent"}, 500

    # Send the torrent URL and category to qBittorrent
    add_data = {
        "urls": torrent_url,
        "content_layout": "Subfolder",  # Example layout option
    }
    if category:  # Include category if provided
        add_data["category"] = category

    add_response = session.post(f"{app.config['QB_URL']}/api/v2/torrents/add", data=add_data, headers=app.config['BASE_HEADERS'])

    if add_response.status_code == 200:
        return jsonify({"status": "success", "message": "Torrent added successfully"}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to add torrent to qBittorrent"}), 500


def get_categories():
    global QB_SESSION
    if not QB_SESSION:
        QB_SESSION = requests.Session()
    # session = requests.Session()

    login_response = QB_SESSION.post(f"{app.config['QB_URL']}/api/v2/auth/login", data={
        "username": app.config["QB_USERNAME"],
        "password": app.config["QB_PASSWORD"],
        },
        headers=app.config['BASE_HEADERS']
        )

    categories = {}  # Default to an empty dictionary

    if login_response.status_code == 200 and login_response.text == "Ok.":
        categories_response = QB_SESSION.get(f"{app.config['QB_URL']}/api/v2/sync/maindata?rid=0",headers=app.config['BASE_HEADERS'])
        if categories_response.status_code == 200:
            try:
                # Extract categories
                categories = categories_response.json().get("categories", {})
                if not isinstance(categories, dict):
                    categories = {}
            except Exception as e:
                print("Error parsing categories:", e)
                categories = {}
        else:
            print("Failed to fetch categories. Response status:", categories_response.status_code)
    else:
        print("Failed to authenticate with qBittorrent.")

    return categories 

@app.route("/update_settings", methods=["POST"])
def update_settings():
    app.config["QB_URL"] = request.form.get("QB_URL", app.config["QB_URL"])
    app.config["QB_USERNAME"] = request.form.get("QB_USERNAME", app.config["QB_USERNAME"])
    
    # Update password only if not blank
    qb_password = request.form.get("QB_PASSWORD")
    if qb_password:  # Only update if QB_PASSWORD is not empty or None
        app.config["QB_PASSWORD"] = qb_password

    app.config["MAM_ID"] = request.form.get("MAM_ID", app.config["MAM_ID"])

    # (Optional) Save back to .env (if needed)
    # Uncomment this if saving to .env is required
    # with open('.env', 'w') as f:
    #     f.write(f"QB_URL={app.config['QB_URL']}\n")
    #     f.write(f"QB_USERNAME={app.config['QB_USERNAME']}\n")
    #     f.write(f"QB_PASSWORD={app.config['QB_PASSWORD']}\n")
    #     f.write(f"MAM_ID={app.config['MAM_ID']}\n")

    return jsonify({"status": "success", "message": "Settings updated successfully!"})

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Flask app with custom address and port.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", default=5000, type=int, help="Port number to bind to (default: 5000)")
    args = parser.parse_args()

    # Run the app with specified host and port
    app.run(host=args.host, port=args.port, debug=True)