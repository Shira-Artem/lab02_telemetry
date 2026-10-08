"""Russian Streamlit dashboard backed by SQLite."""

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.analyze import (  # noqa: E402
    completion_rate, conversion_funnel, death_heatmap, load, retention, session_length,
)

st.set_page_config(page_title="Игровая телеметрия", page_icon="🎮", layout="wide")
st.markdown("""<style>
    .block-container {max-width: 1200px; padding-top: 2rem}
    h1 {letter-spacing: -.035em}
    [data-testid="stMetric"] {background: #f2f5fa; padding: 1rem; border-radius: 14px}
</style>""", unsafe_allow_html=True)
st.title("Игровая телеметрия")
st.caption("Лабораторная работа № 2 · данные из SQLite · синтетические игровые сессии")

all_events = load()
levels = sorted(all_events.level.dropna().unique()) if not all_events.empty else []
choice = st.selectbox("Игровой уровень", ["Все уровни", *levels])
df = all_events if choice == "Все уровни" else all_events[all_events.level == choice]

if df.empty:
    st.info("Событий пока нет. Создайте демонстрационные данные командой из README.")

lengths = session_length(df)
columns = st.columns(5)
columns[0].metric("Сессии", df.session_id.nunique() if not df.empty else 0)
columns[1].metric("Игроки", df.player_id.nunique() if not df.empty else 0)
columns[2].metric("Медиана", f"{lengths.median() / 60:.1f} мин" if not lengths.empty else "—")
columns[3].metric("D1 retention", f"{retention(df):.1%}")
columns[4].metric("Конверсия", f"{completion_rate(df):.1%}")

left, right = st.columns(2)
with left:
    st.subheader("Длительность сессий")
    fig, ax = plt.subplots(figsize=(7, 4))
    if not lengths.empty:
        ax.hist(lengths / 60, bins=min(12, len(lengths)), color="#2463eb", edgecolor="white")
    ax.set(xlabel="Минуты", ylabel="Число сессий")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

with right:
    st.subheader("Воронка прохождения")
    funnel = conversion_funnel(df)
    counts = list(funnel.values())
    labels = ["Старт", "Чекпоинт", "Завершение"]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.barh(labels[::-1], counts[::-1], color=["#16a394", "#4293c6", "#2463eb"])
    for index, count in enumerate(counts[::-1]):
        share = count / counts[0] if counts[0] else 0
        ax.text(count + 0.2, index, f"{count} · {share:.0%}", va="center")
    ax.set_xlim(0, max(counts + [1]) * 1.35)
    ax.set_xlabel("Число сессий")
    fig.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

st.subheader("Тепловые карты смертей")
maps = death_heatmap(df)
if not maps:
    st.caption("На выбранном уровне смертей не зафиксировано.")
else:
    for level, (counts, _, _) in maps.items():
        fig, ax = plt.subplots(figsize=(7, 4))
        image = ax.imshow(counts.T, origin="lower", extent=[0, 100, 0, 100],
                          aspect="auto", cmap="magma")
        fig.colorbar(image, ax=ax, label="Число смертей")
        ax.set(title=level, xlabel="X", ylabel="Y")
        fig.tight_layout()
        st.pyplot(fig)
        plt.close(fig)

st.caption("D1 считается по UTC-дням первого запуска игрока. При фильтрации метрики пересчитываются по выбранному уровню.")
