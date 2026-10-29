"""공통 디자인: 커스텀 CSS 와 카드형 컴포넌트."""
from __future__ import annotations

import html

import streamlit as st

NAVY = "#1C2E5A"
NAVY_2 = "#2D4485"
ACCENT = "#3B5BDB"
BG = "#F5F7FB"
CARD = "#FFFFFF"
BORDER = "#E4E8F1"
MUTED = "#6B7385"
TEXT = "#171C2B"
OK = "#0CA678"
WARN = "#E8590C"
DANGER = "#E03131"

CSS = f"""
<style>
@import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css");

html, body, [class*="css"], .stApp, .stMarkdown, button, input, textarea, select,
[data-testid="stSidebar"], [data-testid="stHeader"] {{
  font-family: "Pretendard Variable", Pretendard, -apple-system, BlinkMacSystemFont, "Apple SD Gothic Neo",
               "Noto Sans KR", "Malgun Gothic", sans-serif !important;
}}
/* 아이콘 폰트는 유지 */
[data-testid="stIconMaterial"], .material-symbols-rounded, span[class*="material"] {{
  font-family: "Material Symbols Rounded" !important;
}}
.stApp {{ background: {BG}; color: {TEXT}; }}
[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1280px; }}
h1, h2, h3, h4 {{ letter-spacing: -0.02em; color: {TEXT}; }}
h1 {{ font-weight: 800; }}
h2, h3 {{ font-weight: 700; }}
[data-testid="stMarkdownContainer"] h3 {{ font-size: 1.35rem; padding-top: .6rem; }}
.stApp [data-testid="stMarkdownContainer"] h4 {{ font-size: 1.08rem !important; font-weight: 700; padding: .1rem 0 .45rem 0; }}
#MainMenu, footer {{ visibility: hidden; }}

/* 사이드바 */
[data-testid="stSidebar"] {{ background: {NAVY}; }}
[data-testid="stSidebar"] * {{ color: #E8ECF7 !important; }}
[data-testid="stSidebarContent"] {{ display: flex; flex-direction: column; }}
[data-testid="stSidebarHeader"] {{ order: -2; }}
[data-testid="stSidebarUserContent"] {{ order: -1; padding-bottom: 1.4rem; }}
[data-testid="stSidebarNav"] {{ order: 0; margin-top: 1rem; }}
[data-testid="stSidebarNavSeparator"] {{ display: none; }}
[data-testid="stSidebarNav"] a {{ border-radius: 10px; margin: 2px 6px; }}
[data-testid="stSidebar"] .sg-side-card {{ background: rgba(255,255,255,.07); border-radius: 12px; padding: 10px 12px;
  font-size: .82rem; line-height: 1.55; margin-top: 6px; }}
[data-testid="stSidebarNav"] a[aria-current="page"] {{ background: rgba(255,255,255,0.14); }}
[data-testid="stSidebarNav"] a:hover {{ background: rgba(255,255,255,0.08); }}

/* 버튼 */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
  border-radius: 10px; font-weight: 600; padding: 0.5rem 1.1rem; border: 1px solid {BORDER};
  transition: all .15s ease;
}}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {{
  background: {NAVY}; border-color: {NAVY}; color: white;
}}
.stButton > button[kind="primary"]:hover {{ background: {NAVY_2}; border-color: {NAVY_2}; }}

/* 입력 */
[data-baseweb="select"] > div, .stTextInput input, .stNumberInput input, .stTextArea textarea, .stDateInput input {{
  border-radius: 10px !important;
}}

/* 테두리 컨테이너를 카드처럼 */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {{
  background: {CARD}; border-radius: 16px; border-color: {BORDER} !important;
  box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 4px 16px rgba(16,24,40,.04);
}}
[data-testid="stExpander"] details {{ background: {CARD}; border-radius: 14px; border-color: {BORDER}; }}
[data-testid="stDataFrame"] {{ border-radius: 12px; overflow: hidden; }}
.stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
.stTabs [data-baseweb="tab"] {{ border-radius: 10px 10px 0 0; padding: 8px 16px; font-weight: 600; }}

/* 커스텀 컴포넌트 */
.sg-hero {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom: 1.2rem; }}
.sg-hero .eyebrow {{ font-size: .82rem; font-weight: 700; color: {ACCENT}; letter-spacing: .04em; }}
.sg-hero h1 {{ margin: .1rem 0 .2rem 0; font-size: 2rem; padding: 0; }}
.sg-hero p {{ color: {MUTED}; margin: 0; font-size: .98rem; }}
.sg-card {{ background:{CARD}; border:1px solid {BORDER}; border-radius:16px; padding:18px 20px;
            box-shadow: 0 1px 2px rgba(16,24,40,.04), 0 4px 16px rgba(16,24,40,.04); }}
.sg-metrics {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 6px 0 14px; }}
.sg-metric {{ background:{CARD}; border:1px solid {BORDER}; border-radius:16px; padding:16px 18px; position:relative; overflow:hidden; }}
.sg-metric .label {{ color:{MUTED}; font-size:.82rem; font-weight:600; }}
.sg-metric .value {{ font-size:1.75rem; font-weight:800; color:{TEXT}; margin-top:4px; letter-spacing:-.02em; }}
.sg-metric .value small {{ font-size: .95rem; font-weight: 600; color:{MUTED}; margin-left: 2px; }}
.sg-metric .sub {{ font-size:.78rem; color:{MUTED}; margin-top:2px; }}
.sg-metric.ok::before, .sg-metric.bad::before, .sg-metric.info::before {{
  content:""; position:absolute; left:0; top:0; bottom:0; width:4px; }}
.sg-metric.ok::before {{ background:{OK}; }}
.sg-metric.bad::before {{ background:{DANGER}; }}
.sg-metric.info::before {{ background:{ACCENT}; }}
.sg-badge {{ display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: .76rem; font-weight: 700;
             background:#EEF2FF; color:{NAVY}; margin-right: 4px; white-space: nowrap; }}
.sg-badge.ok {{ background:#E6F7F1; color:#087F5B; }}
.sg-badge.warn {{ background:#FFF1E6; color:#C2410C; }}
.sg-badge.danger {{ background:#FDECEC; color:#C92A2A; }}
.sg-badge.gray {{ background:#F1F3F7; color:{MUTED}; }}
.sg-mode {{ position: fixed; right: 18px; bottom: 14px; z-index: 1000; background: {CARD}; border:1px solid {BORDER};
            border-radius: 999px; padding: 6px 14px; font-size: .78rem; font-weight: 700; color: {TEXT};
            box-shadow: 0 4px 16px rgba(16,24,40,.08); }}
.sg-mode .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; vertical-align: middle; }}
.sg-reason {{ border-left: 3px solid {ACCENT}; background: #F4F6FE; padding: 10px 14px; border-radius: 0 10px 10px 0;
              margin: 6px 0; font-size: .93rem; line-height: 1.55; }}
.sg-warn {{ border-left: 3px solid {WARN}; background: #FFF6EF; padding: 10px 14px; border-radius: 0 10px 10px 0;
            margin: 6px 0; font-size: .93rem; }}
.sg-muted {{ color:{MUTED}; font-size:.86rem; }}
.sg-kv {{ display:grid; grid-template-columns: 92px 1fr; row-gap: 6px; font-size: .93rem; }}
.sg-kv .k {{ color:{MUTED}; }}
.sg-kv .v {{ font-weight: 600; }}
.sg-big {{ font-size: 1.35rem; font-weight: 800; letter-spacing: -.02em; }}
.sg-notice {{ display:flex; gap:12px; padding:12px 14px; border:1px solid {BORDER}; border-radius:12px; background:{CARD};
              margin-bottom:8px; align-items:flex-start; }}
.sg-notice.unread {{ border-color: #C5D0F5; background: #F6F8FF; }}
.sg-notice .ic {{ font-size: 1.2rem; }}
.sg-notice .t {{ font-weight:600; font-size: .93rem; }}
.sg-notice .m {{ color:{MUTED}; font-size:.78rem; margin-top:2px; }}

/* 주간 캘린더 */
.sg-cal {{ display:grid; grid-template-columns: 54px repeat(5, 1fr); border:1px solid {BORDER}; border-radius:16px;
           background:{CARD}; overflow:hidden; }}
.sg-cal .hd {{ text-align:center; padding:10px 0; font-weight:700; font-size:.9rem; border-bottom:1px solid {BORDER};
               background:#FAFBFE; }}
.sg-cal .hd small {{ display:block; color:{MUTED}; font-weight:500; font-size:.75rem; }}
.sg-cal .col {{ position:relative; border-left:1px solid {BORDER}; }}
.sg-cal .times {{ position:relative; }}
.sg-cal .tick {{ position:absolute; right:6px; font-size:.7rem; color:{MUTED}; transform: translateY(-50%); }}
.sg-cal .line {{ position:absolute; left:0; right:0; border-top:1px dashed #EEF0F5; }}
.sg-cal .ev {{ position:absolute; left:5px; right:5px; border-radius:10px; padding:6px 8px; font-size:.76rem; line-height:1.3;
               overflow:hidden; color:white; box-shadow: 0 2px 6px rgba(16,24,40,.12); }}
.sg-cal .ev b {{ display:block; font-size:.8rem; }}
.sg-cal .ev.exam {{ background:{NAVY}; }}
.sg-cal .ev.tentative {{ background: repeating-linear-gradient(45deg, #EEF2FF, #EEF2FF 6px, #E3E9FC 6px, #E3E9FC 12px);
                         color:{NAVY}; border:1.5px dashed {ACCENT}; box-shadow:none; }}
.sg-cal .ev.class {{ background:#E9ECF2; color:#3A4256; box-shadow:none; border:1px solid #D8DDE8; }}
.sg-legend span {{ display:inline-flex; align-items:center; gap:6px; margin-right:16px; font-size:.82rem; color:{MUTED}; }}
.sg-legend i {{ width:14px; height:14px; border-radius:4px; display:inline-block; }}
</style>
"""


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def hero(eyebrow: str, title: str, desc: str = ""):
    st.markdown(
        f'<div class="sg-hero"><div><div class="eyebrow">{html.escape(eyebrow)}</div>'
        f'<h1>{html.escape(title)}</h1><p>{html.escape(desc)}</p></div></div>',
        unsafe_allow_html=True,
    )


