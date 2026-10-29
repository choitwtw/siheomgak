"""교수용 시험 일정 보드 — 시험 블록을 끌어다 '가능' 칸에 놓고, 같은 위젯 안에서 강의실까지 고른다.

Streamlit 커스텀 컴포넌트 v2(st.components.v2.component)로 만든 양방향 위젯.
- 끌어다 놓기(드래그 앤 드롭) 또는 칸 클릭으로 시각 선택 → 아래 패널에서 빈 강의실 선택 → '옮기기'
- 시각은 그대로 두고 강의실만 바꿀 수도 있다.
- 결과는 trigger 값 'move' = {day, start, room} 으로 파이썬에 돌아온다.
"""
from __future__ import annotations

import streamlit as st

CSS = """
.eb { font-family: inherit; color: #171C2B; }
.eb-grid { display: grid; border: 1px solid #E4E8F1; border-radius: 16px; background: #fff; overflow: hidden; }
.eb-hd { text-align: center; padding: 10px 0; font-weight: 700; font-size: .9rem; border-bottom: 1px solid #E4E8F1; background: #FAFBFE; }
.eb-hd small { display: block; color: #6B7385; font-weight: 500; font-size: .75rem; }
.eb-times { position: relative; }
.eb-tick { position: absolute; right: 6px; font-size: .7rem; color: #6B7385; transform: translateY(-50%); }
.eb-col { position: relative; border-left: 1px solid #E4E8F1; }
.eb-line { position: absolute; left: 0; right: 0; border-top: 1px dashed #EEF0F5; }
.eb-cell { position: absolute; left: 2px; right: 2px; border-radius: 6px; font-size: .66rem; display: flex;
           align-items: center; justify-content: center; user-select: none; }
.eb-cell.ok { background: #E3F6EE; color: #087F5B; cursor: pointer; }
.eb-cell.burden { background: #FFF1DC; color: #B35C00; cursor: pointer; }
.eb-cell.blocked { background: #F3F4F7; color: #9AA1B2; }
.eb-cell.heavy { background: #FBE4E4; color: #C92A2A; }
.eb-cell.ok:hover, .eb-cell.burden:hover { outline: 2px solid #3B5BDB; }
.eb.dragging .eb-cell.ok, .eb.dragging .eb-cell.burden { outline: 2px dashed #3B5BDB; }
.eb-cell.over { outline: 3px solid #1C2E5A !important; background: #D3E4FF !important; color: #1C2E5A !important; }
.eb-ev { position: absolute; left: 5px; right: 5px; border-radius: 10px; padding: 5px 7px; font-size: .74rem; line-height: 1.3;
         overflow: hidden; z-index: 2; background: #E9ECF2; color: #3A4256; border: 1px solid #D8DDE8; pointer-events: none; }
.eb-ev b { display: block; font-size: .78rem; }
.eb-ev.other { background: #5C6B8A; color: #fff; border: none; }
.eb-exam { position: absolute; left: 4px; right: 4px; border-radius: 10px; padding: 6px 8px; font-size: .76rem; line-height: 1.3;
           overflow: hidden; z-index: 3; background: #1C2E5A; color: #fff; box-shadow: 0 6px 16px rgba(28,46,90,.28); }
.eb-exam b { display: block; font-size: .82rem; }
.eb-exam.movable { cursor: grab; }
.eb-exam.movable:active { cursor: grabbing; }
.eb-exam .grip { float: right; opacity: .8; }
.eb-ghost { position: absolute; left: 4px; right: 4px; border-radius: 10px; z-index: 4; border: 2.5px dashed #3B5BDB;
            background: rgba(59,91,219,.12); pointer-events: none; padding: 5px 7px; font-size: .74rem; color: #1C2E5A; font-weight: 700; }
.eb-panel { margin-top: 12px; border: 1px solid #C5D0F5; background: #F6F8FF; border-radius: 14px; padding: 14px 16px; }
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
  const ppm = D.ppm;
  const height = Math.round((D.end - D.start) * ppm) + 12;
  const y = (m) => Math.round((m - D.start) * ppm);
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  const help = document.createElement('p');
  help.className = 'eb-help';
  help.innerHTML = D.movable
    ? '<b>남색 시험 블록을 끌어서 초록(가능)·주황(△) 칸에 놓거나, 칸을 클릭하세요.</b> 아래에서 강의실을 고른 뒤 옮기기를 누르면 바로 다시 배정합니다.'
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

  let selected = null;   // 고른 slot id
  let room = null;       // 고른 강의실

  // 배경 칸 (시작 가능 여부)
  const cellEls = {};
  for (const c of D.cells) {
    const el = document.createElement('div');
    el.className = 'eb-cell ' + c.cls;
    el.style.top = (y(c.start) + 1) + 'px';
    el.style.height = Math.max(Math.round((c.end - c.start) * ppm) - 2, 6) + 'px';
    el.title = c.tip || '';
    el.textContent = c.label || '';
    if (c.slot && D.movable) {
      el.dataset.slot = c.slot;
      cellEls[c.slot] = el;
      el.addEventListener('click', () => choose(c.slot));
      el.addEventListener('dragover', (ev) => { ev.preventDefault(); el.classList.add('over'); });
      el.addEventListener('dragleave', () => el.classList.remove('over'));
      el.addEventListener('drop', (ev) => { ev.preventDefault(); el.classList.remove('over'); root.classList.remove('dragging'); choose(c.slot); });
    }
    cols[c.day].appendChild(el);
  }
  // 고정 일정 (내 수업, 내 다른 시험)
  for (const e of D.events) {
    const el = document.createElement('div');
    el.className = 'eb-ev ' + (e.cls || '');
    el.style.top = y(e.start) + 'px';
    el.style.height = Math.max(Math.round((e.end - e.start) * ppm) - 3, 24) + 'px';
    el.innerHTML = `<b>${esc(e.title)}</b>${esc(e.sub)}`;
    cols[e.day].appendChild(el);
  }
  // 이 과목 시험 블록 (끌 수 있음)
  const X = D.exam;
  const ex = document.createElement('div');
  ex.className = 'eb-exam' + (D.movable ? ' movable' : '');
  ex.style.top = y(X.start) + 'px';
  ex.style.height = Math.max(Math.round((X.end - X.start) * ppm) - 3, 30) + 'px';
  ex.innerHTML = `${D.movable ? '<span class="grip">⠿</span>' : ''}<b>${esc(X.title)}</b>${esc(X.sub)}`;
  if (D.movable) {
    ex.draggable = true;
    ex.addEventListener('dragstart', (ev) => {
      ev.dataTransfer.setData('text/plain', 'exam');
      ev.dataTransfer.effectAllowed = 'move';
      root.classList.add('dragging');
    });
    ex.addEventListener('dragend', () => root.classList.remove('dragging'));
  }
  cols[X.day].appendChild(ex);

  let ghost = null;
  const panel = document.createElement('div');
  panel.className = 'eb-panel';
  root.appendChild(panel);

  function choose(slotId) {
    selected = slotId;
    const s = D.slots[slotId];
    const ids = s.rooms.map((r) => r.rid);
    room = ids.includes(X.room) ? X.room : (ids[0] || null);
    if (ghost) ghost.remove();
    if (slotId !== X.slot) {
      ghost = document.createElement('div');
      ghost.className = 'eb-ghost';
      ghost.style.top = y(s.start) + 'px';
      ghost.style.height = Math.max(Math.round((s.end - s.start) * ppm) - 3, 30) + 'px';
      ghost.textContent = '여기로 옮기기';
      cols[s.day].appendChild(ghost);
    } else { ghost = null; }
    renderPanel();
  }

  function renderPanel() {
    if (!D.movable) { panel.style.display = 'none'; return; }
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
    panel.innerHTML = `<h4>${title}</h4><div class="muted">${esc(s.info)}${D.room_fixed ? '' : ' · 지금 비어 있고 시험 좌석이 충분한 강의실만 보여 줍니다.'}</div>
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
