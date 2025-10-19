# Edge Case Handling for Auto-Organization

## Overview
This document describes the comprehensive edge case handling implemented for the auto-organization feature to ensure robust production operation.

## Edge Cases Addressed

### 1. Hash Calculation Failure
**Scenario:** Torrent is added but hash cannot be calculated (network error, invalid torrent file, etc.)

**Impact:** Without metadata, the webhook `/organize/<hash>` cannot find author/title information.

**Solution:**
- In `qb_add_torrent()`: Set `auto_organize_warning` variable when hash calculation fails
- Return warning message to frontend: `"Unable to calculate torrent hash - auto-organization will not work for this torrent."`
- User is immediately informed that this specific torrent won't auto-organize
- Torrent still downloads normally, just won't be organized

**Code Location:** Lines ~340-395 in `app.py`

### 2. Missing Source Files (Timing Issue)
**Scenario:** Webhook fires but qBittorrent hasn't finished moving files, or files were manually deleted.

**Impact:** `content_path.exists()` returns False, organization fails.

**Current Behavior (Preserved):**
- Return error without incrementing retry counter
- Safety net job will retry up to 3 times per torrent
- This handles legitimate timing issues where webhook fires too early

**Rationale:** If files are missing due to timing, retry will succeed. If permanently missing, we don't want to mark as "failed" after 3 retries since user might manually re-add later.

**Code Location:** Lines ~710-713 in `app.py`

### 3. Destination Write Errors
**Scenario:** 
- No permission to create directory under `ORGANIZED_PATH`
- Filesystem full
- Directory structure locked by another process

**Previous Behavior:** Unhandled OSError/PermissionError would crash organization attempt with no logging.

**New Behavior:**
- `try/except` around `dest_path.mkdir()` catches OSError/PermissionError
- Return error message: `"Cannot create destination directory '{dest_path}': {e}"`
- Logged at ERROR level for admin attention
- Does NOT increment retry counter (permanent failure, retries won't help)

**Code Location:** Lines ~718-721 in `app.py`

**Additional Handling:**
- `try/except` around individual `os.link()` calls
- Logs failed links but continues processing other files
- Allows partial organization if some files fail

**Code Location:** Lines ~733-738 in `app.py`

### 4. Files Already Exist (Idempotent Re-runs)
**Scenario:** 
- Organization ran previously
- User manually copies files
- Safety net job re-runs on already-organized torrent

**Previous Behavior:** `files_linked == 0` treated as failure, incremented retry counter.

**New Behavior:**
- Track `files_already_exist` separately from `files_linked`
- Calculate `total_audio_files = files_linked + files_already_exist`
- Mark as **success** if `total_audio_files > 0`
- Three success message variations:
  1. New files only: `"{files_linked} files linked to '{dest_path}'"`
  2. Mixed: `"{files_linked} new files linked, {files_already_exist} already existed (total: {total_audio_files})"`
  3. All existing: `"All {files_already_exist} files already organized in '{dest_path}'"`

**Impact:** Idempotent behavior - re-running organization on same torrent is safe and marks as success.

**Code Location:** Lines ~723-757 in `app.py`

## Success Conditions

Organization is marked **successful** (`organized=True`) when:
1. At least one file was newly linked (`files_linked > 0`), OR
2. At least one file already existed (`files_already_exist > 0`)

This means if audio files are present in destination (whether we just linked them or they were already there), it's a success.

## Failure Conditions

Organization **fails** (does not set `organized=True`) when:
1. Source path doesn't exist (timing issue - retry without increment)
2. Cannot create destination directory (permission error - logged, no retry)
3. No audio files found at all (`total_audio_files == 0`)
4. API errors communicating with qBittorrent

## Retry Logic

**Increments retry counter:**
- Only when NO audio files found (`total_audio_files == 0`)
- Max 3 attempts via safety net job

**Does NOT increment retry counter:**
- Source path missing (timing issue)
- Destination creation failure (permanent error)
- Files already organized (success case)

## Error Handling

### Logged Errors:
- `ERROR`: Individual file link failures (permission issues)
- `ERROR`: Cannot create destination directory
- `ERROR`: API failures communicating with qBittorrent
- `WARNING`: Hash calculation failure (user warned in response)

### Caught Exceptions:
- `OSError`, `PermissionError`: Directory creation and file linking
- `RequestError`: qBittorrent API communication
- `json.JSONDecodeError`: Invalid API responses
- `Exception`: Catch-all for unexpected errors (logged with traceback)

## User-Facing Changes

### Frontend Warning
When hash calculation fails during "Add to qBittorrent":
```json
{
  "message": "Torrent added successfully",
  "warning": "Unable to calculate torrent hash - auto-organization will not work for this torrent."
}
```

**Implementation Note:** Frontend should display warnings alongside success messages (yellow alert vs green).

### Log Messages
Administrators monitoring logs will see clear categorization:
- `[ORGANIZE] SUCCESS`: Files linked or already organized
- `[ORGANIZE] Linked`: Individual file operations
- `[ORGANIZE] Skipped (already exists)`: Idempotent behavior
- `[ORGANIZE] Failed to link`: Permission errors on specific files

## Testing Edge Cases

### Manual Test Scenarios:

1. **Hash Failure:**
   ```bash
   # Add invalid torrent URL via API
   curl -X POST http://localhost:5000/qb/add \
     -H "Content-Type: application/json" \
     -d '{"torrent_url": "invalid", "author": "Test", "title": "Test"}'
   ```
   Expected: Success response with warning message

2. **Permission Error:**
   ```bash
   # Make organized directory read-only
   chmod 555 /app/data/organized
   # Trigger organization webhook
   curl -X POST http://localhost:5000/organize/TESTHASH
   ```
   Expected: Error logged, organization fails gracefully

3. **Idempotent Re-run:**
   ```bash
   # Organize same torrent twice
   curl -X POST http://localhost:5000/organize/HASH1
   curl -X POST http://localhost:5000/organize/HASH1
   ```
   Expected: Both return success, second shows "already existed"

4. **Missing Source:**
   ```bash
   # Delete source files after webhook
   rm -rf /audiobooks/downloads/test-torrent
   curl -X POST http://localhost:5000/organize/HASH2
   ```
   Expected: Fails without retry increment, safety net will retry

## Migration Notes

**Breaking Changes:** None - this is purely additive error handling.

**Backward Compatibility:**
- Existing `metadata.json` entries work unchanged
- Previously organized torrents won't be re-organized (already marked `organized=True`)
- Retry counters from old code still respected

**Deployment:**
- No database migrations needed
- No configuration changes required
- Can deploy without downtime (stateless changes)

## Related Files

- `app.py`: Lines 340-395 (qb_add_torrent), Lines 664-757 (_perform_organization)
- `data/metadata.json`: Stores organization state
- `data/organized/`: Destination for hardlinked files

## Future Enhancements

Potential improvements not included in this fix:
1. **Retry backoff**: Exponential delay between retry attempts
2. **Manual retry button**: UI to force re-organization of failed torrents
3. **Detailed status page**: Show all torrents with organization status
4. **Email notifications**: Alert on permanent failures (permission errors)
5. **Disk space checks**: Warn if destination filesystem near capacity
