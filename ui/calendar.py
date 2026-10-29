"""시험 기간 주간 시간표(HTML) 컴포넌트 — 학생·교수·강의실 화면이 함께 쓴다."""
from __future__ import annotations

import html

import streamlit as st

from core.settings import Settings
from core.timeutil import min_to_hm

CAL_CSS = """
<style>
.sg-cal .bg { position:absolute; left:2px; right:2px; border-radius:6px; font-size:.66rem; line-height:1;
              display:flex; align-items:center; justify-content:center; color:#3A4256; cursor:default; }
.sg-cal .bg.ok { background:#E3F6EE; color:#087F5B; }
.sg-cal .bg.burden { background:#FFF1DC; color:#B35C00; }
.sg-cal .bg.blocked { background:#F3F4F7; color:#9AA1B2; }
.sg-cal .bg.heavy { background:#FBE4E4; color:#C92A2A; }
.sg-cal .ev.expected { background:#F1F7FF; color:#1C2E5A; border:1.5px dashed #74A0E8; box-shadow:none; }
.sg-cal .ev.mine { background:#E9ECF2; color:#3A4256; box-shadow:none; border:1px solid #D8DDE8; }
.sg-cal .ev.general { background:#F4F4F6; color:#5C6270; box-shadow:none; border:1px solid #DDDFE5; }
.sg-cal .ev.current { background:#1C2E5A; outline:3px solid rgba(59,91,219,.35); }
.sg-cal .ev.dept { color:white; }
.sg-cal .ev { z-index:2; }
</style>
"""


def inject():
    st.markdown(CAL_CSS, unsafe_allow_html=True)


def week_grid(settings: Settings, events: list[dict], backgrounds: list[dict] | None = None,
              px_per_min: float = 1.1, min_event_px: int = 26) -> str:
    """events: {day, start, end, cls, title, sub, color?, tip?}
    backgrounds: {day, start, end, cls, label, tip}  (시험 가능 시간 등 배경 칸)"""
    backgrounds = backgrounds or []
    n = settings.n_days
    st_ = min([settings.day_start] + [e["start"] for e in events])
    en_ = max([settings.day_end] + [e["end"] for e in events])
    height = int((en_ - st_) * px_per_min) + 12
    first_hour = (st_ // 60 + (st_ % 60 > 0)) * 60
    ticks = "".join(f"<div class='tick' style='top:{int((m - st_) * px_per_min)}px'>{min_to_hm(m)}</div>"
                    for m in range(first_hour, en_ + 1, 60))
    lines = "".join(f"<div class='line' style='top:{int((m - st_) * px_per_min)}px'></div>"
                    for m in range(first_hour, en_ + 1, 60))
    cols = []
    for d in range(n):
        parts = [lines]
        for b in backgrounds:
            if b["day"] != d:
                continue
            top = int((b["start"] - st_) * px_per_min) + 1
            h = max(int((b["end"] - b["start"]) * px_per_min) - 2, 6)
            parts.append(f"<div class='bg {b.get('cls', '')}' style='top:{top}px;height:{h}px' "
                         f"title='{html.escape(b.get('tip', ''), quote=True)}'>{html.escape(b.get('label', ''))}</div>")
        for e in events:
            if e["day"] != d:
                continue
            top = int((e["start"] - st_) * px_per_min)
            h = max(int((e["end"] - e["start"]) * px_per_min) - 3, min_event_px)
            style = f"top:{top}px;height:{h}px"
            if e.get("color"):
                style += f";background:{e['color']}"
            parts.append(f"<div class='ev {e.get('cls', '')}' style='{style}' "
                         f"title='{html.escape(e.get('tip', e.get('title', '')), quote=True)}'>"
                         f"<b>{html.escape(e['title'])}</b>{html.escape(e.get('sub', ''))}</div>")
        cols.append(f"<div class='col' style='height:{height}px'>{''.join(parts)}</div>")
    head = "<div class='hd'></div>" + "".join(
        f"<div class='hd'>{settings.day_name(d)}<small>{settings.date_of(d).month}/{settings.date_of(d).day}</small></div>"
        for d in range(n))
    return (f"<div class='sg-cal' style='grid-template-columns: 54px repeat({n}, minmax(0, 1fr))'>{head}"
            f"<div class='times' style='height:{height}px'>{ticks}</div>{''.join(cols)}</div>")


def legend(items: list[tuple[str, str]]) -> str:
    """items: [(css 스타일, 라벨)]"""
    return "<div class='sg-legend' style='margin:4px 0 10px'>" + "".join(
        f"<span><i style='{style}'></i>{html.escape(label)}</span>" for style, label in items) + "</div>"
