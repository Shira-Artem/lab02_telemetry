"""JSONL logger and reproducible synthetic game sessions."""

import argparse
import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
JSONL = ROOT / "data" / "events.jsonl"
SERVER = "http://127.0.0.1:8000/events"


class TelemetryLogger:
    def __init__(self, player_id: str, session_id: str | None = None, *,
                 path: Path = JSONL, url: str | None = None, batch_size: int = 20):
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.player_id = player_id
        self.session_id = session_id or uuid.uuid4().hex
        self.path = path
        self.url = url
        self.batch_size = batch_size
        self.buffer: list[dict] = []
        self._written = 0

    def log(self, event_type: str, level: str, *, ts: float | None = None, **fields) -> None:
        import time

        self.buffer.append({"session_id": self.session_id, "player_id": self.player_id,
                            "event_type": event_type, "ts": time.time() if ts is None else ts,
                            "level": level, **fields})
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self.buffer:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._written < len(self.buffer):
            with self.path.open("a", encoding="utf-8") as handle:
                for event in self.buffer[self._written:]:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._written = len(self.buffer)
        if self.url:
            response = requests.post(self.url, json=self.buffer, timeout=10)
            response.raise_for_status()
        self.buffer.clear()
        self._written = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.flush()


def generate_sessions(n_sessions: int = 40, seed: int = 42) -> list[dict]:
    """Create 30–50 deterministic, chronological sessions across four UTC dates."""
    if not 30 <= n_sessions <= 50:
        raise ValueError("demo requires 30–50 sessions")
    rng = random.Random(seed)
    start_day = datetime(2026, 9, 1, 10, tzinfo=timezone.utc)
    events = []
    for i in range(n_sessions):
        day, slot = divmod(i, 12)
        player_number = (slot + 1 if day == 0 else
                         slot + 1 if slot < max(2, 10 - day * 2) else
                         12 + (day - 1) * 6 + slot - max(2, 10 - day * 2) + 1)
        player = f"player_{player_number:02d}"
        level = f"L{1 + (i // 12) % 3}"
        start = start_day + timedelta(days=day, minutes=rng.randint(0, 600))
        start_ts = start.timestamp()
        session = f"demo_{seed}_{i + 1:03d}"

        def add(kind: str, offset: int, **extra):
            events.append({"session_id": session, "player_id": player,
                           "event_type": kind, "ts": start_ts + offset,
                           "level": level, **extra})

        add("session_start", 0)
        elapsed = rng.randint(30, 95)
        for _ in range(rng.randint(0, 3)):
            x = rng.gauss(28 if level == "L1" else 65, 9)
            add("death", elapsed, x=round(max(0, min(100, x)), 2),
                y=round(rng.uniform(0, 100), 2), cause=rng.choice(["spikes", "enemy", "fall"]))
            elapsed += rng.randint(20, 55)
        if rng.random() < 0.82:
            add("checkpoint", elapsed, x=50.0, y=50.0)
            elapsed += rng.randint(60, 140)
            if rng.random() < 0.68:
                add("level_complete", elapsed, time_s=elapsed)
                elapsed += rng.randint(8, 30)
        add("session_end", elapsed + rng.randint(15, 80), reason="quit")
    return events


def write_demo(events: list[dict], *, path: Path = JSONL, send_http: bool = False) -> None:
    """Replace demo JSONL and ingest the same records in SQLite or via HTTP."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    grouped: dict[str, list[dict]] = {}
    for event in events:
        grouped.setdefault(event["session_id"], []).append(event)
    for session_events in grouped.values():
        first = session_events[0]
        logger = TelemetryLogger(first["player_id"], first["session_id"], path=path,
                                 url=SERVER if send_http else None, batch_size=1000)
        for event in session_events:
            logger.log(event["event_type"], event["level"], ts=event["ts"],
                       **{k: v for k, v in event.items() if k not in
                          {"session_id", "player_id", "event_type", "level", "ts"}})
        logger.flush()
    if not send_http:
        from server.app import replace_events

        replace_events(events)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Генерация демонстрационной телеметрии")
    parser.add_argument("--simulate", type=int, default=40, metavar="N")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--http", action="store_true", help="Отправить на запущенный FastAPI")
    args = parser.parse_args()
    generated = generate_sessions(args.simulate, args.seed)
    write_demo(generated, send_http=args.http)
    print(f"Сгенерировано {args.simulate} сессий и {len(generated)} событий")
