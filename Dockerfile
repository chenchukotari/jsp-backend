FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY data ./data 2>/dev/null || true

# Render sets the PORT env var. Default to 8080 if not provided.
ENV PORT=8080

EXPOSE 8080

# Use the PORT env var so Render can bind correctly.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT}
