# Ping Monitor (Vercel Ready)

A realtime ping monitoring application built with Python (FastAPI) and Vanilla JS.

## Features
- Realtime Latency Graph
- Jitter Calculation
- ICMP Ping with TCP Fallback (for serverless environments)
- Glassmorphism UI
- Deployable to Vercel

## Local Development

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run the server:
   ```bash
   uvicorn api.index:app --reload
   ```
3. Open `http://127.0.0.1:8000/public/index.html` (or serve public folder appropriately).
   *Note: On Vercel, `public` is served at root. Locally, you might need to adjust paths or just open the html file if CORS is set properly.*

## Vercel Deployment

1. Install Vercel CLI: `npm i -g vercel`
2. Run `vercel` in this directory.
3. Deploy!

## Notes on Vercel
- **Persistence**: Vercel functions are ephemeral. The SQLite database is stored in `/tmp` and will be cleared when the function instance is recycled. This is suitable for temporary session monitoring.
- **Ping Permissions**: ICMP ping often requires root. If it fails, the app falls back to TCP (port 80) connect latency.
