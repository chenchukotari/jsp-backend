from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import re
import requests
import json
from starlette.concurrency import run_in_threadpool
from datetime import datetime
from app.config import OCR_SPACE_API_KEY, OCR_SPACE_API_URL, CORS_ORIGINS
from pathlib import Path
from app import db

app = FastAPI()

# ============ CORS SETUP ============
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ FILE-BASED STORAGE ============
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
MEMBERS_FILE = DATA_DIR / "members.json"


def load_members():
    """Load members from JSON file"""
    if MEMBERS_FILE.exists():
        with open(MEMBERS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_members(members):
    """Save members to JSON file"""
    with open(MEMBERS_FILE, "w") as f:
        json.dump(members, f, indent=2, default=str)


# ============ PYDANTIC SCHEMAS ============

class Item(BaseModel):
    id: int
    name: str


class PersonSubmitRequest(BaseModel):
    """Form submission payload from UI"""
    aadhaar_number: str
    full_name: str
    dob: str | None = None
    gender: str | None = None
    mobile_number: str | None = None
    pincode: str | None = None
    
    education: str | None = None
    profession: str | None = None
    religion: str | None = None
    reservation: str | None = None
    caste: str | None = None
    
    membership: str | None = None
    membership_id: str | None = None
    
    constituency: str | None = None
    mandal: str | None = None
    panchayathi: str | None = None
    village: str | None = None
    ward_number: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    
    aadhaar_image_url: str | None = None
    photo_url: str | None = None
    
    nominee_id: str | None = None


# ============ BASIC ENDPOINTS ============

@app.get("/hello")
async def hello():
    return {"message": "Hello, world!"}


@app.post("/items")
async def create_item(item: Item):
    return {"status": "created", "item": item}


# ============ OCR HELPER FUNCTIONS ============

def _extract_fields(parsed_text: str) -> dict:
    lines = [l.strip() for l in re.split(r"[\r\n]+", parsed_text) if l.strip()]

    # Find DOB by searching for date patterns or 'DOB' label
    dob = None
    date_re = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b")
    for i, line in enumerate(lines):
        if "dob" in line.lower() or "d o b" in line.lower():
            m = date_re.search(line)
            if m:
                dob = m.group(1)
            else:
                # look next tokens
                if i + 1 < len(lines):
                    m2 = date_re.search(lines[i + 1])
                    if m2:
                        dob = m2.group(1)
            break
    if not dob:
        for line in lines:
            m = date_re.search(line)
            if m:
                dob = m.group(1)
                break

    # Heuristic for name: take the non-labelled line before DOB or first capitalized pair
    name = None
    if dob:
        for i, line in enumerate(lines):
            if dob in line:
                # look backwards for a likely name
                j = i - 1
                while j >= 0:
                    candidate = lines[j]
                    if candidate and not any(k in candidate.lower() for k in ("aadhaar","vid","address","dob","date","authority","sign")):
                        # pick candidate with letters and at least one space
                        if re.search(r"[A-Za-z]", candidate) and " " in candidate:
                            name = candidate
                            break
                    j -= 1
                break
    if not name:
        # fallback: find first line of two capitalized words
        for line in lines:
            if re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+", line):
                name = line
                break

    # Address: find 'Address' label and collect following lines
    address = None
    for i, line in enumerate(lines):
        if line.lower().startswith("address") or "address:" in line.lower():
            parts = []
            # collect next up to 6 lines or until a blank / unrelated token
            for j in range(i + 1, min(i + 7, len(lines))):
                if re.search(r"\b\d{6}\b", lines[j]):
                    parts.append(lines[j])
                    break
                if any(k in lines[j].lower() for k in ("aadhar","vid","dob","male","female","authority")):
                    break
                parts.append(lines[j])
            address = ", ".join(parts).strip()
            break

    # Aadhaar number: look for 12 digits or 4-4-4 grouped format
    aadhaar = None
    aadhaar_re = re.compile(r"\b(\d{4}\s*\d{4}\s*\d{4}|\d{12})\b")
    for line in lines:
        m = aadhaar_re.search(line.replace('-', ' ').replace(',', ' '))
        if m:
            digits = re.sub(r"\D", "", m.group(1))
            if len(digits) == 12:
                aadhaar = f"{digits[0:4]} {digits[4:8]} {digits[8:12]}"
                break

    # Gender: look for MALE / FEMALE tokens
    gender = None
    for line in lines:
        gm = re.search(r"\b(male|female)\b", line, re.IGNORECASE)
        if gm:
            gender = gm.group(1).upper()
            break

    return {
        "name": name or "",
        "dob": dob or "",
        "address": address or "",
        "aadhaar": aadhaar or "",
        "gender": gender or "",
    }


@app.post("/ocr-parse")
async def ocr_parse(file: UploadFile = File(...), apikey: str = Form(None)):
    """Accepts an uploaded image, forwards to OCR.space, and returns extracted fields.

    - `file`: image file upload
    - `apikey`: optional OCR.space API key (falls back to config or 'helloworld')
    """
    api_key = apikey or OCR_SPACE_API_KEY

    content = await file.read()
    filename = getattr(file, "filename", "upload")
    content_type = getattr(file, "content_type", "application/octet-stream")

    data = {"apikey": api_key}
    files = {"file": (filename, content, content_type)}

    # Use requests in a thread to avoid httpx/httpcore issues on some Python versions
    try:
        resp = await run_in_threadpool(requests.post, OCR_SPACE_API_URL, data=data, files=files, timeout=30)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OCR provider request failed: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="OCR provider error")

    j = resp.json()
    parsed_text = ""
    try:
        parsed = j.get("ParsedResults")
        if parsed and len(parsed) > 0:
            parsed_text = parsed[0].get("ParsedText", "")
    except Exception:
        parsed_text = ""

    extracted = _extract_fields(parsed_text)
    return {"extracted": extracted}


