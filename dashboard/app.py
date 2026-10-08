"""Readable Russian dashboard backed by the project's SQLite database."""

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analysis.analyze import (  # noqa: E402
    completion_rate, conversion_funnel, death_heatmap, load, retention, session_length,
)

PRIMARY = "#2555C7"
INK = "#17243B"
MUTED = "#52627A"
GRID = "#E5EBF3"

st.set_page_config(page_title="Игровая телеметрия", layout="wide",
                   initial_sidebar_state="collapsed")
st.markdown("""<style>
    :root { --ink: #17243B; --muted: #52627A; --line: #DCE5F0; --surface: #FFFFFF; }
    [data-testid="stAppViewContainer"] { background: #F7F9FC; color: var(--ink); }
    [data-testid="stHeader"] { background: #F7F9FC; }
    .block-container { max-width: 1120px; padding-top: 2.4rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: var(--ink); letter-spacing: -.025em; }
    h1 { margin-top: .15rem; margin-bottom: .2rem; font-size: clamp(2rem, 4vw, 2.8rem); }
    h2 { font-size: 1.35rem; }
    p, label, [data-testid="stCaptionContainer"] p { color: var(--muted); }
    .eyebrow { color: #2555C7; font-size: .78rem; font-weight: 750; letter-spacing: .14em; }
    .metric-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 12px; margin: 1.35rem 0 1.7rem; }
    .metric-card { background: var(--surface); border: 1px solid var(--line); border-radius: 16px; padding: 18px 20px 16px; min-width: 0; box-shadow: 0 3px 18px rgba(23,36,59,.035); }
    .metric-label { display: block; color: var(--muted); font-size: .87rem; line-height: 1.3; margin-bottom: .5rem; }
    .metric-value { display: block; color: var(--ink); font-size: clamp(1.55rem, 2.5vw, 2rem); line-height: 1.1; font-weight: 720; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .metric-note { display: block; color: var(--muted); font-size: .74rem; margin-top: .55rem; }
    [data-testid="stVerticalBlockBorderWrapper"] { background: var(--surface); border-color: var(--line); border-radius: 18px; }
    [data-testid="stSelectbox"] label { font-weight: 650; color: var(--ink); }
    .stButton button { border-radius: 10px; min-height: 42px; }
    .stButton button:focus-visible, [data-testid="stSelectbox"] *:focus-visible { outline: 3px solid #2555C7; outline-offset: 2px; }
    @media (max-width: 640px) {
        .block-container { padding: 1.25rem 1rem 2rem; }
        .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
        .metric-card { padding: 14px; }
        .metric-value { font-size: 1.45rem; }
    }
    @media (max-width: 380px) { .metric-grid { grid-template-columns: 1fr; } }
</style>""", unsafe_allow_html=True)

st.markdown('<div class="eyebrow">АНАЛИТИКА · ЛР № 2</div>', unsafe_allow_html=True)
st.title("Игровая телеметрия")
st.caption("Синтетические игровые сессии · данные напрямую из SQLite")

all_events = load()
levels = sorted(all_events.level.dropna().unique()) if not all_events.empty else []
choice = st.selectbox("Игровой уровень", ["Все уровни", *levels],
                      help="Фильтр пересчитывает все показатели и графики ниже.")
st.button("Обновить данные", help="Перечитать SQLite после отправки новых событий")
df = all_events if choice == "Все уровни" else all_events[all_events.level == choice]

if df.empty:
    st.info("Событий пока нет. Создайте демоданные командой `python -m client.python_logger --simulate 40 --seed 42`.")

lengths = session_length(df)
funnel = conversion_funnel(df)
start_count = funnel["session_start"]
checkpoint_count = funnel["checkpoint"]
finish_count = funnel["level_complete"]


def card(label: str, value: str, note: str) -> str:
    return (f'<div class="metric-card"><span class="metric-label">{label}</span>'
            f'<strong class="metric-value">{value}</strong>'
            f'<span class="metric-note">{note}</span></div>')


cards = [
    card("Сессии", str(df.session_id.nunique() if not df.empty else 0), "уникальных запусков"),
    card("Игроки", str(df.player_id.nunique() if not df.empty else 0), "уникальных ID"),
    card("Медиана сессии", f"{lengths.median() / 60:.1f} мин" if not lengths.empty else "—",
         "только завершённые"),
    card("D1 retention", f"{retention(df):.1%}", "возврат на следующий день"),
    card("Конверсия", f"{completion_rate(df):.1%}", "прошли уровень"),
]
st.markdown('<section class="metric-grid" aria-label="Ключевые показатели">' + "".join(cards) +
            "</section>", unsafe_allow_html=True)

