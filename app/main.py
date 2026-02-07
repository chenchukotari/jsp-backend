from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, field_validator
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
    allow_origins=["*"],
    allow_credentials=False,
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


def _normalize_aadhaar(aadhaar: str) -> str:
    """Return digits-only 12-digit Aadhaar string or empty string if invalid."""
    if not aadhaar:
        return ""
    digits = re.sub(r"\D", "", aadhaar)
    return digits if len(digits) == 12 else digits



# ============ PYDANTIC SCHEMAS ============

class Item(BaseModel):
    id: int
    name: str


class GeographyResponse(BaseModel):
    """Geography lookup response"""
    village_name: str
    panchayati_name: str | None = None
    mandal_name: str | None = None
    constituency_name: str | None = None
    pincode: str | None = None


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
    
    # Nominee Details
    nominee_id: str
    nominee_full_name: str | None = None
    nominee_dob: str | None = None
    nominee_gender: str | None = None
    nominee_mobile_number: str | None = None
    nominee_education: str | None = None
    nominee_profession: str | None = None
    nominee_religion: str | None = None
    nominee_reservation: str | None = None
    nominee_caste: str | None = None
    nominee_membership: str | None = None
    nominee_membership_id: str | None = None
    nominee_aadhaar_image_url: str | None = None
    nominee_photo_url: str | None = None
    
    @field_validator('nominee_id')
    def nominee_id_not_null(cls, v):
        if not v or (isinstance(v, str) and v.strip() == ""):
            raise ValueError("nominee_id cannot be null or empty")
        return v


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
            gender = gm.group(1).capitalize()
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
    print(f"DEBUG: submit_person payload: {payload.dict()}")
    """Save or update member registration from form submission"""
    try:
        aadhaar_digits = _normalize_aadhaar(payload.aadhaar_number)
        if not aadhaar_digits or len(aadhaar_digits) != 12:
            raise HTTPException(status_code=400, detail="Member Aadhaar must be exactly 12 digits")

        # Validate Nominee Aadhaar
        nominee_aadhaar_clean = _normalize_aadhaar(payload.nominee_id)
        if not nominee_aadhaar_clean or len(nominee_aadhaar_clean) != 12:
            raise HTTPException(status_code=400, detail="Nominee Aadhaar must be exactly 12 digits")

        member_data = payload.dict()
        
        # Filter out nominee specific fields for the member record
        # Filter out nominee specific fields for the member record, but keep nominee_id and image links
        member_fields = {k: v for k, v in member_data.items() 
                        if not k.startswith("nominee_") or k in ["nominee_id", "nominee_aadhaar_image_url", "nominee_photo_url"]}
        member_fields["created_at"] = datetime.utcnow().isoformat()
        member_fields["updated_at"] = datetime.utcnow().isoformat()
        member_fields["is_registered"] = True  # Mark primary member as registered

        if db.DB_AVAILABLE:
            try:
                # 1. Save Member (Clean fields to allow COALESCE)
                clean_member = {k: v for k, v in member_fields.items() if v is not None and str(v).strip() != ""}
                db.insert_or_update_member(clean_member)
                
                # 2. Save Nominee if details provided
                if payload.nominee_id:
                    nominee_data = {
                        "aadhaar_number": nominee_aadhaar_clean,
                        "full_name": payload.nominee_full_name,
                        "dob": payload.nominee_dob,
                        "gender": payload.nominee_gender,
                        "mobile_number": payload.nominee_mobile_number,
                        "education": payload.nominee_education,
                        "profession": payload.nominee_profession,
                        "religion": payload.nominee_religion,
                        "reservation": payload.nominee_reservation,
                        "caste": payload.nominee_caste,
                        "membership": payload.nominee_membership,
                        "membership_id": payload.nominee_membership_id,
                        "aadhaar_image_url": payload.nominee_aadhaar_image_url,
                        "photo_url": payload.nominee_photo_url,
                        "is_registered": False,  # Nominee is not a registered member unless they submit independently
                        "created_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat()
                    }
                    clean_nominee = {k: v for k, v in nominee_data.items() if v is not None and str(v).strip() != ""}
                    if any(v for k, v in clean_nominee.items() if k not in ["aadhaar_number", "created_at", "updated_at", "is_registered"]):
                        db.insert_or_update_member(clean_nominee)

                return {"status": "upserted", "member_id": aadhaar_digits, "aadhaar": aadhaar_digits}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"DB error: {e}")
        else:
            members = load_members()
            
            # Clean and Update Member
            clean_member = {k: v for k, v in member_fields.items() if v is not None and str(v).strip() != ""}
            if aadhaar_digits in members:
                was_reg = members[aadhaar_digits].get("is_registered", False)
                members[aadhaar_digits].update(clean_member)
                members[aadhaar_digits]["is_registered"] = was_reg or clean_member.get("is_registered", False)
                members[aadhaar_digits]["updated_at"] = datetime.utcnow().isoformat()
            else:
                members[aadhaar_digits] = clean_member
            
            # Clean and Update Nominee
            if payload.nominee_id:
                nid = nominee_aadhaar_clean
                nominee_data = {
                    "aadhaar_number": nid,
                    "full_name": payload.nominee_full_name,
                    "dob": payload.nominee_dob,
                    "gender": payload.nominee_gender,
                    "mobile_number": payload.nominee_mobile_number,
                    "education": payload.nominee_education,
                    "profession": payload.nominee_profession,
                    "religion": payload.nominee_religion,
                    "reservation": payload.nominee_reservation,
                    "caste": payload.nominee_caste,
                    "membership": payload.nominee_membership,
                    "membership_id": payload.nominee_membership_id,
                    "aadhaar_image_url": payload.nominee_aadhaar_image_url,
                    "photo_url": payload.nominee_photo_url,
                    "is_registered": False,
                    "updated_at": datetime.utcnow().isoformat()
                }
                clean_nominee = {k: v for k, v in nominee_data.items() if v is not None and str(v).strip() != ""}
                if any(v for k, v in clean_nominee.items() if k not in ["aadhaar_number", "updated_at", "is_registered"]):
                    if nid in members:
                        was_reg = members[nid].get("is_registered", False)
                        members[nid].update(clean_nominee)
                        members[nid]["is_registered"] = was_reg or clean_nominee.get("is_registered", False)
                    else:
                        clean_nominee["created_at"] = datetime.utcnow().isoformat()
                        members[nid] = clean_nominee
            
            save_members(members)
            return {"status": "success", "member_id": aadhaar_digits, "aadhaar": aadhaar_digits}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to save member: {str(e)}")


