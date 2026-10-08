"""FastAPI ingestion and SQLite persistence."""

import json
import math
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

DB = Path(__file__).resolve().parents[1] / "data" / "telemetry.db"


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    session_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    event_type: Literal["session_start", "session_end", "death", "checkpoint", "level_complete"]
    ts: float = Field(ge=0)
    level: str = Field(min_length=1)
    x: float | None = Field(default=None, ge=0, le=100)
    y: float | None = Field(default=None, ge=0, le=100)
    cause: str | None = None
    reason: str | None = None
    time_s: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_fields(self):
        if not math.isfinite(self.ts):
            raise ValueError("ts must be finite")
        if self.event_type in {"death", "checkpoint"} and (self.x is None or self.y is None):
            raise ValueError("death/checkpoint require x and y")
        if self.event_type == "death" and not self.cause:
            raise ValueError("death requires cause")
        if self.event_type == "session_end" and not self.reason:
            raise ValueError("session_end requires reason")
        if self.event_type == "level_complete" and self.time_s is None:
            raise ValueError("level_complete requires time_s")
        return self


def init_db() -> None:
    DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, player_id TEXT NOT NULL,
            event_type TEXT NOT NULL, ts REAL NOT NULL, level TEXT NOT NULL,
            x REAL, y REAL, payload TEXT NOT NULL,
            UNIQUE(session_id, event_type, ts, level))""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_player_ts ON events(player_id, ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_events_level_type ON events(level, event_type)")


def insert_events(events: list[Event]) -> int:
    init_db()
    with sqlite3.connect(DB) as conn:
        before = conn.total_changes
        conn.executemany("""INSERT OR IGNORE INTO events
            (session_id, player_id, event_type, ts, level, x, y, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", [
                (e.session_id, e.player_id, e.event_type, e.ts, e.level, e.x, e.y,
                 json.dumps(e.model_dump(exclude={"session_id", "player_id", "event_type",
                                                  "ts", "level", "x", "y"}, exclude_none=True)))
                for e in events
            ])
        return conn.total_changes - before


def replace_events(raw_events: list[dict]) -> int:
    """Recreate only synthetic sessions, retaining manually ingested data."""
    events = [Event.model_validate(e) for e in raw_events]
    if any(not e.session_id.startswith("demo_") for e in events):
        raise ValueError("replace_events accepts demo sessions only")
    init_db()
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM events WHERE session_id LIKE 'demo_%'")
    return insert_events(events)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="Игровая телеметрия", lifespan=lifespan)


@app.post("/events", status_code=202)
def ingest(events: list[Event]) -> dict[str, int]:
    if not events:
        raise HTTPException(status_code=400, detail="At least one event is required")
    return {"accepted": insert_events(events)}