with st.container(border=True):
    st.header("Длительность сессий")
    st.caption("Распределение завершённых сессий по времени. Наведите на столбец для точного числа.")
    if lengths.empty:
        st.info("Нет сессий с началом и окончанием.")
    else:
        durations = pd.DataFrame({"minutes": lengths.to_numpy() / 60})
        chart = (alt.Chart(durations).mark_bar(color=PRIMARY, cornerRadiusTopLeft=3,
                                         cornerRadiusTopRight=3)
                 .encode(x=alt.X("minutes:Q", bin=alt.Bin(maxbins=12),
                                 title="Длительность, мин"),
                         y=alt.Y("count():Q", title="Число сессий"),
                         tooltip=[alt.Tooltip("minutes:Q", bin=alt.Bin(maxbins=12),
                                              title="Интервал, мин"),
                                  alt.Tooltip("count():Q", title="Сессий")])
                 .properties(height=280)
                 .configure_axis(gridColor=GRID, labelColor=MUTED, titleColor=INK,
                                 labelFontSize=12, titleFontSize=12)
                 .configure_view(stroke=None))
        st.altair_chart(chart, use_container_width=True)

with st.container(border=True):
    st.header("Воронка прохождения")
    st.caption("Последовательные этапы в пределах одной сессии и уровня. Проценты — от всех стартов.")
    stages = ["Старт", "Чекпоинт", "Завершение"]
    stage_counts = [start_count, checkpoint_count, finish_count]
    funnel_data = pd.DataFrame({
        "stage": stages,
        "count": stage_counts,
        "share": [count / start_count if start_count else 0 for count in stage_counts],
        "label": [f"{count}  ·  {count / start_count:.1%}" if start_count else "0  ·  0%"
                  for count in stage_counts],
    })
    base = alt.Chart(funnel_data).encode(
        y=alt.Y("stage:N", sort=stages, title=None,
                axis=alt.Axis(labelFontSize=13, labelColor=INK)),
        x=alt.X("count:Q", title="Число сессий",
                scale=alt.Scale(domain=[0, max(stage_counts + [1]) * 1.3])),
        tooltip=[alt.Tooltip("stage:N", title="Этап"),
                 alt.Tooltip("count:Q", title="Сессий"),
                 alt.Tooltip("share:Q", title="От стартов", format=".1%")],
    )
    bars = base.mark_bar(size=32, cornerRadiusEnd=5).encode(
        color=alt.Color("stage:N", scale=alt.Scale(domain=stages,
                        range=["#2555C7", "#4784D8", "#19A48F"]), legend=None))
    labels = base.mark_text(align="left", baseline="middle", dx=8, fontSize=13,
                            fontWeight="bold", color=INK).encode(text="label:N")
    funnel_chart = ((bars + labels).properties(height=215)
                    .configure_axis(gridColor=GRID, labelColor=MUTED, titleColor=INK)
                    .configure_view(stroke=None))
    st.altair_chart(funnel_chart, use_container_width=True)
    if start_count:
        st.caption(f"До чекпоинта дошли {checkpoint_count} из {start_count} сессий; "
                   f"после него уровень завершили {finish_count} из {checkpoint_count}.")

with st.container(border=True):
    st.header("Карта смертей")
    st.caption("Каждая клетка показывает число смертей на участке 10 × 10 игрового поля.")
    maps = death_heatmap(df)
    if not maps:
        st.info("Для выбранного уровня пока нет смертей с координатами.")
    else:
        level = (st.selectbox("Уровень карты", list(maps), key="heatmap_level")
                 if len(maps) > 1 else next(iter(maps)))
        counts, x_edges, y_edges = maps[level]
        cells = pd.DataFrame([
            {"x_start": x_edges[x], "x_end": x_edges[x + 1],
             "y_start": y_edges[y], "y_end": y_edges[y + 1],
             "count": int(counts[x, y]),
             "area": f"X {x_edges[x]:.0f}–{x_edges[x + 1]:.0f}, Y {y_edges[y]:.0f}–{y_edges[y + 1]:.0f}"}
            for x in range(len(x_edges) - 1) for y in range(len(y_edges) - 1)
        ])
        heatmap = (alt.Chart(cells).mark_rect(stroke="#FFFFFF", strokeWidth=1)
                   .encode(x=alt.X("x_start:Q", title="X", scale=alt.Scale(domain=[0, 100])),
                           x2="x_end:Q",
                           y=alt.Y("y_start:Q", title="Y", scale=alt.Scale(domain=[0, 100])),
                           y2="y_end:Q",
                           color=alt.Color("count:Q", title="Смертей", scale=alt.Scale(scheme="blues")),
                           tooltip=[alt.Tooltip("area:N", title="Участок"),
                                    alt.Tooltip("count:Q", title="Смертей")])
                   .properties(height=360)
                   .configure_axis(gridColor=GRID, labelColor=MUTED, titleColor=INK)
                   .configure_view(stroke=None))
        st.altair_chart(heatmap, use_container_width=True)
        st.caption(f"{level}: число событий смерти — {int(counts.sum())}.")
        with st.expander("Точные значения по участкам"):
            st.dataframe(cells.loc[cells["count"] > 0, ["area", "count"]]
                         .rename(columns={"area": "Участок", "count": "Смертей"})
                         .sort_values("Смертей", ascending=False), hide_index=True,
                         use_container_width=True)

st.caption("D1: возврат в следующий календарный день UTC после первого старта игрока. "
           "При выборе уровня все показатели пересчитываются.")
