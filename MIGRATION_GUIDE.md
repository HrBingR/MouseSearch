# MouseSearch Migration Guide - Flask to Quart

## Overview

This document provides a summary of the migration from Flask (synchronous) to Quart (asynchronous).

## What Changed

### Core Framework
- **Flask** → **Quart** (ASGI-compatible async framework)
- **requests** → **httpx** (async HTTP client)
- **Gunicorn** → **Hypercorn** (ASGI server)

### All Route Handlers Are Now Async
Every route handler must be declared as `async def` and use `await` for:
- `await request.get_json()`
- `await request.form`
- `await render_template()`
- `await make_response()`

### HTTP Client Changed
```python
# Old (synchronous)
response = requests.get(url, cookies=cookies)

# New (asynchronous)
async with httpx.AsyncClient() as client:
    response = await client.get(url, cookies=cookies)
```

### Session Management
```python
# Old
session_obj = requests.Session()
session_obj.cookies.update(cookies)

# New
async with httpx.AsyncClient(cookies=cookies) as client:
    response = await client.get(url)
```

## Running the Application

### Development
```bash
python app.py --host 0.0.0.0 --port 5000
```

### Production (with Hypercorn)
```bash
hypercorn --bind 0.0.0.0:5000 --workers 1 --worker-class asyncio app:app
```

### Docker
```bash
docker compose up -d
```

## Testing

Run the included test script:
```bash
./test_migration.sh
```

## Rollback

If you need to rollback to Flask:
```bash
cp app_flask_backup.py app.py
git checkout requirements.txt Dockerfile
```

## Benefits

1. **Better Concurrency** - Multiple requests handled simultaneously
2. **Improved Performance** - Non-blocking I/O for API calls
3. **Modern Architecture** - ASGI support for WebSockets (future enhancement)
4. **Scalability** - Better resource utilization

## Important Notes

- All API endpoints remain unchanged
- Frontend JavaScript requires no modifications
- Configuration and environment variables unchanged
- Docker volumes unchanged

For detailed migration information, see [QUART_MIGRATION.md](./QUART_MIGRATION.md).
