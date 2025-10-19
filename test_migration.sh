#!/bin/bash
# Test script for Quart migration

echo "🧪 Testing Quart Migration..."
echo ""

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo "📥 Installing dependencies..."
pip install -q -r requirements.txt

# Check for syntax errors
echo "🔍 Checking for syntax errors..."
python3 -m py_compile app.py
if [ $? -eq 0 ]; then
    echo "✅ No syntax errors found"
else
    echo "❌ Syntax errors detected"
    exit 1
fi

# Test imports
echo "🔍 Testing imports..."
python3 << EOF
try:
    from quart import Quart
    import httpx
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    print("✅ All imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    exit(1)
EOF

# Check if hypercorn is installed
echo "🔍 Checking for hypercorn..."
if python3 -c "import hypercorn" 2>/dev/null; then
    echo "✅ Hypercorn is installed"
else
    echo "⚠️  Installing hypercorn..."
    pip install -q hypercorn
fi

# Start the app in the background
echo "🚀 Starting Quart app..."
python3 app.py --host 127.0.0.1 --port 5555 &
APP_PID=$!
sleep 3

# Test if the app is running
echo "🔍 Testing app endpoints..."

# Test root endpoint
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5555/)
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Root endpoint (/) working - HTTP $HTTP_CODE"
else
    echo "❌ Root endpoint failed - HTTP $HTTP_CODE"
fi

# Test MAM status endpoint
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5555/mam/status)
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ MAM status endpoint working - HTTP $HTTP_CODE"
else
    echo "❌ MAM status endpoint failed - HTTP $HTTP_CODE"
fi

# Test qBittorrent status endpoint
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:5555/qb/status)
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "503" ]; then
    echo "✅ qBittorrent status endpoint working - HTTP $HTTP_CODE"
else
    echo "❌ qBittorrent status endpoint failed - HTTP $HTTP_CODE"
fi

# Cleanup
echo "🧹 Cleaning up..."
kill $APP_PID 2>/dev/null
wait $APP_PID 2>/dev/null

echo ""
echo "✨ Migration test complete!"
echo ""
echo "To run the app manually:"
echo "  python app.py --host 0.0.0.0 --port 5000"
echo ""
echo "To run with hypercorn (production):"
echo "  hypercorn --bind 0.0.0.0:5000 --workers 1 --worker-class asyncio app:app"
