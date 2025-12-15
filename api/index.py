
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
from fastapi.responses import HTMLResponse, FileResponse

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
    
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS pings
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      host TEXT,
                      timestamp REAL,
                      latency REAL,
                      status TEXT)''')
                      
        c.execute('''CREATE TABLE IF NOT EXISTS hosts
                     (host TEXT PRIMARY KEY)''')
        
        # Default hosts if empty
        c.execute("SELECT count(*) FROM hosts")
        if c.fetchone()[0] == 0:
            defaults = ['8.8.8.8', '36.64.212.42', '112.78.46.69']
            for h in defaults:
                c.execute("INSERT INTO hosts (host) VALUES (?)", (h,))

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



class HostItem(BaseModel):
    host: str

@app.get("/api/hosts")
def get_hosts():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT host FROM hosts")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

@app.post("/api/hosts")
def add_host(item: HostItem):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO hosts (host) VALUES (?)", (item.host,))
        conn.commit()
        conn.close()
        return {"status": "added", "host": item.host}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.delete("/api/hosts/{host}")
def remove_host(host: str):
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM hosts WHERE host=?", (host,))
        conn.commit()
        conn.close()
        return {"status": "removed", "host": host}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/cron")
def run_cron():
    """
    This endpoint is called by Vercel Cron Jobs.
    It fetches all hosts from DB and pings them.
    """
    hosts = get_hosts()
    results = []
    
    for host in hosts:
        # Re-use the existing ping logic manually or call the function
        # Calling perform_ping directly is easier since we have the logic there
        # but perform_ping returns a Pydantic model or dict.
        # Let's just instantiate the target and call the function.
        try:
            res = perform_ping(PingTarget(host=host))
            results.append(res)
        except:
            results.append({"host": host, "status": "failed_job"})
            
    return {"cron_status": "completed", "results": results}



@app.get("/api/health")
def health_check():
    return {"status": "ok"}


def tcp_ping(host, ports=[80, 443, 53, 8080], timeout=2):
    import socket
    # If user provided a specific port in host (e.g., 1.2.3.4:9000), use that.
    if ":" in host:
        try:
            h, p = host.split(":")
            return _single_tcp_ping(h, int(p), timeout)
        except:
            pass
            
    for port in ports:
        res = _single_tcp_ping(host, port, timeout)
        if res is not None:
            return res
    return None

def _single_tcp_ping(host, port, timeout):
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
        # Vercel almost always blocks ICMP (Permission denied).
        # We try ICMP only if we are lucky (e.g. running locally as root), 
        # otherwise we immediately fallback to smart TCP pinging.
        try:
            if os.environ.get("VERCEL"):
                raise OSError("Skip ICMP on Vercel")
            latency = ping(host, timeout=1, unit='ms')
        except OSError:
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



@app.get("/", response_class=HTMLResponse)
async def read_root():
    # Serve index.html from the same directory as this script
    base_dir = os.path.dirname(os.path.realpath(__file__))
    file_path = os.path.join(base_dir, "index.html")
    with open(file_path, "r") as f:
        return f.read()

# Mount current directory for local development (fallback if needed, but root is now handled above)
# We can remove the old app.mount logic or keep it for assets if we had them.
# For this single-file app, the root handler is sufficient.
