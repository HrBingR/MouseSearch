# Batch Organization Feature

## Overview

The `/organize` endpoint now supports two modes of operation:
1. **Single torrent organization** - when a hash is provided
2. **Batch organization** - when no hash is provided (iterates through all unorganized torrents)

## API Endpoints

### 1. Organize Specific Torrent
```
POST /organize/<hash_val>
```

**Use Case:** Called by qBittorrent webhook when a single torrent completes.

**Example:**
```bash
curl -X POST http://localhost:5000/organize/abc123def456...
```

**Response:**
```json
{
  "status": "success",
  "message": "SUCCESS: 'Book Title' (3 files linked from '...' to '...')."
}
```

### 2. Batch Organize All Unorganized Torrents
```
POST /organize
```

**Use Case:** Manually trigger organization of all unorganized torrents in metadata.json.

**Example:**
```bash
curl -X POST http://localhost:5000/organize
```

**Response:**
```json
{
  "status": "success",
  "message": "Batch organization complete: 5 succeeded, 2 failed, 1 skipped (out of 8 total)",
  "results": {
    "total": 8,
    "succeeded": 5,
    "failed": 2,
    "skipped": 1,
    "details": [
      {
        "hash": "abc123...",
        "success": true,
        "message": "SUCCESS: 'Book Title' (3 files linked...)"
      },
      {
        "hash": "def456...",
        "success": false,
        "message": "Source path does not exist: /path/to/missing/torrent"
      }
    ]
  }
}
```

## Handling Missing Source Files

The batch organization intelligently handles cases where metadata exists but source files are gone:

### Error Handling
- **Source files missing**: Logs as WARNING, marks as failed, continues processing
- **Already organized**: Logs as INFO, counts as skipped
- **Other errors**: Logs as ERROR, counts as failed

### Log Output Example
```
[2025-10-19 18:00:00] [INFO] Received batch organization request (no hash provided)
[2025-10-19 18:00:00] [INFO] Found 10 unorganized torrent(s). Processing...
[2025-10-19 18:00:01] [INFO] Batch organize - Success: abc123... - SUCCESS: 'Book 1' (5 files linked)
[2025-10-19 18:00:01] [WARNING] Batch organize - Source missing: def456... - Source path does not exist: /audiobooks/Book2
[2025-10-19 18:00:02] [INFO] Batch organize - Skipped: ghi789... - Skipping: Torrent already marked as organized
[2025-10-19 18:00:10] [INFO] Batch organization complete: 7 succeeded, 2 failed, 1 skipped (out of 10 total)
```

## Use Cases

### 1. Initial Setup
After importing existing metadata, organize all torrents at once:
```bash
curl -X POST http://localhost:5000/organize
```

### 2. Retry Failed Organizations
If some torrents failed to organize (e.g., files weren't ready), re-run batch organization:
```bash
curl -X POST http://localhost:5000/organize
```

Only unorganized torrents will be processed (already organized ones are skipped).

### 3. Clean Up After Moving Files
If you moved source files and some organization attempts failed:
```bash
curl -X POST http://localhost:5000/organize
```

### 4. Webhook Integration
qBittorrent automatically calls the single-hash endpoint:
```
POST http://localhost:5000/organize/abc123def456...
```

## Result Categories

### Succeeded
- Files were successfully hardlinked
- Torrent marked as `organized: true` in metadata

### Failed
- **Source missing**: Torrent files no longer exist at expected path
- **No audio files**: No compatible audio files found in torrent
- **API errors**: qBittorrent connection issues
- **File system errors**: Permission issues, disk full, etc.

### Skipped
- Already marked as `organized: true`
- Exceeded retry limit (3 attempts)

## Safety Features

1. **Idempotent**: Safe to run multiple times - organized torrents are skipped
2. **Atomic**: Each torrent processed independently - one failure doesn't stop others
3. **Retry Limit**: Torrents that fail 3 times are skipped automatically
4. **Detailed Logging**: Every operation logged with hash and result
5. **Non-destructive**: Only creates hardlinks, never moves or deletes files

## Integration with Scheduled Job

The hourly safety net job (`check_for_unorganized_torrents`) does the same thing automatically, but this endpoint allows manual triggering:

```python
# This happens automatically every hour:
scheduler.add_job(check_for_unorganized_torrents, 'interval', hours=1)

# But you can also trigger it manually:
curl -X POST http://localhost:5000/organize
```

## Example Workflow

1. Download 20 audiobooks via qBittorrent
2. Some complete while app was down → webhook missed
3. Restart app and manually trigger batch organization:
   ```bash
   curl -X POST http://localhost:5000/organize
   ```
4. Check logs to see which ones succeeded:
   ```bash
   grep "Batch organize" logs.txt
   ```

## Error Recovery

If batch organization shows "Source path does not exist":
1. Check if files were moved/deleted
2. Update `QB_PATH` in config if location changed
3. Re-run batch organization after fixing paths

If many torrents fail with same error:
1. Check qBittorrent connection: `curl http://localhost:5000/qb/status`
2. Verify `QB_PATH` matches qBittorrent's download location
3. Check file permissions on source and destination paths
