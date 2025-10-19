# Thumbnail Proxy Streaming Fix

## Problem

Thumbnails were failing to load with the error:
```
httpx.StreamClosed: Attempted to read or stream content, but the stream has been closed.
```

## Root Cause

In the async httpx client, when using `client.stream()` with a context manager, the stream is automatically closed when you exit the context. The generator function was trying to iterate over `response.aiter_bytes()` **after** the context manager had already closed the connection.

### The Broken Code
```python
async with httpx.AsyncClient() as client:
    async with client.stream('GET', url, ...) as response:
        # Define a generator
        async def generate():
            async for chunk in response.aiter_bytes(chunk_size=1024):
                yield chunk
        
        # Return response with generator
        return Response(generate(), ...)
# ❌ Context exits here, stream closes
# When Quart tries to iterate the generator later, stream is already closed!
```

## Solution

Instead of streaming, we fetch the entire thumbnail content and return it at once. Thumbnails are typically small images (< 100KB), so loading them into memory is not a problem.

### The Fixed Code
```python
async with httpx.AsyncClient() as client:
    response = await client.get(url, cookies=mam_session_cookies, timeout=10)
    response.raise_for_status()
    
    cache_headers = {
        "Cache-Control": "public, max-age=31536000, immutable",
        "Content-Type": response.headers.get("Content-Type", "image/jpeg")
    }
    
    return Response(
        response.content,  # ✅ Content is already loaded in memory
        headers=cache_headers
    )
```

## Benefits of This Approach

1. **Simpler Code**: No need for complex streaming logic
2. **Better Performance**: For small files, streaming overhead is unnecessary
3. **Reliable**: No context manager lifecycle issues
4. **Cached**: Browser caches the full image for 1 year

## When to Use Streaming

Streaming is still valuable for:
- Large files (> 10MB)
- Video/audio content
- Files where you want to show progress
- Server-sent events (SSE)

For thumbnails and small images, fetching the full content is the better choice.

## Alternative Solution (If Streaming is Required)

If you absolutely need streaming, you must keep the stream alive:

```python
async def stream_thumbnail(url):
    async with httpx.AsyncClient() as client:
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=1024):
                yield chunk

@app.route("/proxy_thumbnail")
async def proxy_thumbnail():
    url = request.args.get("url")
    if not url:
        return "No URL provided", 400
    
    return Response(
        stream_thumbnail(url),
        content_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=31536000, immutable"}
    )
```

But for this use case, the simpler non-streaming approach is better.

## Testing

Thumbnails now load correctly without errors! ✅
