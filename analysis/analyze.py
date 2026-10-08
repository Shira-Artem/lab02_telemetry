"""Metrics and figures built exclusively from the SQLite event table."""

import argparse
import sqlite3
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "telemetry.db"
RES = ROOT / "results"
COLUMNS = ["session_id", "player_id", "event_type", "ts", "level", "x", "y"]


def load(db: Path = DB) -> pd.DataFrame:
    if not db.exists():
        return pd.DataFrame(columns=COLUMNS)
    with sqlite3.connect(db) as conn:
        return pd.read_sql_query("SELECT session_id, player_id, event_type, ts, level, x, y FROM events", conn)


def session_length(df: pd.DataFrame) -> pd.Series:
    """Seconds from first start to first subsequent end in each complete session."""
    lengths = {}
    if df.empty:
        return pd.Series(dtype=float, name="length_s")
    for session, group in df.groupby("session_id"):
        starts = group.loc[group.event_type == "session_start", "ts"]
        ends = group.loc[group.event_type == "session_end", "ts"]
        if starts.empty or ends.empty:
            continue
        start = starts.min()
        valid_ends = ends[ends >= start]
        if not valid_ends.empty:
            lengths[session] = float(valid_ends.min() - start)
    return pd.Series(lengths, dtype=float, name="length_s")


def retention(df: pd.DataFrame) -> float:
    """Fraction of players active on the UTC day after their first start."""
    if df.empty:
        return 0.0
    starts = df[df.event_type == "session_start"].copy()
    if starts.empty:
        return 0.0
    starts["day"] = pd.to_datetime(starts.ts, unit="s", utc=True).dt.floor("D")
    days = starts.groupby("player_id").day.agg(lambda values: set(values))
    return float(sum(min(player_days) + pd.Timedelta(days=1) in player_days
                     for player_days in days) / len(days))


def death_heatmap(df: pd.DataFrame, bins: int = 10) -> dict[str, tuple]:
    """Level -> (2D counts, x bin edges, y bin edges)."""
    import numpy as np

    if df.empty:
        return {}
    deaths = df[(df.event_type == "death") & df.x.notna() & df.y.notna()]
    return {level: np.histogram2d(group.x, group.y, bins=bins, range=[[0, 100], [0, 100]])
            for level, group in deaths.groupby("level")}


def conversion_funnel(df: pd.DataFrame) -> dict[str, int]:
    """Count sessions reaching each stage in chronological order, per level."""
    result = {"session_start": 0, "checkpoint": 0, "level_complete": 0}
    if df.empty:
        return result
    for _, group in df.groupby(["session_id", "level"]):
        starts = group.loc[group.event_type == "session_start", "ts"]
        if starts.empty:
            continue
        result["session_start"] += 1
        checkpoints = group.loc[(group.event_type == "checkpoint") & (group.ts >= starts.min()), "ts"]
        if checkpoints.empty:
            continue
        result["checkpoint"] += 1
        completed = group.loc[(group.event_type == "level_complete") &
                              (group.ts >= checkpoints.min()), "ts"]
        if not completed.empty:
            result["level_complete"] += 1
    return result


def completion_rate(df: pd.DataFrame) -> float:
    funnel = conversion_funnel(df)
    return funnel["level_complete"] / funnel["session_start"] if funnel["session_start"] else 0.0


def save_figures(df: pd.DataFrame, destination: Path = RES) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    lengths = session_length(df)
    fig, ax = plt.subplots(figsize=(7, 4))
    if not lengths.empty:
        ax.hist(lengths / 60, bins=min(12, max(1, len(lengths))), color="#2463eb", edgecolor="white")
    ax.set(title="Длительность сессий", xlabel="Минуты", ylabel="Сессии")
    fig.tight_layout()
    path = destination / "session_length.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(path)

    for level, (counts, _, _) in death_heatmap(df).items():
        fig, ax = plt.subplots(figsize=(6, 5))
        image = ax.imshow(counts.T, origin="lower", extent=[0, 100, 0, 100], cmap="magma", aspect="auto")
        fig.colorbar(image, ax=ax, label="Смерти")
        ax.set(title=f"Тепловая карта смертей — {level}", xlabel="X", ylabel="Y")
        fig.tight_layout()
        path = destination / f"death_heatmap_{level}.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(path)

    funnel = conversion_funnel(df)
    fig, ax = plt.subplots(figsize=(7, 4))
    labels = ["Старт", "Чекпоинт", "Завершение"]
    counts = list(funnel.values())
    ax.barh(labels[::-1], counts[::-1], color=["#16a394", "#4293c6", "#2463eb"])
    for index, count in enumerate(counts[::-1]):
        share = count / counts[0] if counts[0] else 0
        ax.text(count + 0.2, index, f"{count} · {share:.0%}", va="center")
    ax.set_xlim(0, max(counts + [1]) * 1.35)
    ax.set(title="Последовательная воронка", xlabel="Сессии")
    fig.tight_layout()
    path = destination / "conversion_funnel.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(path)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DB)
    args = parser.parse_args()
    df = load(args.db)
    lengths = session_length(df)
    funnel = conversion_funnel(df)
    print(f"Сессий: {df.session_id.nunique() if not df.empty else 0}; игроков: {df.player_id.nunique() if not df.empty else 0}")
    print(f"Медиана длительности: {lengths.median() if not lengths.empty else 0:.1f} с")
    print(f"D1 retention: {retention(df):.1%}")
    print(f"Воронка: {funnel}; конверсия: {completion_rate(df):.1%}")
    print("Графики:", ", ".join(str(path) for path in save_figures(df)))


if __name__ == "__main__":
    main()
