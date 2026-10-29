"""교수용 시험 일정 보드 — 시험 블록을 끌어다 빈 시간에 놓고, 같은 위젯 안에서 강의실까지 고른다.

Streamlit 커스텀 컴포넌트 v2(st.components.v2.component)로 만든 양방향 위젯.
- 배경 칸(30분) = 그 시간에 다른 시험·수업이 있는 이 과목 수강생 수 (0명이면 초록)
- 시험 블록을 끌면 놓을 위치에 시험 시간 전체가 미리 보인다: 초록 = 놓을 수 있음, 빨강 = 불가(이유 표시)
- 놓거나 칸을 클릭 → 아래 패널에서 빈 강의실 선택 → '옮기기'. 시각은 두고 강의실만 바꿀 수도 있다.
- 결과는 trigger 값 'move' = {day, start, room} 으로 파이썬에 돌아온다.
"""
from __future__ import annotations

import streamlit as st

CSS = """
.eb, .eb * { box-sizing: border-box; }
.eb { font-family: inherit; color: #171C2B; }
.eb-grid { display: grid; border: 1px solid #E4E8F1; border-radius: 16px; background: #fff; overflow: hidden; }
.eb-hd { text-align: center; padding: 10px 0; font-weight: 700; font-size: .9rem; border-bottom: 1px solid #E4E8F1; background: #FAFBFE; }
.eb-hd small { display: block; color: #6B7385; font-weight: 500; font-size: .75rem; }
.eb-times { position: relative; }
.eb-tick { position: absolute; right: 6px; font-size: .7rem; color: #6B7385; transform: translateY(-50%); }
.eb-col { position: relative; border-left: 1px solid #E4E8F1; }
.eb-line { position: absolute; left: 0; right: 0; border-top: 1px dashed #EEF0F5; }
.eb-cell { position: absolute; left: 2px; right: 2px; border-radius: 5px; font-size: .66rem; display: flex;
           align-items: center; justify-content: center; user-select: none; }
.eb-cell.free { background: #E3F6EE; color: #087F5B; }
.eb-cell.busy { background: #FBE4E4; color: #C92A2A; }
.eb-cell.prof { background: #F3F4F7; color: #9AA1B2; }
.eb.movable .eb-cell { cursor: pointer; }
.eb-ev { position: absolute; left: 5px; right: 5px; border-radius: 9px; padding: 4px 7px; font-size: .72rem; line-height: 1.25;
         overflow: hidden; z-index: 2; background: #E9ECF2; color: #3A4256; border: 1px solid #D8DDE8; pointer-events: none; }
.eb-ev b { display: block; font-size: .76rem; }
.eb-ev.other { background: #5C6B8A; color: #fff; border: none; }
.eb-exam { position: absolute; left: 4px; right: 4px; border-radius: 9px; padding: 4px 8px; font-size: .74rem; line-height: 1.25;
           overflow: hidden; z-index: 3; background: #1C2E5A; color: #fff; box-shadow: 0 4px 12px rgba(28,46,90,.28); }
.eb-exam b { display: block; font-size: .8rem; }
.eb-exam.movable { cursor: grab; }
.eb-exam.movable:active { cursor: grabbing; }
.eb-exam .grip { float: right; opacity: .8; }
.eb.dragging .eb-exam { opacity: .45; }
.eb-prev { position: absolute; left: 3px; right: 3px; border-radius: 9px; z-index: 4; pointer-events: none;
           padding: 4px 7px; font-size: .72rem; font-weight: 700; line-height: 1.25; }
.eb-prev.good { border: 2.5px solid #0CA678; background: rgba(12,166,120,.16); color: #087F5B; }
.eb-prev.bad { border: 2.5px solid #E03131; background: rgba(224,49,49,.14); color: #C92A2A; }
.eb-prev.pick { border: 2.5px dashed #3B5BDB; background: rgba(59,91,219,.12); color: #1C2E5A; }
.eb-panel { margin-top: 12px; border: 1px solid #C5D0F5; background: #F6F8FF; border-radius: 14px; padding: 14px 16px; }
.eb-panel.err { border-color: #F3B4B4; background: #FFF5F5; }
.eb-panel h4 { margin: 0 0 4px 0; font-size: 1rem; }
.eb-panel .muted { color: #6B7385; font-size: .82rem; margin-bottom: 10px; }
.eb-rooms { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 8px; margin: 8px 0 12px; }
.eb-room { border: 1.5px solid #E4E8F1; background: #fff; border-radius: 12px; padding: 9px 11px; cursor: pointer; font-size: .82rem; }
.eb-room b { display: block; font-size: .9rem; }
.eb-room .seat { color: #6B7385; }
.eb-room .fit { color: #087F5B; font-weight: 700; }
.eb-room.sel { border-color: #1C2E5A; box-shadow: 0 0 0 3px rgba(59,91,219,.18); }
.eb-room.cur::after { content: "현재"; float: right; font-size: .7rem; background: #EEF2FF; color: #1C2E5A; padding: 1px 6px; border-radius: 999px; }
.eb-btns { display: flex; gap: 8px; flex-wrap: wrap; }
.eb-btn { border: 1px solid #E4E8F1; background: #fff; border-radius: 10px; padding: 8px 16px; font-weight: 600; cursor: pointer; font-size: .88rem; font-family: inherit; }
.eb-btn.primary { background: #1C2E5A; border-color: #1C2E5A; color: #fff; }
.eb-btn:disabled { opacity: .5; cursor: not-allowed; }
.eb-help { font-size: .82rem; color: #6B7385; margin: 0 0 8px; }
.eb-help b { color: #1C2E5A; }
"""

