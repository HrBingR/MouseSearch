from flask import Flask, request, render_template, Response, make_response
import requests, json, argparse, os
import math
from datetime import datetime
from dotenv import load_dotenv

from language_dict import language_dict

app = Flask(__name__)

# Load .env file
load_dotenv()

# Base API URL
API_URL = os.getenv("MAM_API_URL", "https://www.myanonamouse.net/tor/js/loadSearchJSONbasic.php")

session_cookies = {
    "mam_id": os.getenv("MAM_ID", ""),
    "uid": os.getenv("MAM_UID", ""),
}

QB_URL = os.getenv("QB_URL", "http://localhost:8080")  # Replace with your qBittorrent URL, e.g., "http://localhost:8080"
QB_USERNAME = os.getenv("QB_USERNAME", "admin")
QB_PASSWORD = os.getenv("QB_PASSWORD", "adminadmin")

def update_cookies(response):
    """Extract and update cookies from the API response."""
    global session_cookies
    if "set-cookie" in response.headers:
        cookies = response.cookies.get_dict()
        session_cookies.update(cookies)

@app.route("/", methods=["GET", "POST"])
def search():
    # Get search parameters
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
        "Cookie": "; ".join([f"{k}={v}" for k, v in session_cookies.items()])
    }

    if search_query:
        response = requests.get(API_URL, headers=headers, params=params)

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
            data = check_existing_torrents(ranked_results)
        else:
            total_results = 0
            total_pages = 0
            data = []
    else:
        total_results = 0
        total_pages = 0
        data = []

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
    login_response = session.post(f"{QB_URL}/api/v2/auth/login", data={
        "username": QB_USERNAME,
        "password": QB_PASSWORD
    })

    if login_response.status_code != 200 or login_response.text != "Ok.":
        raise Exception("Failed to authenticate with qBittorrent")

    # Collect all hashes from the search results
    hashes = [result.get("hash", "").upper() for result in search_results if result.get("hash")]
    #if not hashes:
        #return search_results  # No hashes to check

    # Query qBittorrent for these hashes
    hash_filter = "|".join(hashes)  # Join hashes with "|" as required by the API
    torrents_response = session.get(f"{QB_URL}/api/v2/torrents/info", params={"hashes": hash_filter})

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

    headers = {"Cookie": "; ".join([f"{k}={v}" for k, v in session_cookies.items()])}
    response = requests.get(url, headers=headers, stream=True)

    if response.status_code == 200:
        proxy_response = Response(response.content, content_type=response.headers.get("Content-Type"))
        # Add Cache-Control headers for the browser
        proxy_response.headers["Cache-Control"] = "public, max-age=86400"  # Cache for 1 day
        return proxy_response
    else:
        return "Failed to fetch image", 500
    
@app.route("/add_to_qbittorrent", methods=["POST"])
def add_to_qbittorrent():
    """Adds a torrent to qBittorrent via its Web API."""
    torrent_url = request.form.get("torrent_url")
    
    if not torrent_url:
        return {"error": "No torrent URL provided"}, 400

    # Authenticate with qBittorrent
    session = requests.Session()
    login_response = session.post(f"{QB_URL}/api/v2/auth/login", data={
        "username": QB_USERNAME,
        "password": QB_PASSWORD
    })

    if login_response.status_code != 200 or login_response.text != "Ok.":
        return {"error": "Failed to authenticate with qBittorrent"}, 500

    # Send the torrent URL to qBittorrent
    add_response = session.post(f"{QB_URL}/api/v2/torrents/add", data={
        "urls": torrent_url,
        "category": "prowlarr",  # qBittorrent category
        "content_layout": "Subfolder", # create subfolder
        "cookie": session_cookies
    })

    if add_response.status_code == 200:
        return {"success": "Torrent added successfully"}
    else:
        return {"error": "Failed to add torrent to qBittorrent"}, 500

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the Flask app with custom address and port.")
    parser.add_argument("--host", default="127.0.0.1", help="Host address to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", default=5000, type=int, help="Port number to bind to (default: 5000)")
    args = parser.parse_args()

    # Run the app with specified host and port
    app.run(host=args.host, port=args.port, debug=True)