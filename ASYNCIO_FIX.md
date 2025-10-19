# AsyncIO Event Loop Fix

## Problem

When running the Quart app with the debugger or directly, the app would crash with:

```
RuntimeError: no running event loop
```

This happened at line 35 where `scheduler.start()` was called during module import.

## Root Cause

The `AsyncIOScheduler` requires an active asyncio event loop to start. When the module is imported, there's no event loop running yet. The event loop is only created when Quart starts serving requests.

## Solution

Use Quart's lifecycle hooks to start the scheduler **after** the event loop is running:

### Before (Broken)
```python
# Initialize AsyncIO scheduler for Quart
scheduler = AsyncIOScheduler()
scheduler.start()  # ❌ No event loop yet!

atexit.register(lambda: scheduler.shutdown())
```

### After (Fixed)
```python
# Initialize AsyncIO scheduler for Quart (but don't start it yet)
scheduler = AsyncIOScheduler()

@app.before_serving
async def startup():
    """Start the scheduler and load config when the app starts serving requests."""
    # Load config and fetch MAM_UID if needed
    await load_new_app_config()
    
    # Start the scheduler
    if not scheduler.running:
        scheduler.start()
        app.logger.info("AsyncIOScheduler started")

@app.after_serving
async def shutdown():
    """Shutdown the scheduler when the app stops serving."""
    if scheduler.running:
        scheduler.shutdown()
        app.logger.info("AsyncIOScheduler shutdown")
```

## Additional Changes

### Config Loading

Also moved async config loading to the `@app.before_serving` hook:

**Before:**
```python
# Load config at startup (we need to run this with async context)
import asyncio
asyncio.run(load_new_app_config())  # ❌ Can cause issues
```

**After:**
```python
# Load initial config synchronously (without MAM_UID fetch)
initial_config = load_config()
app.secret_key = initial_config["FLASK_SECRET_KEY"]
app.config.update(initial_config)
# ... etc

# Then in the startup hook:
@app.before_serving
async def startup():
    await load_new_app_config()  # ✅ Fetch MAM_UID asynchronously
    # ... scheduler start
```

## Benefits

1. **Proper Lifecycle Management**: Scheduler starts/stops with the app
2. **Event Loop Safety**: No asyncio operations before event loop exists
3. **Clean Shutdown**: Scheduler properly cleaned up when app stops
4. **Debugger Compatible**: Works with VS Code debugger and direct execution

## Testing

The app now works correctly with:
- `python app.py --host 0.0.0.0 --port 5000` ✅
- VS Code debugger (F5) ✅
- `hypercorn app:app --bind 0.0.0.0:5000` ✅
- Docker container ✅

## References

- [Quart Lifecycle Documentation](https://quart.palletsprojects.com/en/latest/how_to_guides/startup_shutdown.html)
- [APScheduler AsyncIOScheduler](https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/asyncio.html)