JS = r"""
export default function(component) {
  const { data, setTriggerValue, parentElement } = component;
  let root = parentElement.querySelector('.eb');
  if (!root) { root = document.createElement('div'); root.className = 'eb'; parentElement.appendChild(root); }
  root.innerHTML = '';
  if (!data) { return; }
  const D = data;
  root.classList.toggle('movable', !!D.movable);
  const ppm = D.ppm;
  const height = Math.round((D.end - D.start) * ppm) + 12;
  const y = (m) => Math.round((m - D.start) * ppm);
  const h = (a, b) => Math.max(Math.round((b - a) * ppm), 18);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const X = D.exam;
  const dur = X.end - X.start;

  const help = document.createElement('p');
  help.className = 'eb-help';
  help.innerHTML = D.movable
    ? '<b>남색 시험 블록을 끌어 옮기세요(칸을 클릭해도 됩니다).</b> 끄는 동안 시험 시간 전체가 초록이면 놓을 수 있고, 빨강이면 그 시간에 다른 시험·수업이 있는 학생이 있어 놓을 수 없습니다.'
    : esc(D.locked_reason || '이 시험은 옮길 수 없습니다.');
  root.appendChild(help);

  const grid = document.createElement('div');
  grid.className = 'eb-grid';
  grid.style.gridTemplateColumns = `54px repeat(${D.days.length}, minmax(0, 1fr))`;
  grid.innerHTML = '<div class="eb-hd"></div>' + D.days.map((d) => `<div class="eb-hd">${esc(d.label)}<small>${esc(d.sub)}</small></div>`).join('');
  const times = document.createElement('div');
  times.className = 'eb-times';
  times.style.height = height + 'px';
  times.innerHTML = D.ticks.map((t) => `<div class="eb-tick" style="top:${y(t.m)}px">${esc(t.label)}</div>`).join('');
  grid.appendChild(times);
  const lines = D.ticks.map((t) => `<div class="eb-line" style="top:${y(t.m)}px"></div>`).join('');
  const cols = [];
  for (let d = 0; d < D.days.length; d++) {
    const col = document.createElement('div');
    col.className = 'eb-col';
    col.style.height = height + 'px';
    col.innerHTML = lines;
    grid.appendChild(col);
    cols.push(col);
  }
  root.appendChild(grid);

  // ---- 시작 시각 판정 ----
  const sid = (day, start) => `${day}-${start}`;
  function verdict(day, start) {
    const id = sid(day, start);
    if (D.slots[id]) return { ok: true, id };
    return { ok: false, id, reason: D.blocked[id] || D.default_block };
  }

  // ---- 미리보기 상자 ----
  const prev = document.createElement('div');
  prev.className = 'eb-prev';
  prev.style.display = 'none';
  function showPreview(day, start, cls, text) {
    if (prev.parentElement !== cols[day]) cols[day].appendChild(prev);
    prev.className = 'eb-prev ' + cls;
    prev.style.top = y(start) + 'px';
    prev.style.height = h(start, start + dur) + 'px';
    prev.textContent = text;
    prev.style.display = 'block';
  }
  const hidePreview = () => { prev.style.display = 'none'; };
  const hm = (m) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

  // ---- 배경 칸: 30분마다 바쁜 학생 수 ----
  for (const c of D.cells) {
    const el = document.createElement('div');
    el.className = 'eb-cell ' + c.cls;
    el.style.top = (y(c.start) + 1) + 'px';
    el.style.height = Math.max(Math.round((c.end - c.start) * ppm) - 2, 6) + 'px';
    el.title = c.tip || '';
    el.textContent = c.label || '';
    if (D.movable) {
      const enter = (ev) => {
        if (ev) ev.preventDefault();
        const v = verdict(c.day, c.start);
        const span = `${hm(c.start)}~${hm(c.start + dur)}`;
        showPreview(c.day, c.start, v.ok ? 'good' : 'bad', v.ok ? `${span} 놓을 수 있음` : `${span} 불가 — ${v.reason}`);
      };
      el.addEventListener('dragover', enter);
      el.addEventListener('dragenter', enter);
      el.addEventListener('mouseenter', () => { if (!root.classList.contains('dragging')) enter(); });
      el.addEventListener('mouseleave', () => { if (!root.classList.contains('dragging')) restorePick(); });
      const pick = (ev) => {
        if (ev) ev.preventDefault();
        root.classList.remove('dragging');
        const v = verdict(c.day, c.start);
        if (v.ok) choose(v.id); else refuse(c.day, c.start, v.reason);
      };
      el.addEventListener('drop', pick);
      el.addEventListener('click', pick);
    }
    cols[c.day].appendChild(el);
  }
  // ---- 고정 일정 (내 수업, 내 다른 시험) ----
  for (const e of D.events) {
    const el = document.createElement('div');
    el.className = 'eb-ev ' + (e.cls || '');
    el.style.top = y(e.start) + 'px';
    el.style.height = h(e.start, e.end) + 'px';
    el.innerHTML = `<b>${esc(e.title)}</b>${esc(e.sub)}`;
    cols[e.day].appendChild(el);
  }
  // ---- 이 과목 시험 블록 ----
  const ex = document.createElement('div');
  ex.className = 'eb-exam' + (D.movable ? ' movable' : '');
  ex.style.top = y(X.start) + 'px';
  ex.style.height = h(X.start, X.end) + 'px';
  ex.innerHTML = `${D.movable ? '<span class="grip">⠿</span>' : ''}<b>${esc(X.title)}</b>${esc(X.sub)}`;
  if (D.movable) {
    ex.draggable = true;
    ex.addEventListener('dragstart', (ev) => {
      ev.dataTransfer.setData('text/plain', 'exam');
      ev.dataTransfer.effectAllowed = 'move';
      setTimeout(() => root.classList.add('dragging'), 0);
    });
    ex.addEventListener('dragend', () => { root.classList.remove('dragging'); restorePick(); });
  }
  cols[X.day].appendChild(ex);

  const panel = document.createElement('div');
  panel.className = 'eb-panel';
  root.appendChild(panel);

  let selected = null, room = null;

  function restorePick() {
    if (selected && selected !== X.slot) {
      const s = D.slots[selected];
      showPreview(s.day, s.start, 'pick', '여기로 옮기기');
    } else { hidePreview(); }
  }

  function refuse(day, start, reason) {
    panel.className = 'eb-panel err';
    panel.innerHTML = `<h4>${esc(D.days[day].label)} ${esc(D.days[day].sub)} ${hm(start)}에는 시작할 수 없습니다</h4>
      <div class="muted">${esc(reason)}</div><div class="eb-btns"><button class="eb-btn back">돌아가기</button></div>`;
    panel.querySelector('.back').addEventListener('click', () => choose(selected || X.slot));
  }

  function choose(slotId) {
    selected = slotId;
    const s = D.slots[slotId];
    const ids = s.rooms.map((r) => r.rid);
    room = ids.includes(X.room) ? X.room : (ids[0] || null);
    restorePick();
    renderPanel();
  }

  function renderPanel() {
    panel.className = 'eb-panel';
    const s = D.slots[selected];
    const same = selected === X.slot;
    const title = same ? `현재 시간 그대로 · ${esc(s.when)}` : `${esc(s.when)}(으)로 옮기기`;
    const roomsHtml = D.room_fixed
      ? `<div class="muted">수업시간 시험은 정규 강의실(${esc(X.room)})에서 봅니다.</div>`
      : `<div class="eb-rooms">` + s.rooms.map((r) => {
          const left = r.exam_cap - D.enrollment;
          return `<div class="eb-room${r.rid === room ? ' sel' : ''}${r.rid === X.room ? ' cur' : ''}" data-rid="${esc(r.rid)}">
                    <b>${esc(r.rid)}</b><span class="seat">좌석 ${r.cap} · 시험 좌석 ${r.exam_cap}</span><br>
                    <span class="fit">수강 ${D.enrollment}명 → 여유 ${left}석</span></div>`;
        }).join('') + `</div>`;
    const canGo = D.room_fixed ? !same : (room && (!same || room !== X.room));
    const label = same ? '강의실만 바꾸기' : '이 시간·강의실로 옮기기';
    panel.innerHTML = `<h4>${title}</h4><div class="muted">${esc(s.info)}${D.room_fixed ? '' : ' · 그 시간에 비어 있고 시험 좌석이 충분한 강의실만 보여 줍니다.'}</div>
      ${roomsHtml}
      <div class="eb-btns"><button class="eb-btn primary" ${canGo ? '' : 'disabled'}>${label}</button>
      ${same ? '' : '<button class="eb-btn cancel">취소</button>'}</div>`;
    panel.querySelectorAll('.eb-room').forEach((el) => el.addEventListener('click', () => { room = el.dataset.rid; renderPanel(); }));
    const go = panel.querySelector('.eb-btn.primary');
    go.addEventListener('click', () => {
      go.disabled = true;
      go.textContent = '다시 배정하는 중…';
      setTriggerValue('move', { day: s.day, start: s.start, room: D.room_fixed ? X.room : room, t: Date.now() });
    });
    const cancel = panel.querySelector('.eb-btn.cancel');
    if (cancel) cancel.addEventListener('click', () => choose(X.slot));
  }

  if (D.movable && D.slots[X.slot]) { choose(X.slot); } else { panel.style.display = 'none'; }
}
"""

_board = st.components.v2.component("siheomgak_exam_board", css=CSS, js=JS)


def exam_board(data: dict, key: str):
    """보드를 그리고, 교수가 옮기기를 누르면 {day, start, room} 을 돌려준다 (그 외에는 None)."""
    res = _board(data=data, key=key, on_move_change=lambda: None)
    return getattr(res, "move", None)
