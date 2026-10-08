"""Metric definitions and pipeline checks."""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from analysis.analyze import (completion_rate, conversion_funnel, death_heatmap,
                              load, retention, session_length)
from client.python_logger import TelemetryLogger, generate_sessions, write_demo
from server import app as server


def rows():
    day = 1_780_000_000  # UTC timestamp; use exact day arithmetic below
    day -= day % 86400
    return pd.DataFrame([
        ("s1", "p1", "session_start", day + 100, "L1", None, None),
        ("s1", "p1", "death", day + 110, "L1", 20, 30),
        ("s1", "p1", "checkpoint", day + 130, "L1", 50, 50),
        ("s1", "p1", "level_complete", day + 160, "L1", None, None),
        ("s1", "p1", "session_end", day + 200, "L1", None, None),
        ("s2", "p1", "session_start", day + 86400 + 100, "L1", None, None),
        ("s2", "p1", "session_end", day + 86400 + 140, "L1", None, None),
        ("s3", "p2", "session_start", day + 1000, "L2", None, None),
        ("s3", "p2", "level_complete", day + 1010, "L2", None, None),
        ("s3", "p2", "checkpoint", day + 1020, "L2", 50, 50),
        ("s4", "p2", "session_start", day + 2 * 86400 + 100, "L2", None, None),
        ("s4", "p2", "session_end", day + 2 * 86400 + 170, "L2", None, None),
        ("s5", "p3", "session_end", day + 3000, "L1", None, None),
    ], columns=["session_id", "player_id", "event_type", "ts", "level", "x", "y"])


def test_session_length_uses_start_and_end_only():
    lengths = session_length(rows())
    assert lengths.to_dict() == {"s1": 100.0, "s2": 40.0, "s4": 70.0}
    assert lengths.median() == 70


def test_retention_is_next_calendar_day_not_repeat_count():
    assert retention(rows()) == pytest.approx(1 / 2)
    assert retention(rows()[rows().player_id == "p2"]) == 0


def test_heatmap_by_level_and_empty():
    heatmaps = death_heatmap(rows())
    assert list(heatmaps) == ["L1"]
    assert heatmaps["L1"][0].sum() == 1
    assert death_heatmap(rows().iloc[0:0]) == {}


def test_funnel_requires_order_and_missing_events():
    assert conversion_funnel(rows()) == {"session_start": 4, "checkpoint": 2, "level_complete": 1}
    assert completion_rate(rows()) == 0.25
    empty = rows().iloc[0:0]
    assert conversion_funnel(empty) == {"session_start": 0, "checkpoint": 0, "level_complete": 0}
    assert completion_rate(empty) == retention(empty) == 0
    assert session_length(empty).empty


def test_generator_reproducible_complete_and_multiday():
    events = generate_sessions(40, 42)
    assert events == generate_sessions(40, 42)
    assert events != generate_sessions(40, 43)
    df = pd.DataFrame(events)
    assert df.session_id.nunique() == 40
    assert df.player_id.nunique() > 1
    assert df.level.nunique() > 1
    assert len(pd.to_datetime(df.ts, unit="s", utc=True).dt.date.unique()) > 1
    assert (df.groupby("session_id").event_type.apply(lambda values: {"session_start", "session_end"} <= set(values))).all()
    assert (df.groupby("session_id").ts.apply(lambda values: values.is_monotonic_increasing)).all()


def test_logger_flush_retries_without_duplicate_jsonl(tmp_path, monkeypatch):
    calls = []

    class Response:
        def raise_for_status(self):
            if len(calls) == 1:
                raise RuntimeError("HTTP error")

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return Response()

    monkeypatch.setattr("client.python_logger.requests.post", fake_post)
    path = tmp_path / "events.jsonl"
    logger = TelemetryLogger("p1", "s1", path=path, url="http://example/events")
    logger.log("session_start", "L1", ts=100)
    with pytest.raises(RuntimeError):
        logger.flush()
    assert len(logger.buffer) == 1
    logger.flush()
    assert logger.buffer == []
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_database_api_and_analysis_script(tmp_path, monkeypatch):
    db = tmp_path / "telemetry.db"
    monkeypatch.setattr(server, "DB", db)
    path = tmp_path / "events.jsonl"
    events = generate_sessions(40, 42)
    write_demo(events, path=path)
    assert len([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]) == len(events)
    assert load(db).session_id.nunique() == 40
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(DISTINCT session_id) FROM events").fetchone()[0] >= 20
    with TestClient(server.app) as client:
        valid = events[0]
        assert client.post("/events", json=[valid]).status_code == 202
        assert client.post("/events", json=[valid]).json()["accepted"] == 0
        assert client.post("/events", json=[{"event_type": "bad"}]).status_code == 422
        assert client.post("/events", json=[]).status_code == 400
    script = Path(__file__).resolve().parents[1] / "analysis" / "analyze.py"
    run = subprocess.run([sys.executable, str(script), "--db", str(db)], capture_output=True,
                         text=True, check=True)
    assert "Сессий: 40" in run.stdout


def test_streamlit_app_loads():
    from streamlit.testing.v1 import AppTest

    script = Path(__file__).resolve().parents[1] / "dashboard" / "app.py"
    app = AppTest.from_file(str(script), default_timeout=30).run()
    assert not app.exception
    assert app.title[0].value == "Игровая телеметрия"
    app.selectbox[0].set_value("L1").run()
    assert not app.exception
