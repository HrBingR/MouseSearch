import asyncio
import httpx
import json

# --- UPDATE THESE TO MATCH YOUR CONFIG ---
URL = "http://localhost:9091/transmission/rpc"  # Ensure /transmission/rpc is at the end
USERNAME = "" 
PASSWORD = ""
# -----------------------------------------

async def debug_connection():
    headers = {}
    auth = (USERNAME, PASSWORD) if USERNAME or PASSWORD else None
    
    payload = {
        "jsonrpc": "2.0",
        "method": "session-get",
        "fields": ["version"],
        "id": 1
    }

    print(f"--- Attempting connection to {URL} ---")

    async with httpx.AsyncClient(auth=auth, timeout=10.0) as client:
        try:
            # 1. First Attempt
            print("1. Sending initial request...")
            response = await client.post(URL, json=payload, headers=headers)
            print(f"   Status Code: {response.status_code}")
            
            # 2. CSRF Handling
            if response.status_code == 409:
                print("   Received 409 Conflict (Expected). Fetching Session ID...")
                session_id = response.headers.get('X-Transmission-Session-Id')
                
                if session_id:
                    print(f"   Got Session ID: {session_id}")
                    headers['X-Transmission-Session-Id'] = session_id
                    
                    # 3. Retry with Token
                    print("2. Retrying with Session ID...")
                    response = await client.post(URL, json=payload, headers=headers)
                    print(f"   Status Code: {response.status_code}")
                else:
                    print("   ERROR: 409 received but no X-Transmission-Session-Id header found!")
                    print("   Headers:", response.headers)
                    return

            # 4. Check Final Result
            if response.status_code == 200:
                print("\nSUCCESS!")
                print("Response:", json.dumps(response.json(), indent=2))
            else:
                print(f"\nFAILURE. Status: {response.status_code}")
                print("Body:", response.text)

        except httpx.RequestError as e:
            print(f"\nNETWORK ERROR: {e}")
            print("Check if the URL is correct and the server is reachable from this script.")

if __name__ == "__main__":
    asyncio.run(debug_connection())