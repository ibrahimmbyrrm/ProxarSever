# main.py
from dotenv import load_dotenv
load_dotenv()
import time, uuid, random

from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from typing import List, Optional
from jose import jwt, JWTError

class Settings(BaseSettings):
    database_url: str
    jwt_secret_key: str
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
app = FastAPI(title="CSI Backend MVP")
security = HTTPBearer()

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        return jwt.decode(credentials.credentials, settings.jwt_secret_key, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(401, "Geçersiz token")

# --- Modeller ---
class Position(BaseModel):
    x: float
    y: float

class Person(BaseModel):
    person_id: str
    timestamp: float
    state: str
    position: Position
    velocity_mgntd: Optional[float] = None

class FramePayload(BaseModel):
    market_id: str
    frame_id: int
    timestamp: float
    people: List[Person]

# --- Endpoint'ler ---
@app.post("/ingest", status_code=202)
async def ingest(payload: FramePayload, token=Depends(verify_token), db: AsyncSession = Depends(get_db)):
    if payload.market_id != token.get("market_id"):
        raise HTTPException(403, "Market ID uyuşmuyor")

    await db.execute(text(
        "INSERT INTO frames (frame_id, market_id, timestamp, person_count) "
        "VALUES (:fid, :mid, :ts, :pc) ON CONFLICT DO NOTHING"
    ), {"fid": payload.frame_id, "mid": payload.market_id, "ts": payload.timestamp, "pc": len(payload.people)})

    for p in payload.people:
        await db.execute(text(
            "INSERT INTO persons (frame_id, market_id, person_id, timestamp, state, pos_x, pos_y, velocity_mgntd) "
            "VALUES (:fid,:mid,:pid,:ts,:st,:x,:y,:v)"
        ), {"fid": payload.frame_id, "mid": payload.market_id, "pid": p.person_id,
            "ts": p.timestamp, "st": p.state, "x": p.position.x, "y": p.position.y, "v": p.velocity_mgntd})

    await db.commit()
    return {"status": "accepted", "frame_id": payload.frame_id}

@app.get("/markets/{market_id}/frames")
async def get_frames(market_id: str, limit: int = 50, token=Depends(verify_token), db: AsyncSession = Depends(get_db)):
    if market_id != token.get("market_id"):
        raise HTTPException(403)
    rows = await db.execute(text(
        "SELECT frame_id, timestamp, person_count, received_at FROM frames "
        "WHERE market_id = :mid ORDER BY timestamp DESC LIMIT :lim"
    ), {"mid": market_id, "lim": limit})
    return {"data": [dict(r._mapping) for r in rows]}

@app.get("/markets/{market_id}/frames/{frame_id}")
async def get_frame(market_id: str, frame_id: int, token=Depends(verify_token), db: AsyncSession = Depends(get_db)):
    if market_id != token.get("market_id"):
        raise HTTPException(403)
    frame = await db.execute(text(
        "SELECT * FROM frames WHERE frame_id=:fid AND market_id=:mid"
    ), {"fid": frame_id, "mid": market_id})
    row = frame.first()
    if not row:
        raise HTTPException(404, "Frame bulunamadı")
    persons = await db.execute(text(
        "SELECT person_id, timestamp, state, pos_x, pos_y, velocity_mgntd "
        "FROM persons WHERE frame_id=:fid"
    ), {"fid": frame_id})
    return {
        **dict(row._mapping),
        "people": [dict(p._mapping) for p in persons]
    }

@app.get("/markets/{market_id}/stats")
async def get_stats(market_id: str, token=Depends(verify_token), db: AsyncSession = Depends(get_db)):
    if market_id != token.get("market_id"):
        raise HTTPException(403)
    r = await db.execute(text("""
        SELECT COUNT(*) as total_frames,
               AVG(person_count) as avg_occupancy,
               MAX(person_count) as peak_occupancy,
               MIN(timestamp) as first_ts,
               MAX(timestamp) as last_ts
        FROM frames WHERE market_id = :mid
    """), {"mid": market_id})
    return dict(r.first()._mapping)

# --- Token üretici (geliştirme için) ---
@app.post("/dev/token")
async def dev_token(market_id: str):
    token = jwt.encode(
        {"market_id": market_id, "sub": market_id},
        settings.jwt_secret_key, algorithm="HS256"
    )
    return {"token": token}