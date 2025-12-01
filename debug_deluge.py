import asyncio
import httpx
import json

# CONFIGURATION
URL = "http://localhost:8112"
PASSWORD = "deluge"  # Default password. Change if yours is different.

async def debug_deluge():
    base_url = f"{URL.rstrip('/')}/json"
    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }
    cookies = {}
    req_id = 1

    async with httpx.AsyncClient(timeout=10.0) as client:
        print(f"--- 1. Attempting to reach {URL} ---")
        try:
            # Payload for auth.login
            payload = {"method": "auth.login", "params": [PASSWORD], "id": req_id}
            
            resp = await client.post(base_url, json=payload, headers=headers)
            print(f"Status Code: {resp.status_code}")
            
            # Save cookies (CRITICAL for Deluge)
            if resp.cookies:
                cookies = dict(resp.cookies)
                print("Cookies received/saved.")
            else:
                print("WARNING: No cookies received.")

            data = resp.json()
            print(f"Login Response: {data}")
            
            if not data.get('result'):
                print("\n❌ FAILURE: Login returned False. Check your PASSWORD.")
                return

            req_id += 1

            # Check if WebUI is connected to Daemon
            print("\n--- 2. Checking Daemon Connection ---")
            payload = {"method": "web.connected", "params": [], "id": req_id}
            resp = await client.post(base_url, json=payload, headers=headers, cookies=cookies)
            is_connected = resp.json().get('result')
            print(f"Web Connected to Daemon: {is_connected}")

            if not is_connected:
                print("\n⚠️  WebUI is NOT connected to the Daemon.")
                print("Attempting to list hosts...")
                req_id += 1
                payload = {"method": "web.get_hosts", "params": [], "id": req_id}
                resp = await client.post(base_url, json=payload, headers=headers, cookies=cookies)
                hosts = resp.json().get('result', [])
                print(f"Hosts found: {hosts}")
                
                if hosts:
                    host_id = hosts[0][0]
                    print(f"Attempting to connect to Host ID: {host_id}")
                    req_id += 1
                    payload = {"method": "web.connect", "params": [host_id], "id": req_id}
                    resp = await client.post(base_url, json=payload, headers=headers, cookies=cookies)
                    print(f"Connect Result: {resp.json()}")
                else:
                    print("❌ FAILURE: No Daemons found in WebUI config.")
            
            # Final Status Check
            req_id += 1
            payload = {"method": "daemon.info", "params": [], "id": req_id}
            resp = await client.post(base_url, json=payload, headers=headers, cookies=cookies)
            print(f"\nFinal Daemon Info: {resp.json().get('result')}")
            print("\n✅ SUCCESS: Deluge JSON-RPC is working!")

        except Exception as e:
            print(f"\n❌ EXCEPTION: {e}")

if __name__ == "__main__":
    asyncio.run(debug_deluge())