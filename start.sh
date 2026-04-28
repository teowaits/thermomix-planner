#!/bin/zsh

# Thermomix Planner — start backend + frontend
# Usage: ./start.sh        (starts both, opens browser)
#        ./start.sh stop   (kills both processes)

PROJECT="$HOME/Documents/Claude/thermomix-planner"
PIDFILE="$PROJECT/.pids"

# ── stop ──────────────────────────────────────────────────────────────────────
if [[ "$1" == "stop" ]]; then
    if [[ -f "$PIDFILE" ]]; then
        while read -r pid; do
            kill "$pid" 2>/dev/null && echo "Stopped process $pid"
        done < "$PIDFILE"
        rm "$PIDFILE"
        echo "Thermomix Planner stopped."
    else
        echo "No running instance found."
    fi
    exit 0
fi

# ── check already running ─────────────────────────────────────────────────────
if [[ -f "$PIDFILE" ]]; then
    echo "Thermomix Planner appears to already be running."
    echo "Run './start.sh stop' first, then try again."
    exit 1
fi

# ── start backend ─────────────────────────────────────────────────────────────
echo "Starting backend..."
cd "$PROJECT"
source .venv/bin/activate

uvicorn backend.main:app --port 8000 > "$PROJECT/backend.log" 2>&1 &
BACKEND_PID=$!

# wait for backend to be ready (up to 15s)
echo -n "Waiting for backend"
for i in {1..15}; do
    sleep 1
    if curl -s http://localhost:8000/api/cache/status > /dev/null 2>&1; then
        echo " ready."
        break
    fi
    echo -n "."
    if [[ $i -eq 15 ]]; then
        echo ""
        echo "ERROR: Backend did not start in time. Check backend.log for details."
        kill "$BACKEND_PID" 2>/dev/null
        exit 1
    fi
done

# ── start frontend ────────────────────────────────────────────────────────────
echo "Starting frontend..."
cd "$PROJECT/frontend"
npm run dev > "$PROJECT/frontend.log" 2>&1 &
FRONTEND_PID=$!

# save PIDs for stop command
echo "$BACKEND_PID" > "$PIDFILE"
echo "$FRONTEND_PID" >> "$PIDFILE"

# wait a moment then open browser
sleep 2
open http://localhost:5173

echo ""
echo "Thermomix Planner is running."
echo "  App:     http://localhost:5173"
echo "  Backend: http://localhost:8000"
echo ""
echo "Logs: tail -f $PROJECT/backend.log"
echo "      tail -f $PROJECT/frontend.log"
echo ""
echo "To stop: ./start.sh stop"
