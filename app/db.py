import os
import psycopg
from psycopg.rows import dict_row
from app.config import DATABASE_URL
import logging

logger = logging.getLogger(__name__)


DB_AVAILABLE = False
CONN = None


def init_db():
    global DB_AVAILABLE, CONN
    try:
        if not DATABASE_URL or not DATABASE_URL.startswith("postgres"):
            logger.info("DATABASE_URL not configured for Postgres; skipping DB init")
            DB_AVAILABLE = False
            return False

        # connect
        CONN = psycopg.connect(DATABASE_URL, autocommit=True)

        with CONN.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS members (
                    aadhaar_number varchar PRIMARY KEY,
                    full_name text NOT NULL,
                    dob varchar,
                    gender varchar,
                    mobile_number varchar,
                    pincode varchar,
                    education text,
                    profession text,
                    religion text,
                    reservation text,
                    caste text,
                    membership varchar,
                    membership_id varchar,
                    constituency text,
                    mandal text,
                    panchayathi text,
                    village text,
                    ward_number varchar,
                    latitude double precision,
                    longitude double precision,
                    aadhaar_image_url text,
                    photo_url text,
                    nominee_id varchar,
                    created_at timestamptz,
                    updated_at timestamptz
                )
                """
            )

        DB_AVAILABLE = True
        logger.info("Postgres DB initialized and available")
        return True
    except Exception as e:
        logger.warning("Failed to initialize Postgres DB: %s", e)
        DB_AVAILABLE = False
        CONN = None
        return False


def insert_or_update_member(member: dict):
    """Upsert member dict into Postgres members table."""
    if not DB_AVAILABLE or CONN is None:
        raise RuntimeError("DB not available")

    cols = [
        "aadhaar_number","full_name","dob","gender","mobile_number","pincode",
        "education","profession","religion","reservation","caste",
        "membership","membership_id","constituency","mandal","panchayathi",
        "village","ward_number","latitude","longitude","aadhaar_image_url",
        "photo_url","nominee_id","created_at","updated_at"
    ]

    values = [member.get(c) for c in cols]

    placeholders = ",".join(["%s"] * len(cols))
    set_clause = ",".join([f"{c}=EXCLUDED.{c}" for c in cols if c != "aadhaar_number"]) 

    sql = f"INSERT INTO members ({','.join(cols)}) VALUES ({placeholders}) ON CONFLICT (aadhaar_number) DO UPDATE SET {set_clause};"

    with CONN.cursor() as cur:
        cur.execute(sql, values)


def get_member(aadhaar: str):
    if not DB_AVAILABLE or CONN is None:
        return None
    with CONN.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM members WHERE aadhaar_number = %s", (aadhaar,))
        r = cur.fetchone()
        return dict(r) if r else None


def list_members(skip: int = 0, limit: int = 100):
    if not DB_AVAILABLE or CONN is None:
        return []
    with CONN.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM members ORDER BY created_at DESC LIMIT %s OFFSET %s", (limit, skip))
        rows = cur.fetchall()
        return [dict(r) for r in rows]


# initialize on import
init_db()