def metric_cards(items: list[dict]):
    """items: [{label, value, unit?, sub?, tone?(ok/bad/info)}]"""
    parts = []
    for it in items:
        unit = f"<small>{html.escape(str(it.get('unit', '')))}</small>" if it.get("unit") else ""
        sub = f'<div class="sub">{it["sub"]}</div>' if it.get("sub") else ""
        parts.append(f'<div class="sg-metric {it.get("tone", "")}"><div class="label">{html.escape(it["label"])}</div>'
                     f'<div class="value">{html.escape(str(it["value"]))}{unit}</div>{sub}</div>')
    st.markdown(f'<div class="sg-metrics">{"".join(parts)}</div>', unsafe_allow_html=True)


def badge(text: str, tone: str = "") -> str:
    return f'<span class="sg-badge {tone}">{html.escape(text)}</span>'


def mode_indicator(label: str, ok: bool):
    color = OK if ok else WARN
    st.markdown(f'<div class="sg-mode"><span class="dot" style="background:{color}"></span>{html.escape(label)}</div>',
                unsafe_allow_html=True)


def reason_box(text: str):
    st.markdown(f'<div class="sg-reason">{text}</div>', unsafe_allow_html=True)


def warn_box(text: str):
    st.markdown(f'<div class="sg-warn">{text}</div>', unsafe_allow_html=True)
