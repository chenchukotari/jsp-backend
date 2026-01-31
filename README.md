# Minimal FastAPI REST API

Files added:
- `app/main.py` — FastAPI application with a GET `/hello` and POST `/items` endpoint.
- `requirements.txt` — dependencies.

Quick start (local):

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Run locally (dev):

```bash
uvicorn app.main:app --reload
```

Or run directly (no reload):

```bash
python3 app/main.py
```

Open http://127.0.0.1:8000/hello to see the JSON response.

Deploying to Render

This project includes a `Dockerfile` and is ready to deploy on Render as a Web Service using your repository.

Steps to deploy on Render (Docker):

1. Push your repo to GitHub (or another supported Git provider).
2. In Render, create a new `Web Service` and connect your repo.
3. Choose `Docker` as the environment; Render will build the provided `Dockerfile`.
4. Set the `PORT` environment variable if you want a custom port (Render provides `$PORT` automatically).

Notes and tips:
- The `Dockerfile` uses the `PORT` env var so Render can bind to the supplied port.
- Render sets a `PORT` environment variable — the container uses `${PORT:-8080}` by default.
- For a non-Docker deployment, Render can also detect Python apps; provide a start command like `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.

Files of interest:
- [Dockerfile](Dockerfile) — container definition for the app.

If you'd like, I can add a `render.yaml` with a recommended service spec, or update the `Dockerfile` to use Gunicorn + Uvicorn workers for production.
gcloud config set project PROJECT_ID


