from flask import Flask, request, render_template, Response, make_response
import requests, json, argparse
import math
from datetime import datetime

app = Flask(__name__)

# Base API URL
API_URL = "https://www.myanonamouse.net/tor/js/loadSearchJSONbasic.php"

# Session cookies
session_cookies = {
    "mam_id": "_zXN0MpPPSXWWgMlJ0YLHvPUq9FRh56DRrciTUY908x85dl--29svP04D2mYQuAVDYj8IMWJMRF8ZUrHL9EWUHf5K96jotpO4Oirre13mhtWRS3iVJzXXp4AwgIuQ3r4uXIkNF56Rkffep9deKOGMMouNQqEaNGC_unaDHNj-utOM8uLPxVJtnXhNvIKdFoBaZuIPK-s9N_ZVwopt-dcRpdnhpQcxXx5K7zQVDq9PXuuU6kuXW8SDeLYkn2UvfgyYZwC4Hxgy1IcK8D6Ze1sYmgmkKSfVjCgwmEH",
    "uid": "221118",
}

QB_URL = "http://192.168.4.73:6767"  # qBittorrent Web UI URL
QB_USERNAME = "admin"  # Replace with your username
QB_PASSWORD = "Emulation5!"  # Replace with your password

language_dict = {
    "English": 1,
    "Afrikaans": 17,
    "Arabic": 32,
    "Bengali": 35,
    "Bosnian": 51,
    "Bulgarian": 18,
    "Burmese": 6,
    "Cantonese": 44,
    "Catalan": 19,
    "Chinese": 2,
    "Croatian": 49,
    "Czech": 20,
    "Danish": 21,
    "Dutch": 22,
    "Estonian": 61,
    "Farsi": 39,
    "Finnish": 23,
    "French": 36,
    "German": 37,
    "Greek": 26,
    "Greek, Ancient": 59,
    "Gujarati": 3,
    "Hebrew": 27,
    "Hindi": 8,
    "Hungarian": 28,
    "Icelandic": 63,
    "Indonesian": 53,
    "Irish": 56,
    "Italian": 43,
    "Japanese": 38,
    "Javanese": 12,
    "Kannada": 5,
    "Korean": 41,
    "Lithuanian": 50,
    "Latin": 46,
    "Latvian": 62,
    "Malay": 33,
    "Malayalam": 58,
    "Manx": 57,
    "Marathi": 9,
    "Norwegian": 48,
    "Polish": 45,
    "Portuguese": 34,
    "Brazilian Portuguese (BP)": 52,
    "Punjabi": 14,
    "Romanian": 30,
    "Russian": 16,
    "Scottish Gaelic": 24,
    "Sanskrit": 60,
    "Serbian": 31,
    "Slovenian": 54,
    "Spanish": 4,
    "Castilian Spanish": 55,
    "Swedish": 40,
    "Tagalog": 29,
    "Tamil": 11,
    "Telugu": 10,
    "Thai": 7,
    "Turkish": 42,
    "Ukrainian": 25,
    "Urdu": 15,
    "Vietnamese": 13,
    "Other": 47
}

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
        result['score'] = calculate_score(result, max_seeders, max_normalized_downloads, newest_date)
    
    # Sort results by total_score (descending)
    ranked_results = sorted(search_results, key=lambda x: x['score']['total_score'], reverse=True)
    return ranked_results

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