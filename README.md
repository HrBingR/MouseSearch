# MouseSearch

MouseSearch is a web-based search utility for MyAnonamouse (MAM) that allows you to search for torrents and send them directly to your qBittorrent client.

## Features

* **Advanced Search**: Search for audiobooks, e-books, and other media on MyAnonamouse with filters for title, author, narrator, media type, and language.
* **qBittorrent Integration**: Add torrents directly to your qBittorrent client from the search results.
* **Result Ranking**: Search results are intelligently ranked based on file type and the number of seeders to help you find the best torrents.
* **Dynamic IP Updater**: Automatically checks and updates your dynamic seedbox IP address with the MyAnonamouse tracker.
* **Status Dashboard**: View your MyAnonamouse user stats (ratio, upload, download, bonus points) and qBittorrent connection status at a glance.
* **Easy Configuration**: All settings can be managed through a simple web interface.

## Getting Started

### Prerequisites

* Docker and Docker Compose (if using the Docker installation method)
* Python 3.10+ (if running on bare metal)
* A MyAnonamouse account
* A qBittorrent instance

### Installation

You can run MouseSearch using Docker Compose (the recommended method) or on bare metal with Flask or Gunicorn.

#### Docker Compose (Recommended)

This is the simplest way to get started.

1.  **Create a `compose.yaml` file:**
    ```yaml
    services:
      mousesearch:
        image: sevenlayercookie/mousesearch
        container_name: mousesearch
        ports:
          - "5000:5000" # You can change the host port (left side) if 5000 is in use
        environment:
          - FLASK_SECRET_KEY=${FLASK_SECRET_KEY}
          - MAM_ID=${MAM_ID}
          - MAM_UID=${MAM_UID}
          - QB_URL=${QB_URL}
          - QB_USERNAME=${QB_USERNAME}
          - QB_PASSWORD=${QB_PASSWORD}
          - QB_CATEGORY=${QB_CATEGORY}
          - CF_ACCESS_CLIENT_ID=${CF_ACCESS_CLIENT_ID}
          - CF_ACCESS_CLIENT_SECRET=${CF_ACCESS_CLIENT_SECRET}
        volumes:
          - ./data:/app/data
    ```

2.  **Create a `.env` file** in the same directory and add your configuration details.
    ```env
    # A long, random string for security
    FLASK_SECRET_KEY=your_super_secret_key_here
    
    # MyAnonamouse Credentials
    MAM_ID=your_mam_id_cookie
    MAM_UID=your_mam_uid_cookie
    
    # qBittorrent Credentials
    QB_URL=http://your-qbittorrent-ip:8080
    QB_USERNAME=your_qb_username
    QB_PASSWORD=your_qb_password
    QB_CATEGORY=mousesearch
    
    # Optional Cloudflare Access Credentials
    # CF_ACCESS_CLIENT_ID=
    # CF_ACCESS_CLIENT_SECRET=
    ```

3.  **Start the container:**
    ```bash
    docker compose up -d
    ```

The application will be accessible at [http://localhost:5000](http://localhost:5000).

#### Bare Metal (Gunicorn for Production)

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/sevenlayercookie/mousesearch.git](https://github.com/sevenlayercookie/mousesearch.git)
    cd mousesearch
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    pip install gunicorn
    ```

3.  **Run with Gunicorn:**
    ```bash
    gunicorn --bind 0.0.0.0:5000 app:app
    ```

#### Bare Metal (Flask for Development)

1.  **Clone the repository:**
    ```bash
    git clone [https://github.com/sevenlayercookie/mousesearch.git](https://github.com/sevenlayercookie/mousesearch.git)
    cd mousesearch
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the Flask development server:**
    ```bash
    python app.py
    ```

## Configuration

For Docker deployments, it is recommended to use the `.env` file as described above. For bare metal, you can still use a `.env` file, or you can manage all settings through the web interface. Click the settings icon in the top right corner to open the configuration panel.

You will need to provide the following information:

* **qBittorrent:**
    * URL
    * Username
    * Password
    * Default Category (optional)
* **MyAnonamouse:**
    * MAM ID (your `mam_id` cookie)

## Usage

1.  Navigate to the application in your web browser.
2.  If you haven't used a `.env` file, open the settings panel and configure your qBittorrent and MyAnonamouse credentials.
3.  Use the main search form to find content.
4.  From the results list, click the download icon to send a torrent to qBittorrent.

## Project Structure

* `app.py`: The main Flask application file containing all routes and logic.
* `Dockerfile`: Defines the Docker container for the application.
* `requirements.txt`: A list of Python dependencies for the project.
* `templates/`: Contains the HTML templates for the web interface.
* `static/`: Contains static assets like CSS and JavaScript.
