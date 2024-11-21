from flask import Flask, request, render_template, Response
import requests
import math

app = Flask(__name__)

# Replace with your API base URL and session cookie
API_URL = "https://www.myanonamouse.net/tor/js/loadSearchJSONbasic.php"
COOKIE = {"Cookie": "mam_id=qiII%2Bg%2F%2Bdacp94FgTI%2Focf3SMGJfuFOAwx82xtvwjc2MzgOBsy%2FFVvVENrv0of6KwsZmTJBbImP700x10AHbxzIsfVE8XWfKhDd5Q%2BODYwkHgWVdoL%2FfzdYmjxqloxySXhTUNe2iy4n9NEqVAOHxldo1TPR56B5JHon0qQezJ85e341n2ndN5VKjte2P0ckq4rM9CenKbSGRIWOvBMgqmREx%2BXsTAc7UnljkA8HDapuROi5c9xQb3WB8%2B2%2Bo%2BQSsmDlXPUa3LDmpN8xPQo%2BLaVWmXzGg%2FvMNhVLZ"}

@app.route("/", methods=["GET", "POST"])
def search():
    # Get search parameters from the form
    search_query = request.args.get("query", "")
    search_in_title = request.args.get("search_in_title", "off") == "on"
    search_in_author = request.args.get("search_in_author", "off") == "on"
    search_in_narrator = request.args.get("search_in_narrator", "off") == "on"
    media_type = request.args.get("media_type", "all")
    page = int(request.args.get("page", 1))
    per_page = 10
    start_number = (page - 1) * per_page

    # Prepare API parameters
    params = {
        "tor[text]": search_query,
        "tor[sortType]": "default",
        "tor[startNumber]": start_number,
        "perpage": per_page,
        "thumbnail": "true",
    }

    # Add search_in parameters
    params["tor[srchIn][title]"] = search_in_title
    params["tor[srchIn][author]"] = search_in_author
    params["tor[srchIn][narrator]"] = search_in_narrator

    # Add media type filter
    if media_type != "all":
        params["main_cat[]"] = media_type

    # Make API request
    if search_query:
        response = requests.get(API_URL, headers=COOKIE, params=params)
        if response.status_code == 200:
            results = response.json()
            total_results = results.get("total", 0)
            total_pages = math.ceil(total_results / per_page)
            data = results.get("data", [])
        else:
            total_results = 0
            total_pages = 0
            data = []
    else:
        total_results = 0
        total_pages = 0
        data = []

    return render_template(
        "index.html",
        query=search_query,
        search_in_title=search_in_title,
        search_in_author=search_in_author,
        search_in_narrator=search_in_narrator,
        media_type=media_type,
        results=data,
        page=page,
        total_pages=total_pages,
    )

@app.route("/proxy_thumbnail")
def proxy_thumbnail():
    url = request.args.get("url")
    if not url:
        return "No URL provided", 400
    headers = COOKIE
    response = requests.get(url, headers=headers, stream=True)
    return Response(response.content, content_type=response.headers.get("Content-Type"))

if __name__ == "__main__":
    app.run(debug=True)