# Batch Polling Refactor

## Summary

Refactored the torrent status polling system from individual per-torrent intervals to a single batch polling interval that efficiently checks multiple torrents in one HTTP request.

## Changes Made

### Backend (`app.py`)

#### New Endpoint: `/qb/info/batch`
- **Method:** POST
- **Accepts:** `{"hashes": ["hash1", "hash2", ...]}`
- **Returns:** `{"torrents": {"hash1": {...}, "hash2": {...}}}`
- Uses qBittorrent's pipe-separated hash format (`hash1|hash2|...`) for efficient querying
- Returns torrents indexed by hash for easy client-side lookup

### Frontend (`static/js/main.js`)

#### New Global State
```javascript
const activeHashes = new Set();           // Active torrents being polled
const hashToElementMap = new Map();       // Maps hash -> DOM element
let batchPollingInterval = null;          // Single polling interval
```

#### New Functions

1. **`performBatchPoll()`**
   - Performs a single batch poll of all active torrents
   - Fetches status for all active hashes in one request
   - Updates UI for each torrent based on response
   - Can be called independently or via interval

2. **`startBatchPolling()`**
   - Starts a single 2-second interval if not already running
   - **Makes an immediate poll before starting the interval** (eliminates 0-2 second delay)
   - Then continues polling every 2 seconds
   - Auto-stops when no active hashes remain

3. **`stopBatchPolling()`**
   - Clears the batch polling interval

4. **`addHashToPolling(hash, resultItem)`**
   - Adds a hash to the active polling set
   - Stores the DOM element reference
   - Starts batch polling if needed (which makes an immediate poll)

5. **`removeHashFromPolling(hash)`**
   - Removes hash from active set
   - Cleans up element reference
   - Stops polling if no hashes remain

6. **`updateTorrentUI(hash, data, resultItem)`**
   - Updates the status UI for a specific torrent
   - Handles state mapping and progress display
   - Removes from polling on terminal states

#### Modified Functions

1. **`pollTorrentStatus(hash, resultItem)`**
   - Simplified to just call `addHashToPolling()`
   - No longer creates individual intervals

2. **Search form submit handler**
   - Now clears batch polling system instead of individual intervals
   - Calls `stopBatchPolling()`, `activeHashes.clear()`, `hashToElementMap.clear()`

## Performance Benefits

### Before
- **N torrents = N HTTP requests** every 2 seconds
- **N setInterval timers** running simultaneously
- Higher CPU usage and network overhead

### After
- **N torrents = 1 HTTP request** every 2 seconds
- **1 setInterval timer** for all torrents
- Dramatically reduced overhead

### Example Impact
- **10 active torrents:**
  - Before: 10 requests/2s = 300 requests/minute
  - After: 1 request/2s = 30 requests/minute
  - **90% reduction in HTTP requests**

## Backward Compatibility

The old `pollingIntervals` and `torrentHashMap` objects are retained but no longer used. They can be removed in a future cleanup if desired.

## Terminal States

Torrents are automatically removed from polling when they reach terminal states:
- `error`, `missingFiles` (errors)
- `uploading`, `pausedUP`, `stalledUP`, `forcedUP` (seeding/paused upload)
- `pausedDL` (paused download)

## Testing Checklist

- [x] Backend endpoint compiles without errors
- [x] Frontend JavaScript has no syntax errors
- [ ] Search returns results correctly
- [ ] Adding torrent to qBittorrent initiates polling
- [ ] Multiple torrents can be monitored simultaneously
- [ ] Status badges update correctly
- [ ] Polling stops on terminal states
- [ ] Polling auto-stops when all torrents complete
- [ ] New search clears previous polling correctly
- [ ] Browser console shows reduced HTTP request frequency

## Future Enhancements

1. **Adjustable polling interval:** Could make the 2-second interval configurable
2. **Error retry logic:** Could implement exponential backoff on failed batch requests
3. **Cleanup legacy code:** Remove unused `pollingIntervals` object
4. **Visual indicator:** Show "Polling N torrents" somewhere in UI
