
import time
import sqlite3
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from ping3 import ping
from datetime import datetime
import statistics


from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use explicit /tmp path for Vercel
DB_PATH = "/tmp/monitor.db" if os.environ.get("VERCEL") else "monitor.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Create table if not exists with host column
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS pings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      host TEXT,
                      timestamp REAL,
                      latency REAL,
                      status TEXT)''')
        
        # Check if host column exists (migration for existing users)
        c.execute("PRAGMA table_info(pings)")
        columns = [info[1] for info in c.fetchall()]
        if 'host' not in columns:
            print("Migrating DB: Adding host column")
            c.execute("ALTER TABLE pings ADD COLUMN host TEXT DEFAULT 'unknown'")
            
    except Exception as e:
        print(f"DB Init Error: {e}")
        
    conn.commit()
    conn.close()

# Initialize DB
init_db()

class PingTarget(BaseModel):
    host: str

@app.get("/api/health")
def health_check():
    return {"status": "ok"}


def tcp_ping(host, port=80, timeout=2):
    import socket
    start = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return (time.time() - start) * 1000 # to ms
    except:
        return None

@app.post("/api/ping")
def perform_ping(target: PingTarget):
    host = target.host
    latency = None
    method = "ICMP"
    
    try:
        # Try ICMP Ping first
        try:
            latency = ping(host, timeout=2, unit='ms')
        except OSError:
            # Permission denied or socket error
            latency = None
        
        # Fallback to TCP Ping
        if latency is None:
            method = "TCP"
            latency = tcp_ping(host)

        status = "up"
        if latency is None:
            status = "down"
            latency = 0
        else:
            latency = round(latency, 2)
            
        timestamp = time.time()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO pings (host, timestamp, latency, status) VALUES (?, ?, ?, ?)", (host, timestamp, latency, status))
        conn.commit()
        
        # Get last 10 pings for THIS HOST for stats
        c.execute("SELECT latency FROM pings WHERE host=? AND status='up' ORDER BY id DESC LIMIT 10", (host,))
        rows = c.fetchall()
        latencies = [r[0] for r in rows]
        
        jitter = 0
        if len(latencies) > 1:
            jitter = round(statistics.stdev(latencies), 2)
        
        conn.close()
        
        return {
            "host": host,
            "status": status,
            "latency": latency,
            "jitter": jitter,
            "method": method,
            "timestamp": datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
        }
        
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/stats")
def get_stats(host: str = None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Get last 50 records, optionally filtered by host
    if host:
        c.execute("SELECT timestamp, latency, status FROM pings WHERE host=? ORDER BY id DESC LIMIT 50", (host,))
    else:
        c.execute("SELECT timestamp, latency, status FROM pings ORDER BY id DESC LIMIT 50")
        
    rows = c.fetchall()
    conn.close()
    
    data = []
    for r in rows:
        data.append({
            "timestamp": datetime.fromtimestamp(r[0]).strftime('%H:%M:%S'),
            "latency": r[1],
            "status": r[2]
        })
    
    return data[::-1]

# Mount public directory for local development
# On Vercel, this is handled by the CDN, but Uvicorn needs this to serve index.html
if os.path.exists("public"):
    app.mount("/", StaticFiles(directory="public", html=True), name="public")
