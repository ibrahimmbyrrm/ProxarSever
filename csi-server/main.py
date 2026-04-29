import logging
from fastapi import FastAPI, HTTPException, Depends, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
from jose import jwt, JWTError

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    env: str = "development"  # FIX: typo "developlemt" → "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
app = FastAPI(
    title="CSI Backend API",
    description="RESTful API for processing camera frames and human tracking data for customer behavior analysis.",
    version="1.2.0"
)
security = HTTPBearer()

# --- Database Setup ---
engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    pool_recycle=3600,
    connect_args={"ssl": "require"} # Supabase için kritik olabilir
)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def get_db():
    # FIX: removed redundant finally/close — `async with` handles it already
    async with AsyncSessionLocal() as session:
        yield session


# --- Security & Authorization ---
def get_current_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret_key,
            algorithms=["HS256"]
        )
        return payload
    except JWTError as e:
        logger.warning(f"Invalid token attempt: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token. Please log in again."
        )


def verify_market_access(expected_market_id: str, token_payload: dict):
    """Checks if the market_id in the user's token matches the requested market_id."""
    token_market_id = token_payload.get("market_id")
    if expected_market_id != token_market_id:
        logger.warning(
            f"Unauthorized access attempt. Requested: {expected_market_id}, "
            f"Token has: {token_market_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: You are not authorized for market ID '{expected_market_id}'."
        )


# --- Data Models ---
class Position(BaseModel):
    x: float = Field(..., description="X coordinate")
    y: float = Field(..., description="Y coordinate")


class Person(BaseModel):
    person_id: str = Field(..., description="Unique tracking ID assigned to the person")
    timestamp: float
    state: str = Field(..., description="State of the person (e.g., walking, standing, interacting)")
    position: Position
    velocity_mgntd: Optional[float] = Field(None, description="Magnitude of movement velocity")


class FramePayload(BaseModel):
    market_id: str = Field(..., description="ID of the market where the camera is located")
    frame_id: int = Field(..., description="Sequence number of the processed frame")
    timestamp: float = Field(..., description="Unix timestamp when the frame was processed")
    people: List[Person] = Field(default_factory=list, description="List of detected people in the frame")


# --- API Endpoints ---

@app.post("/ingest", status_code=status.HTTP_202_ACCEPTED, tags=["Data Ingestion"])
async def ingest(
        payload: FramePayload,
        token: dict = Depends(get_current_token),
        db: AsyncSession = Depends(get_db)
):
    """Saves real-time skeleton/person tracking data from cameras into the system."""
    verify_market_access(payload.market_id, token)

    try:
        await db.execute(text(
            "INSERT INTO frames (frame_id, market_id, timestamp, person_count) "
            "VALUES (:fid, :mid, :ts, :pc) ON CONFLICT DO NOTHING"
        ), {"fid": payload.frame_id, "mid": payload.market_id, "ts": payload.timestamp, "pc": len(payload.people)})

        if payload.people:
            persons_data = [
                {
                    "fid": payload.frame_id, "mid": payload.market_id, "pid": p.person_id,
                    "ts": p.timestamp, "st": p.state, "x": p.position.x, "y": p.position.y,
                    "v": p.velocity_mgntd
                }
                for p in payload.people
            ]
            await db.execute(text(
                "INSERT INTO persons (frame_id, market_id, person_id, timestamp, state, pos_x, pos_y, velocity_mgntd) "
                "VALUES (:fid, :mid, :pid, :ts, :st, :x, :y, :v)"
            ), persons_data)

        await db.commit()
        logger.info(f"Ingested frame {payload.frame_id} for market {payload.market_id} "
                    f"with {len(payload.people)} people.")
        return {
            "status": "accepted",
            "frame_id": payload.frame_id,
            "inserted_people": len(payload.people)
        }


    except SQLAlchemyError as e:

        await db.rollback()

        logger.error(f"Database insertion error (Frame ID: {payload.frame_id}): {str(e)}")

        raise HTTPException(

            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,

            detail=str(e)  # geçici olarak gerçek hatayı dön

        )


@app.get("/markets/{market_id}/stats", tags=["Analytics"])
async def get_stats(
        market_id: str,
        token: dict = Depends(get_current_token),
        db: AsyncSession = Depends(get_db)
):
    """Calculates and returns general statistics for the market."""
    verify_market_access(market_id, token)

    r = await db.execute(text("""
        SELECT COUNT(*) as total_frames,
               COALESCE(AVG(person_count), 0) as avg_occupancy,
               COALESCE(MAX(person_count), 0) as peak_occupancy,
               MIN(timestamp) as first_ts,
               MAX(timestamp) as last_ts
        FROM frames WHERE market_id = :mid
    """), {"mid": market_id})

    stats = dict(r.first()._mapping)
    if stats.get("total_frames") == 0:
        return {"message": "No data collected for this market yet.", "stats": stats}

    return stats
logger.info(f"DATABASE_URL: {settings.database_url}")

@app.get("/markets/{market_id}/frames/{frame_id}", tags=["Analytics"])
async def get_frame(
        market_id: str,
        frame_id: int,
        token: dict = Depends(get_current_token),
        db: AsyncSession = Depends(get_db)
):
    """Retrieves detailed data of a specific frame and all people within it."""
    verify_market_access(market_id, token)

    frame_res = await db.execute(text(
        "SELECT * FROM frames WHERE frame_id=:fid AND market_id=:mid"
    ), {"fid": frame_id, "mid": market_id})

    frame_row = frame_res.first()
    if not frame_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Frame with ID '{frame_id}' not found in this market."
        )

    # FIX: Added market_id filter to prevent cross-market data leakage
    persons_res = await db.execute(text(
        "SELECT person_id, timestamp, state, pos_x, pos_y, velocity_mgntd "
        "FROM persons WHERE frame_id=:fid AND market_id=:mid"
    ), {"fid": frame_id, "mid": market_id})

    return {
        **dict(frame_row._mapping),
        "people": [dict(p._mapping) for p in persons_res]
    }


@app.get("/markets/{market_id}/frames", tags=["Analytics"])
async def list_frames(
        market_id: str,
        limit: int = Query(default=50, ge=1, le=500, description="Number of frames to return"),
        offset: int = Query(default=0, ge=0, description="Pagination offset"),
        token: dict = Depends(get_current_token),
        db: AsyncSession = Depends(get_db)
):
    """Lists recent frames for a market with pagination support."""
    verify_market_access(market_id, token)

    result = await db.execute(text(
        "SELECT frame_id, timestamp, person_count "
        "FROM frames WHERE market_id=:mid "
        "ORDER BY timestamp DESC LIMIT :limit OFFSET :offset"
    ), {"mid": market_id, "limit": limit, "offset": offset})

    return {"market_id": market_id, "frames": [dict(r._mapping) for r in result]}


@app.get("/health", tags=["System"])
async def health_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}") # Gerçek hatayı logla!
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection failed: {str(e)}" # Postman/Tarayıcıda da gör
        )

@app.get("/debug")
async def debug():
    return {
        "env": settings.env,
        "db": settings.database_url
    }
# --- Development Tools ---
@app.post("/dev/token", tags=["Development"])
async def dev_token(market_id: str = Query(..., description="Market ID to embed in the token")):
    """FOR DEVELOPMENT ONLY: Generates a mock JWT for testing purposes."""
    if settings.env.lower() == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint is disabled in production."
        )

    token = jwt.encode(
        {"market_id": market_id, "sub": market_id},
        settings.jwt_secret_key,
        algorithm="HS256"
    )
    return {"token": token, "warning": "Use this token in test environments only."}