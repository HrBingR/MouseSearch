# Quart Migration Summary

## Migration Completed ✅

MouseSearch has been successfully migrated from Flask to Quart with full async/await support.

## Key Changes

### 1. Dependencies (`requirements.txt`)
- **Removed:** `Flask`, `requests`, `Flask-APScheduler`
- **Added:** `Quart`, `httpx`, `quart-schema`, `APScheduler` (standalone)

### 2. Core Framework Changes
- `Flask` → `Quart`
- `requests` → `httpx` (async HTTP client)
- `Flask-APScheduler` → `APScheduler` with `AsyncIOScheduler`

### 3. Route Handler Changes
All route handlers are now async:
```python
# Before (Flask)
@app.route('/mam/search')
def mam_search():
    data = request.get_json()
    return render_template("results.html", data=data)

# After (Quart)
@app.route('/mam/search')
async def mam_search():
    data = await request.get_json()
    return await render_template("results.html", data=data)
```

### 4. HTTP Client Changes
All HTTP requests are now async:
```python
# Before (Flask + requests)
response = requests.get(url, cookies=cookies, timeout=10)

# After (Quart + httpx)
async with httpx.AsyncClient() as client:
    response = await client.get(url, cookies=cookies, timeout=10)
```

### 5. Scheduler Changes
APScheduler now uses AsyncIOScheduler:
```python
# Before
from flask_apscheduler import APScheduler
scheduler = APScheduler()
scheduler.init_app(app)

# After
from apscheduler.schedulers.asyncio import AsyncIOScheduler
scheduler = AsyncIOScheduler()
scheduler.start()
```

### 6. Deployment Changes
- **Before:** Gunicorn (WSGI server)
- **After:** Hypercorn (ASGI server)

Dockerfile CMD updated:
```dockerfile
# Before
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "app:app"]

# After
CMD ["hypercorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--worker-class", "asyncio", "app:app"]
```

## Awaitable Operations

The following operations now require `await`:

### Request Operations
- `await request.get_json()`
- `await request.form`
- `await request.data`
- `await request.files`

### Response Operations
- `await render_template(...)`
- `await render_template_string(...)`
- `await make_response(...)`
- `await response.get_json()` (when reading JSON from a Response object)

### Helper Functions
All helper functions that make HTTP requests are now async:
- `await login_mam()`
- `await login_qbittorrent()`
- `await calculate_torrent_hash_from_url(url)`
- `await force_update_ip()`
- `await check_and_update_ip()`
- `await _perform_organization(hash_val)`

## Session Management

Session cookie handling updated for httpx:
```python
# Before (requests.Session)
session_obj = requests.Session()
session_obj.cookies.update(session['qb_session'])
response = session_obj.get(url)

# After (httpx.AsyncClient with cookies)
async with httpx.AsyncClient(cookies=session['qb_session']) as client:
    response = await client.get(url)
```

## Running the Application

### Development (Local)
```bash
# Install dependencies
pip install -r requirements.txt

# Run with Quart development server
python app.py --host 0.0.0.0 --port 5000
```

### Production (Docker)
```bash
# Build the container
./buildImage.sh -v v0.2.0 -u sevenlayercookie

# Run with docker compose
docker compose up -d
```

### Production (Bare Metal)
```bash
# Install hypercorn
pip install hypercorn

# Run with hypercorn
hypercorn --bind 0.0.0.0:5000 --workers 1 --worker-class asyncio app:app
```

## Benefits of Async Migration

1. **Better Concurrency:** Multiple requests can be handled concurrently without blocking
2. **Improved Performance:** I/O-bound operations (API calls to MAM/qBittorrent) don't block other requests
3. **Scalability:** Better resource utilization with async I/O
4. **Modern Architecture:** Quart supports ASGI (Asynchronous Server Gateway Interface)
5. **Streaming Support:** Better handling of streaming responses (like proxy_thumbnail)

## Backwards Compatibility

- All API endpoints remain unchanged
- Frontend JavaScript requires no modifications
- Environment variables and configuration remain the same
- Docker volume mounts unchanged

## Testing Checklist

- [ ] Search returns results with thumbnails
- [ ] "Add to qBittorrent" creates download
- [ ] Status badge polling works correctly
- [ ] Settings save and persist after restart
- [ ] AUTO_ORGANIZE hardlinks files after download completion
- [ ] Scheduled jobs run correctly (IP update, organization safety net)
- [ ] Thumbnail proxy caching works
- [ ] MAM API authentication maintained across requests
- [ ] qBittorrent session doesn't expire unexpectedly

## Rollback Plan

If issues are encountered, the original Flask version is preserved:
```bash
# Restore Flask version
cp app_flask_backup.py app.py

# Update requirements.txt manually or from git
git checkout requirements.txt Dockerfile
```

## Performance Expectations

- **Concurrent Requests:** Should handle 10+ simultaneous searches without blocking
- **API Response Time:** Similar or slightly faster due to async I/O
- **Memory Usage:** Slightly lower (no thread pool overhead)
- **Scheduler Jobs:** Run independently without blocking web requests

## Known Limitations

1. **Session Management:** Flask sessions work in Quart, but consider migrating to async session storage for high-traffic scenarios
2. **File I/O:** File operations (metadata.json, config.json) are still synchronous - could be optimized with `aiofiles` if needed
3. **APScheduler:** Jobs run in separate threads - ensure proper async context management

## Next Steps (Optional Enhancements)

1. Replace synchronous file I/O with `aiofiles`
2. Add connection pooling to httpx clients
3. Implement async session storage (Redis/async SQLite)
4. Add request timeouts and retry logic
5. Implement connection limits to prevent overwhelming external APIs