# ============ PERSON/MEMBER ENDPOINTS ============

@app.post("/person/submit")
async def submit_person(payload: PersonSubmitRequest):
    """Save or update member registration from form submission"""
    try:
        aadhaar = payload.aadhaar_number
        member_data = payload.dict()
        member_data["created_at"] = datetime.utcnow().isoformat()
        member_data["updated_at"] = datetime.utcnow().isoformat()

        if db.DB_AVAILABLE:
            # use Postgres
            try:
                db.insert_or_update_member(member_data)
                return {"status": "upserted", "member_id": aadhaar, "aadhaar": aadhaar}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"DB error: {e}")
        else:
            # fallback to file-based storage
            members = load_members()
            if aadhaar in members:
                members[aadhaar]["updated_at"] = datetime.utcnow().isoformat()
                members[aadhaar].update(member_data)
                status = "updated"
            else:
                members[aadhaar] = member_data
                status = "created"
            save_members(members)
            return {"status": status, "member_id": aadhaar, "aadhaar": aadhaar}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save member: {str(e)}")


@app.get("/person/by-aadhaar/{aadhaar}")
async def get_person_by_aadhaar(aadhaar: str):
    """Lookup member by Aadhaar number"""
    if db.DB_AVAILABLE:
        m = db.get_member(aadhaar)
        if not m:
            raise HTTPException(status_code=404, detail="Member not found")
        return m
    members = load_members()
    if aadhaar not in members:
        raise HTTPException(status_code=404, detail="Member not found")
    return members[aadhaar]


@app.get("/person/list")
async def list_members(skip: int = 0, limit: int = 100):
    """List all members (with pagination)"""
    if db.DB_AVAILABLE:
        rows = db.list_members(skip=skip, limit=limit)
        # total is not computed efficiently here; return count of returned
        return {"total": len(rows), "members": rows}

    members = load_members()
    all_members = list(members.values())
    paginated = all_members[skip:skip + limit]
    return {
        "total": len(all_members),
        "members": paginated
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