@app.get("/person/exists/{aadhaar}")
async def check_person_exists(aadhaar: str):
    """Check if person exists and return data for auto-population"""
    clean_aad = aadhaar.replace(" ", "")
    m = None
    if db.DB_AVAILABLE:
        m = db.get_member(clean_aad)
    else:
        members = load_members()
        m = members.get(clean_aad)
        
    if m:
        return {"exists": True, "member": m}
    return {"exists": False}


@app.get("/person/by-aadhaar/{aadhaar}")
async def get_person_by_aadhaar(aadhaar: str):
    """Lookup member by Aadhaar number"""
    clean_aad = aadhaar.replace(" ", "")
    if db.DB_AVAILABLE:
        m = db.get_member(clean_aad)
        if not m:
            raise HTTPException(status_code=404, detail="Member not found")
        return m

    members = load_members()
    if clean_aad not in members:
        raise HTTPException(status_code=404, detail="Member not found")
    return members[clean_aad]


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


@app.get("/person/exists/{aadhaar}")
async def person_exists(aadhaar: str):
    """Check whether a person exists for given Aadhaar. Returns exists flag and optional member."""
    aadhaar_digits = _normalize_aadhaar(aadhaar)
    if not aadhaar_digits:
        raise HTTPException(status_code=400, detail="Invalid Aadhaar number")

    if db.DB_AVAILABLE:
        m = db.get_member(aadhaar_digits)
        return {"exists": bool(m), "member": m}

    members = load_members()
    m = members.get(aadhaar_digits)
    return {"exists": bool(m), "member": m}


@app.post("/person/create")
async def create_person(payload: PersonSubmitRequest):
    """Create a new person/member only if Aadhaar does not already exist.

    Returns 409 if Aadhaar already exists.
    """
    aadhaar_digits = _normalize_aadhaar(payload.aadhaar_number)
    if not aadhaar_digits or len(aadhaar_digits) != 12:
        raise HTTPException(status_code=400, detail="Invalid Aadhaar number")

    member_data = payload.dict()
    member_data["aadhaar_number"] = aadhaar_digits
    member_data["created_at"] = datetime.utcnow().isoformat()
    member_data["updated_at"] = datetime.utcnow().isoformat()

    if db.DB_AVAILABLE:
        existing = db.get_member(aadhaar_digits)
        if existing:
            raise HTTPException(status_code=409, detail="This person is already registered as a member.")
        try:
            db.insert_or_update_member(member_data)
            return {"status": "created", "member_id": aadhaar_digits}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DB error: {e}")

    members = load_members()
    if aadhaar_digits in members:
        raise HTTPException(status_code=409, detail="This person is already registered as a member.")
    members[aadhaar_digits] = member_data
    save_members(members)
    return {"status": "created", "member_id": aadhaar_digits}


# ============ GEOGRAPHY LOOKUP ============

@app.get("/geography/lookup/{village_name}", response_model=GeographyResponse)
async def lookup_geography(village_name: str):
    """Lookup geography data by village name (case-insensitive).
    
    Returns panchayati_name, mandal_name, constituency_name, and pincode.
    Ward number is NOT returned as multiple wards can exist within the same village.
    
    Returns 404 if village not found.
    """
    if not village_name or not village_name.strip():
        raise HTTPException(status_code=400, detail="Village name is required")
    
    if not db.DB_AVAILABLE:
        raise HTTPException(status_code=503, detail="Geography database not available")
    
    result = db.lookup_geography(village_name.strip())
    if not result:
        raise HTTPException(status_code=404, detail="Village not found in geography database")
    
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
