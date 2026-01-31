"""
Configuration and constants for the JSP Backend application.
Store sensitive data and environment variables here.
"""

import os

# ============ DATABASE CONFIGURATION ============
# Default to the Render external database URL. This can be overridden
# by setting the `DATABASE_URL` environment variable locally or in Render.
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://jsp_user:yjIu8kiTIHxCXN7fZIsOiChPTa5lNtmD@dpg-d5uuor4oud1c7384pf50-a.oregon-postgres.render.com/jsp_db"
)

# ============ OCR CONFIGURATION ============
OCR_SPACE_API_KEY = os.getenv("OCR_SPACE_API_KEY", "helloworld")
OCR_SPACE_API_URL = "https://api.ocr.space/parse/image"

# ============ CORS CONFIGURATION ============
CORS_ORIGINS = [
    # Local development
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    # Vercel deployments
    "https://*.vercel.app",
    # Render backend
    "https://aadhaar-backend-uu1u.onrender.com",
    # Allow all origins (can be restricted later)
    "*",
]

# ============ SERVER CONFIGURATION ============
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", 8000))
RELOAD = os.getenv("RELOAD", "True").lower() in ("true", "1", "yes")

# ============ API ENDPOINTS ============
API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8001")
