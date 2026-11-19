'use strict';
// VoiceClone Studio — renderer. Vanilla JS, no deps. All server text goes through textContent (h()).
const API = (window.vc && window.vc.engineUrl) || location.origin;
window.__errors = [];
window.addEventListener('error', e => window.__errors.push(String(e.message)));
window.addEventListener('unhandledrejection', e => window.__errors.push('rej: ' + (e.reason && e.reason.message || JSON.stringify(e.reason))));

/* ---------- helpers ---------- */
const $ = (s, r = document) => r.querySelector(s);
const sleep = ms => new Promise(r => setTimeout(r, ms));
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const k in props || {}) {
    const v = props[k];
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') e[k] = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const c of kids.flat(Infinity)) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
  return e;
}
const P = {
  voices: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
  speech: '<path d="M4 10v4M8 6v12M12 3v18M16 8v8M20 11v2"/>',
  dub: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  book: '<path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2z"/><path d="M4 21V5"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  gear: '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  play: '<path d="M7 4l13 8-13 8z"/>', stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
  dl: '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>', trash: '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  up: '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>', plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5"/>', check: '<path d="M5 12l5 5 9-10"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>', back: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  wand: '<path d="M4 20L15 9M14 4l1 2 2 1-2 1-1 2-1-2-2-1 2-1zM19 12l.7 1.3L21 14l-1.3.7L19 16l-.7-1.3L17 14l1.3-.7z"/>',
  hash: '<path d="M5 9h14M5 15h14M10 4L8 20M16 4l-2 16"/>', pause: '<path d="M8 5v14M16 5v14"/>',
  folder: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  wave: '<path d="M3 12h2l2-6 4 12 3-9 2 3h5"/>', edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/>',
};
const icon = (n, size) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('class', 'ic'); s.setAttribute('aria-hidden', 'true'); if (size) { s.style.width = s.style.height = size + 'px'; } s.innerHTML = P[n] || ''; return s; }; // P is a static, trusted table
const btn = (label, o = {}) => h('button', { class: 'btn ' + (o.cls || ''), type: 'button', 'aria-label': o.aria || label || null, title: o.title || null, onclick: o.onclick, disabled: o.disabled }, o.icon ? icon(o.icon) : null, label);
const initials = n => (String(n || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('') || '?').toUpperCase();
const fmtT = s => { s = Math.max(0, +s || 0); const m = Math.floor(s / 60); return m + ':' + (s % 60).toFixed(1).padStart(4, '0'); };
const fmtDur = s => { s = Math.round(+s || 0); const m = Math.floor(s / 60); return m + ':' + String(s % 60).padStart(2, '0'); };
const fmtSize = mb => mb >= 1024 ? (mb / 1024).toFixed(1) + ' GB' : Math.round(mb) + ' MB';
const fmtDate = v => { const d = new Date(typeof v === 'number' && v < 1e12 ? v * 1000 : v); return isNaN(d) ? '' : d.toLocaleString('vi-VN'); };
const firstArray = (o, ...keys) => { if (Array.isArray(o)) return o; for (const k of keys) if (o && Array.isArray(o[k])) return o[k]; for (const k in o || {}) if (Array.isArray(o[k])) return o[k]; return []; };

function toast(msg, type) {
  const t = h('div', { class: 'toast ' + (type || ''), role: 'status' }, msg);
  $('#toasts').append(t); setTimeout(() => t.remove(), 4500);
}
function modal(title, bodyNodes, actions, onclose) {
  const bg = h('div', { class: 'modal-bg', onmousedown: e => { if (e.target === bg) close(); } });
  const close = () => { bg.remove(); document.removeEventListener('keydown', esc); if (onclose) onclose(); };
  const esc = e => { if (e.key === 'Escape') close(); };
  document.addEventListener('keydown', esc);
  bg.append(h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title }, h('h2', null, title), bodyNodes, h('div', { class: 'row' }, actions(close))));
  $('#modal-root').append(bg);
  const f = bg.querySelector('input,button'); if (f) f.focus();
  return close;
}
const confirmBox = (title, msg) => new Promise(res => {
  let done = false; const fin = v => { if (!done) { done = true; res(v); } };
  modal(title, h('p', null, msg), close => [btn('Hủy', { onclick: close }), btn('Xóa', { cls: 'danger', onclick: () => { fin(true); close(); } })], () => fin(false));
});

/* ---------- api + jobs ---------- */
async function api(path, o = {}) {
  const init = { method: o.method || 'GET', headers: {} };
  if (o.json !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(o.json); }
  if (o.form) init.body = o.form;
  let r;
  try { r = await fetch(API + path, init); } catch (e) { refreshHealth(); throw { error: 'network', message: 'Không kết nối được engine' }; }
  if (!r.ok) {
    let b = {}; try { b = await r.json(); } catch (e) { /* non-json */ }
    const err = { status: r.status, error: b.error || 'http_' + r.status, message: b.message || 'Lỗi ' + r.status };
    if (r.status === 402) openPaywall();
    throw err;
  }
  if (o.raw) return r;
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r;
}
function progressBox() {
  const fill = h('i'), msg = h('div', { class: 'pmsg' });
  const el = h('div', { class: 'progress', role: 'status' }, h('div', { class: 'bar' }, fill), msg);
  el.set = (p, m) => { const n = Math.round((p || 0) * 100); fill.style.width = n + '%'; msg.textContent = n + '% · ' + (m || ''); };
  el.set(0, 'Đang chờ…');
  return el;
}
async function runJob(path, opts, prog) {
  const { job_id } = await api(path, opts);
  for (;;) {
    const j = await api('/jobs/' + job_id);
    if (prog) prog.set(j.progress, j.message);
    if (j.status === 'done') return j.result;
    if (j.status === 'error') {
      const e = j.error || {}; const err = { error: e.error || 'job_error', message: e.message || 'Tác vụ thất bại' };
      if (err.error === 'license_required' || err.error === 'feature_not_licensed') { err.status = 402; openPaywall(); }
      throw err;
    }
    await sleep(700);
  }
}
// Runs fn with the button disabled; shows an error toast (paywall errors already show their modal).
async function busy(b, fn) {
  b.disabled = true;
  try { return await fn(); } catch (e) { if (!e || e.status !== 402) toast((e && e.message) || String(e), 'err'); } finally { b.disabled = false; }
}
function withProgress(host, fn) { const p = progressBox(); host.append(p); return fn(p).finally(() => p.remove()); }

/* ---------- state ---------- */
const S = { health: null, voices: [], langs: null, settings: null, speechText: '', speechVoice: null, speechLang: '', dub: null, abScript: '', abVoice: null, setSec: 'general', voiceSel: null, voiceTab: 'clone', tUrls: {} };
async function loadVoices() { try { S.voices = (await api('/voices')).voices || []; } catch (e) { /* toast already via caller */ } return S.voices; }
async function loadLangs() {
  if (!S.langs) { try { S.langs = await api('/languages'); } catch (e) { S.langs = { tts: [{ code: 'vi', name: 'Tiếng Việt' }, { code: 'en', name: 'English' }], translation: [] }; } }
  return S.langs;
}
const voiceName = id => (S.voices.find(v => v.id === id) || {}).name || id;
function langSelect(list, value, extra) {
  const s = h('select', { 'aria-label': 'Ngôn ngữ' });
  if (extra) s.append(h('option', { value: extra[0] }, extra[1]));
  for (const l of list || []) s.append(h('option', { value: l.code, selected: l.code === value }, l.name));
  if (value != null) s.value = value;
  return s;
}
function voiceSelect(value, extra) {
  const s = h('select', { 'aria-label': 'Chọn giọng' });
  if (extra) s.append(h('option', { value: extra[0] }, extra[1]));
  for (const v of S.voices) s.append(h('option', { value: v.id }, v.name));
  if (value != null) s.value = value;
  return s;
}
function field(label, ctl) { const id = 'f' + Math.random().toString(36).slice(2, 8); ctl.id = id; return h('div', { class: 'field' }, h('label', { for: id }, label), ctl); }
function dropzone(label, accept, onFile) {
  const input = h('input', { type: 'file', accept, hidden: true, 'aria-label': label });
  const name = h('span', null, label);
  const el = h('div', { class: 'drop', role: 'button', tabindex: '0', 'aria-label': label }, icon('up', 24), name, input);
  const pick = f => { if (!f) return; name.replaceChildren(h('b', null, f.name)); onFile(f); };
  el.addEventListener('click', () => input.click());
  el.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); input.click(); } });
  input.addEventListener('change', () => pick(input.files[0]));
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('over'); });
  el.addEventListener('dragleave', () => el.classList.remove('over'));
  el.addEventListener('drop', e => { e.preventDefault(); el.classList.remove('over'); pick(e.dataTransfer.files[0]); });
  return el;
}
// Mic recorder widget. onFile(File) is called when a recording is stopped.
function recorder(onFile) {
  let mr = null, chunks = [], t0 = 0, timer = null, stream = null;
  const mic = h('select', { 'aria-label': 'Chọn micro' }, h('option', { value: '' }, 'Micro mặc định'));
  const time = h('span', { class: 'tm' }, '0:00');
  const prev = h('audio', { controls: true, hidden: true });
  const status = h('span', { class: 'muted small' });
  const rb = h('button', { class: 'recbtn', type: 'button', 'aria-label': 'Ghi âm', title: 'Ghi âm' }, icon('mic', 24));
  async function listMics() {
    try { const ds = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audioinput'); const cur = mic.value; mic.replaceChildren(h('option', { value: '' }, 'Micro mặc định'), ds.map(d => h('option', { value: d.deviceId }, d.label || 'Micro ' + d.deviceId.slice(0, 4)))); mic.value = cur; } catch (e) { /* no devices api */ }
  }
  async function start() {
    if (!navigator.mediaDevices || !window.MediaRecorder) { toast('Máy này không hỗ trợ ghi âm', 'err'); return; }
    try { stream = await navigator.mediaDevices.getUserMedia({ audio: mic.value ? { deviceId: { exact: mic.value } } : true }); }
    catch (e) { toast('Không mở được micro: ' + (e.message || e.name), 'err'); return; }
    listMics(); chunks = []; mr = new MediaRecorder(stream);
    mr.ondataavailable = e => e.data.size && chunks.push(e.data);
    mr.onstop = () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(chunks, { type: 'audio/webm' });
      prev.src = URL.createObjectURL(blob); prev.hidden = false;
      onFile(new File([blob], 'ghi-am-' + Date.now() + '.webm', { type: 'audio/webm' }));
    };
    mr.start(); t0 = Date.now(); rb.classList.add('rec'); rb.replaceChildren(icon('stop', 24)); rb.setAttribute('aria-label', 'Dừng ghi'); status.textContent = 'Đang ghi…';
    timer = setInterval(() => { time.textContent = fmtDur((Date.now() - t0) / 1000); }, 250);
  }
  function stop() { clearInterval(timer); if (mr && mr.state !== 'inactive') mr.stop(); rb.classList.remove('rec'); rb.replaceChildren(icon('mic', 24)); rb.setAttribute('aria-label', 'Ghi âm'); status.textContent = 'Đã ghi xong'; }
  rb.addEventListener('click', () => (mr && mr.state === 'recording') ? stop() : start());
  listMics();
  return h('div', { class: 'card', style: 'display:flex;flex-direction:column;align-items:center;gap:10px' }, rb, h('div', { class: 'row' }, time, status), h('div', { style: 'width:100%' }, field('Thiết bị thu', mic)), prev);
}

/* ---------- paywall / health ---------- */
let paywallOpen = false;
function openPaywall() {
  if (paywallOpen) return; paywallOpen = true;
  const key = h('input', { type: 'text', placeholder: 'Dán license key', 'aria-label': 'License key', autocomplete: 'off' });
  modal('Cần license để dùng tính năng này', [h('p', null, 'Nhập license key để mở khóa. Sau khi kích hoạt, hãy thử lại thao tác của bạn.'), key], close => [
    btn('Để sau', { onclick: close }),
    btn('Kích hoạt', { cls: 'primary', onclick: async ev => {
      await busy(ev.currentTarget, async () => { await api('/license', { method: 'POST', json: { key: key.value.trim() } }); toast('Đã kích hoạt license', 'ok'); close(); refreshHealth(); });
    } })], () => { paywallOpen = false; });
}
let failCount = 0;
async function refreshHealth() {
  const dot = $('#dot');
  try {
    const hh = await api('/health'); S.health = hh; failCount = 0; $('#offline').hidden = true;
    if (dot) { dot.className = 'dot ' + (hh.device === 'cuda' ? 'ok' : 'cpu'); dot.title = 'Engine ' + hh.status + ' · ' + hh.device + (hh.gpu ? ' · ' + hh.gpu.name + ' (' + hh.gpu.free_mb + '/' + hh.gpu.total_mb + ' MB trống)' : '') + (hh.warning ? ' · ' + hh.warning : ''); dot.setAttribute('aria-label', dot.title); }
    const b = $('#banner');
    if (!hh.models_ready) { b.hidden = false; b.replaceChildren('Chưa tải đủ model giọng nói. ', h('a', { href: '#/settings', onclick: () => { S.setSec = 'models'; } }, 'Mở Cài đặt → Model')); }
    else if (hh.warning) { b.hidden = false; b.textContent = hh.warning; } else b.hidden = true;
    renderTopRight();
  } catch (e) {
    failCount++; if (dot) { dot.className = 'dot'; dot.title = 'Engine không phản hồi'; }
    if (failCount >= 1) $('#offline').hidden = false;
  }
}
function renderTopRight() {
  const hh = S.health; if (!hh) return;
  $('#topright').replaceChildren(
    h('span', { class: 'chip-top', title: 'Thiết bị tính toán' }, hh.device === 'cuda' ? 'GPU' : 'CPU'),
    h('button', { class: 'chip-top', type: 'button', onclick: () => { S.setSec = 'license'; location.hash = '#/settings'; } }, hh.licensed ? 'Đã có license' : 'Chưa có license'));
}

/* ---------- router ---------- */
const PAGES = {};
const NAV = [['voices', 'Giọng nói', 'voices'], ['speech', 'Đọc văn bản', 'speech'], ['dub', 'Lồng tiếng', 'dub'], ['audiobook', 'Sách nói', 'book'], ['transcribe', 'Chép lời', 'mic']];
function buildRail() {
  const r = $('#rail');
  r.append(h('div', { class: 'logo', 'aria-hidden': 'true' }, icon('wave', 20)));
  for (const [k, label, ic] of NAV) r.append(h('a', { href: '#/' + k, 'data-k': k, title: label, 'aria-label': label }, icon(ic, 22)));
  r.append(h('div', { class: 'sp' }), h('div', { id: 'dot', class: 'dot', role: 'img', 'aria-label': 'Trạng thái engine' }),
    h('a', { href: '#/settings', 'data-k': 'settings', title: 'Cài đặt', 'aria-label': 'Cài đặt' }, icon('gear', 22)));
}
function route() {
  const k = (location.hash.match(/^#\/(\w+)/) || [])[1];
  const key = PAGES[k] ? k : 'speech';
  const pg = PAGES[key];
  document.querySelectorAll('#rail a').forEach(a => { const on = a.dataset.k === key; a.classList.toggle('on', on); on ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current'); });
  $('#title').textContent = pg.title; document.title = pg.title + ' — VoiceClone Studio';
  const panel = h('aside', { id: 'panel', class: 'panel', 'aria-label': 'Bảng bên' }), main = h('main', { id: 'main', class: 'main' });
  $('#panel').replaceWith(panel); $('#main').replaceWith(main);
  pg.mount(panel, main);
}

/* ================= Giọng nói ================= */
const GROUPS = [
  { key: 'gender', label: 'Giới tính', o: [['male', 'Nam'], ['female', 'Nữ']] },
  { key: 'age', label: 'Độ tuổi', o: [['child', 'Trẻ em'], ['teenager', 'Thiếu niên'], ['young adult', 'Thanh niên'], ['middle-aged', 'Trung niên'], ['elderly', 'Cao tuổi']] },
  { key: 'pitch', label: 'Cao độ', o: [['very low pitch', 'Rất trầm'], ['low pitch', 'Trầm'], ['moderate pitch', 'Vừa'], ['high pitch', 'Cao'], ['very high pitch', 'Rất cao']] },
  { key: 'style', label: 'Phong cách', o: [['whisper', 'Thì thầm']] },
  { key: 'accent', label: 'Giọng vùng', o: [['american accent', 'Mỹ'], ['australian accent', 'Úc'], ['british accent', 'Anh'], ['canadian accent', 'Canada'], ['chinese accent', 'Trung Quốc'], ['indian accent', 'Ấn Độ'], ['japanese accent', 'Nhật'], ['korean accent', 'Hàn'], ['portuguese accent', 'Bồ Đào Nha'], ['russian accent', 'Nga']] },
];
const PRESETS = [
  ['Người dẫn chuyện', ['male', 'middle-aged', 'low pitch']], ['Phát thanh viên', ['female', 'young adult', 'moderate pitch']],
  ['Kể chuyện', ['male', 'elderly', 'low pitch']], ['Trẻ em', ['child', 'high pitch']], ['Thì thầm', ['female', 'whisper']],
];
const DESIGN_SAMPLE = 'Xin chào, rất vui được gặp bạn. Đây là giọng nói tôi vừa được thiết kế, bạn thấy thế nào?';

PAGES.voices = {
  title: 'Giọng nói',
  mount(panel, main) {
    let filter = 'all', q = '';
    const list = h('div', { style: 'display:flex;flex-direction:column;gap:2px' });
    const search = h('input', { type: 'text', placeholder: 'Tìm giọng…', 'aria-label': 'Tìm giọng', oninput: e => { q = e.target.value.toLowerCase(); drawList(); } });
    const chips = h('div', { class: 'chips' }, [['all', 'Tất cả'], ['clone', 'Clone'], ['design', 'Thiết kế']].map(([k, l]) => h('button', { class: 'chip' + (k === filter ? ' on' : ''), type: 'button', 'data-k': k, onclick: e => { filter = k; chips.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c.dataset.k === k)); drawList(); } }, l)));
    panel.append(search, chips, list);
    function drawList() {
      const vs = S.voices.filter(v => (filter === 'all' || v.kind === filter) && v.name.toLowerCase().includes(q));
      list.replaceChildren(...(vs.length ? vs.map(v => h('button', { class: 'vitem' + (v.id === S.voiceSel ? ' on' : ''), type: 'button', onclick: () => { S.voiceSel = v.id; drawList(); drawMain(); } },
        h('span', { class: 'avatar' }, initials(v.name)), h('span', { class: 'grow' }, h('div', { class: 'nm' }, v.name), h('div', { class: 'muted small' }, (v.language || '') + (v.seconds ? ' · ' + Math.round(v.seconds) + 's' : ''))), h('span', { class: 'badge' }, v.kind === 'design' ? 'Thiết kế' : 'Clone')))
        : [h('div', { class: 'empty' }, S.voices.length ? 'Không có giọng phù hợp' : 'Chưa có giọng nào. Hãy clone hoặc thiết kế giọng đầu tiên.')]));
    }
    async function reload(selectId) { await loadVoices(); if (selectId !== undefined) S.voiceSel = selectId; drawList(); drawMain(); }
    function drawMain() { main.replaceChildren(); const v = S.voices.find(x => x.id === S.voiceSel); if (v) detail(v); else tabsView(); }

    function detail(v) {
      const name = h('input', { type: 'text', value: v.name, 'aria-label': 'Tên giọng' });
      main.append(h('div', { class: 'setcol' },
        btn('Thêm giọng mới', { icon: 'plus', cls: 'sm', onclick: () => { S.voiceSel = null; drawList(); drawMain(); }, aria: 'Thêm giọng mới' }),
        h('div', { class: 'card' },
          h('div', { class: 'row', style: 'margin-bottom:12px' }, h('span', { class: 'avatar' }, initials(v.name)), h('div', { class: 'grow' }, h('h2', { class: 'page-h', style: 'margin:0' }, v.name), h('div', { class: 'muted small' }, (v.kind === 'design' ? 'Giọng thiết kế' : 'Giọng clone') + ' · ' + (v.language || '') + ' · ' + fmtDate(v.created)))),
          h('audio', { controls: true, preload: 'none', src: API + '/voices/' + encodeURIComponent(v.id) + '/sample', 'aria-label': 'Nghe mẫu' }),
          v.instruct ? h('p', { class: 'muted', style: 'margin-top:10px' }, 'Mô tả: ' + v.instruct) : null,
          v.ref_text ? h('p', { class: 'muted', style: 'margin-top:10px' }, 'Lời trong mẫu: ' + v.ref_text) : null,
          h('div', { style: 'margin-top:14px' }, field('Đổi tên', name)),
          h('div', { class: 'row wrap' },
            btn('Lưu tên', { onclick: e => busy(e.currentTarget, async () => { await api('/voices/' + encodeURIComponent(v.id), { method: 'PATCH', json: { name: name.value.trim() } }); toast('Đã đổi tên', 'ok'); await reload(v.id); }) }),
            btn('Dùng giọng này', { cls: 'primary', icon: 'check', onclick: () => { S.speechVoice = v.id; location.hash = '#/speech'; } }),
            h('span', { class: 'grow' }),
            btn('Xóa giọng', { cls: 'danger', icon: 'trash', onclick: async e => { if (!await confirmBox('Xóa giọng này?', 'Giọng "' + v.name + '" sẽ bị xóa vĩnh viễn.')) return; await busy(e.currentTarget, async () => { await api('/voices/' + encodeURIComponent(v.id), { method: 'DELETE' }); toast('Đã xóa giọng', 'ok'); await reload(null); }); } })))));
    }

    function tabsView() {
      const wrap = h('div', { class: 'setcol' }), body = h('div');
      const tabs = h('div', { class: 'tabs', role: 'tablist' }, [['clone', 'Clone giọng'], ['design', 'Thiết kế giọng']].map(([k, l]) => h('button', { type: 'button', role: 'tab', 'data-k': k, class: k === S.voiceTab ? 'on' : '', onclick: () => { S.voiceTab = k; tabs.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.k === k)); show(); } }, l)));
      const show = () => { body.replaceChildren(); (S.voiceTab === 'clone' ? cloneForm : designForm)(body); };
      wrap.append(tabs, body); main.append(wrap); show();
    }

    async function cloneForm(root) {
      const langs = await loadLangs(); let file = null;
      const name = h('input', { type: 'text', placeholder: 'Ví dụ: Giọng của tôi', 'aria-label': 'Tên giọng' });
      const lang = langSelect(langs.tts, '', ['', 'Tự nhận diện']);
      const refText = h('textarea', { rows: '2', 'aria-label': 'Lời trong mẫu', placeholder: 'Để trống để engine tự chép' });
      const save = btn('Lưu giọng', { cls: 'primary', disabled: true });
      const prog = h('div');
      const setFile = f => { file = f; save.disabled = false; };
      save.addEventListener('click', () => {
        if (!name.value.trim()) { toast('Hãy đặt tên cho giọng', 'err'); return; }
        busy(save, async () => {
          const fd = new FormData(); fd.append('name', name.value.trim()); fd.append('audio', file, file.name); if (lang.value) fd.append('language', lang.value); if (refText.value.trim()) fd.append('ref_text', refText.value.trim());
          const v = await api('/voices', { method: 'POST', form: fd }); toast('Đã lưu giọng "' + v.name + '"', 'ok'); await reload(v.id);
        });
      });
      root.append(h('p', { class: 'page-s' }, 'Dùng 5–15 giây giọng nói rõ, ít tạp âm'),
        h('div', { class: 'grid2' }, field('Tên giọng', name), field('Ngôn ngữ trong mẫu', lang)),
        h('div', { class: 'grid2', style: 'margin-bottom:12px' }, dropzone('Kéo thả hoặc bấm để chọn file (wav, mp3, m4a, mp4)', '.wav,.mp3,.m4a,.mp4,.webm,audio/*,video/mp4', setFile), recorder(setFile)),
        field('Lời trong mẫu (để trống: tự chép)', refText), save, prog);
    }

    async function designForm(root) {
      const langs = await loadLangs(); const pick = {}; let designId = null;
      const script = h('textarea', { rows: '3', 'aria-label': 'Lời thoại', value: DESIGN_SAMPLE });
      const lang = langSelect(langs.tts, 'vi');
      const name = h('input', { type: 'text', placeholder: 'Tên giọng', 'aria-label': 'Tên giọng' });
      const player = h('audio', { controls: true, hidden: true });
      const saveB = btn('Lưu thành giọng', { cls: 'primary', disabled: true });
      const preview = btn('Nghe thử', { icon: 'play' });
      const groups = GROUPS.map(g => {
        const row = h('div', { class: 'chips' }, g.o.map(([val, lab]) => h('button', { class: 'chip', type: 'button', 'data-v': val, 'aria-pressed': 'false', onclick: () => { pick[g.key] = pick[g.key] === val ? undefined : val; sync(); } }, lab)));
        return h('div', { class: 'field' }, h('span', { class: 'lbl' }, g.label), row);
      });
      const instruct = () => GROUPS.map(g => pick[g.key]).filter(Boolean).join(', ');
      function sync() { root.querySelectorAll('.chip[data-v]').forEach(c => { const on = Object.values(pick).includes(c.dataset.v); c.classList.toggle('on', on); c.setAttribute('aria-pressed', on); }); designId = null; saveB.disabled = true; }
      const presets = h('div', { class: 'chips' }, PRESETS.map(([l, items]) => h('button', { class: 'chip', type: 'button', onclick: () => { for (const g of GROUPS) pick[g.key] = undefined; for (const it of items) { const g = GROUPS.find(g => g.o.some(o => o[0] === it)); pick[g.key] = it; } sync(); } }, l)));
      preview.addEventListener('click', () => {
        const ins = instruct(); if (!ins) { toast('Hãy chọn ít nhất một đặc điểm giọng', 'err'); return; }
        if (!script.value.trim()) { toast('Hãy nhập lời thoại', 'err'); return; }
        busy(preview, async () => {
          preview.lastChild.textContent = ' Đang tạo…';
          try {
            const r = await api('/design/preview', { method: 'POST', json: { instruct: ins, text: script.value.trim(), language: lang.value }, raw: true });
            designId = r.headers.get('x-design-id'); const blob = await r.blob();
            player.src = URL.createObjectURL(blob); player.hidden = false; player.play().catch(() => {}); saveB.disabled = !designId;
          } finally { preview.lastChild.textContent = 'Nghe thử'; }
        });
      });
      saveB.addEventListener('click', () => {
        if (!name.value.trim()) { toast('Hãy đặt tên cho giọng', 'err'); return; }
        busy(saveB, async () => { const v = await api('/design/save', { method: 'POST', json: { design_id: designId, name: name.value.trim() } }); toast('Đã lưu giọng "' + v.name + '"', 'ok'); await reload(v.id); });
      });
      root.append(h('div', { class: 'field' }, h('span', { class: 'lbl' }, 'Điểm bắt đầu'), presets), ...groups, field('Lời thoại nghe thử', script),
        h('div', { class: 'row wrap', style: 'margin-bottom:12px' }, h('div', { style: 'width:220px' }, field('Ngôn ngữ', lang)), preview), player,
        h('div', { class: 'row', style: 'margin-top:12px;align-items:flex-end' }, h('div', { class: 'grow' }, field('Tên giọng', name)), h('div', { style: 'margin-bottom:10px' }, saveB)));
    }
    loadVoices().then(() => { drawList(); drawMain(); });
  },
};

/* ================= Đọc văn bản ================= */
PAGES.speech = {
  title: 'Đọc văn bản',
  mount(panel, main) {
    main.classList.add('flex');
    const ta = h('textarea', { class: 'editor', placeholder: 'Nhập hoặc dán văn bản cần đọc…', 'aria-label': 'Văn bản cần đọc', value: S.speechText });
    const cnt = h('span', { class: 'muted small' });
    const upd = () => { S.speechText = ta.value; cnt.textContent = ta.value.length + ' ký tự'; }; ta.addEventListener('input', upd); upd();
    const speed = h('input', { type: 'range', min: '0.7', max: '1.4', step: '0.05', value: '1', 'aria-label': 'Tốc độ' });
    const speedL = h('span', { class: 'tm' }, '1.00×'); speed.addEventListener('input', () => { speedL.textContent = (+speed.value).toFixed(2) + '×'; });
    const quality = h('select', { 'aria-label': 'Chất lượng' }, [['fast', 'Nhanh'], ['balanced', 'Cân bằng'], ['quality', 'Chất lượng']].map(([v, l]) => h('option', { value: v }, l)));
    quality.value = (S.settings && S.settings.quality) || 'balanced';
    const voiceSel = voiceSelect(null); const lang = h('select', { 'aria-label': 'Ngôn ngữ' });
    const gen = btn('Tạo giọng đọc', { cls: 'primary', icon: 'play', title: 'Ctrl+Enter' });
    const result = h('div'); const takesBox = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
    panel.append(h('h3', { style: 'font-size:14px' }, 'Bản đã tạo'), takesBox);
    main.append(h('div', { class: 'row' }, h('div', { class: 'grow' }, h('h2', { class: 'page-h' }, 'Đọc văn bản'), h('p', { class: 'muted' }, 'Dán văn bản, chọn giọng rồi bấm Tạo giọng đọc.')), cnt), ta, result,
      h('div', { class: 'bar-bottom' }, h('div', { class: 'field', style: 'width:200px' }, h('label', null, 'Giọng'), voiceSel), h('div', { class: 'field', style: 'width:160px' }, h('label', null, 'Ngôn ngữ'), lang),
        h('div', { class: 'field', style: 'width:190px' }, h('label', null, 'Tốc độ ', speedL), speed), h('div', { class: 'field', style: 'width:140px' }, h('label', null, 'Chất lượng'), quality), h('span', { class: 'grow' }), gen));
    Promise.all([loadVoices(), loadLangs()]).then(([vs, langs]) => {
      voiceSel.replaceChildren(...vs.map(v => h('option', { value: v.id }, v.name)));
      if (!vs.length) voiceSel.append(h('option', { value: '' }, '(chưa có giọng)'));
      voiceSel.value = vs.find(v => v.id === S.speechVoice) ? S.speechVoice : (vs[0] && vs[0].id) || '';
      lang.append(h('option', { value: '' }, 'Tự nhận diện'), ...langs.tts.map(l => h('option', { value: l.code }, l.name))); lang.value = S.speechLang;
    });
    voiceSel.addEventListener('change', () => { S.speechVoice = voiceSel.value; }); lang.addEventListener('change', () => { S.speechLang = lang.value; });
    const player = new Audio(); let playingId = null;
    async function loadTakes() {
      let takes = []; try { takes = (await api('/takes?limit=50')).takes || []; } catch (e) { return; }
      takesBox.replaceChildren(...(takes.length ? takes.map(t => {
        const pb = btn('', { icon: 'play', cls: 'icon sm', aria: 'Phát', onclick: () => { if (playingId === t.id && !player.paused) { player.pause(); return; } player.src = API + '/takes/' + encodeURIComponent(t.id) + '/audio'; playingId = t.id; player.play().catch(() => {}); } });
        return h('div', { class: 'take' }, h('p', null, t.text), h('div', { class: 'muted small' }, (t.voice_name || '') + ' · ' + (+t.seconds || 0).toFixed(1) + 's · ' + fmtDate(t.created)),
          h('div', { class: 'acts' }, pb,
            h('a', { class: 'btn icon sm', href: API + '/takes/' + encodeURIComponent(t.id) + '/audio', download: 'giong-doc-' + t.id + '.wav', 'aria-label': 'Tải xuống', title: 'Tải xuống' }, icon('dl')),
            btn('', { icon: 'copy', cls: 'icon sm', aria: 'Chép văn bản về ô soạn thảo', title: 'Chép văn bản về ô soạn thảo', onclick: () => { ta.value = t.text; upd(); toast('Đã chép văn bản về ô soạn thảo'); } }),
            btn('', { icon: 'trash', cls: 'icon sm danger', aria: 'Xóa bản này', title: 'Xóa', onclick: async () => { if (!await confirmBox('Xóa bản này?', 'Bản đọc sẽ bị xóa vĩnh viễn.')) return; try { await api('/takes/' + encodeURIComponent(t.id), { method: 'DELETE' }); loadTakes(); } catch (e) { toast(e.message, 'err'); } } })));
      }) : [h('div', { class: 'empty small' }, 'Chưa có bản nào')]));
    }
    loadTakes();
    gen.addEventListener('click', () => {
      if (!ta.value.trim()) { toast('Hãy nhập văn bản', 'err'); return; }
      if (!voiceSel.value) { toast('Hãy chọn hoặc tạo một giọng trước (mục Giọng nói)', 'err'); return; }
      busy(gen, async () => {
        gen.lastChild.textContent = ' Đang tạo…';
        try {
          const body = { text: ta.value.trim(), voice: voiceSel.value, speed: +speed.value, quality: quality.value }; if (lang.value) body.language = lang.value;
          const r = await api('/speech', { method: 'POST', json: body, raw: true }); const id = r.headers.get('x-take-id'); const blob = await r.blob(); const url = URL.createObjectURL(blob);
          const au = h('audio', { controls: true, src: url, 'aria-label': 'Kết quả' });
          result.replaceChildren(h('div', { class: 'card' }, au, h('div', { class: 'row', style: 'margin-top:8px' }, h('span', { class: 'muted small grow' }, (+r.headers.get('x-audio-seconds') || 0).toFixed(1) + 's âm thanh · tạo trong ' + (+r.headers.get('x-gen-time') || 0).toFixed(1) + 's'), h('a', { class: 'btn sm', href: url, download: 'giong-doc' + (id ? '-' + id : '') + '.wav' }, icon('dl'), 'Tải xuống'))));
          au.play().catch(() => {}); loadTakes();
        } finally { gen.lastChild.textContent = 'Tạo giọng đọc'; }
      });
    });
    ta.addEventListener('keydown', e => { if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); gen.click(); } });
  },
};

/* ================= Lồng tiếng ================= */
const STRATS = [['smart_fit', 'Vừa khít thông minh'], ['strict_slot', 'Giữ đúng độ dài video'], ['stretch', 'Kéo dài video']];
PAGES.dub = {
  title: 'Lồng tiếng',
  mount(panel, main) {
    let tab = 'new', file = null;
    const tabs = h('div', { class: 'tabs', role: 'tablist' }, [['new', 'Lồng tiếng'], ['projects', 'Dự án']].map(([k, l]) => h('button', { type: 'button', role: 'tab', 'data-k': k, class: k === tab ? 'on' : '', onclick: () => { tab = k; tabs.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.k === k)); drawPanel(); } }, l)));
    const body = h('div', { style: 'display:flex;flex-direction:column;gap:12px' });
    panel.append(tabs, body);
    const projectsBox = h('div', { style: 'display:flex;flex-direction:column;gap:6px' });

    async function drawPanel() {
      body.replaceChildren(); const langs = await loadLangs();
      if (tab === 'projects') {
        body.append(projectsBox); let ps = []; try { ps = firstArray(await api('/dub'), 'projects'); } catch (e) { return; }
        projectsBox.replaceChildren(...(ps.length ? ps.map(p => h('div', { class: 'vitem' + (S.dub && S.dub.id === p.id ? ' on' : '') },
          h('button', { class: 'grow vitem', type: 'button', style: 'padding:0', onclick: async () => { try { open(await api('/dub/' + encodeURIComponent(p.id))); } catch (e) { toast(e.message, 'err'); } } },
            h('span', { class: 'grow' }, h('div', { class: 'nm' }, p.name), h('div', { class: 'muted small' }, (p.source_lang || 'auto') + ' → ' + p.target_lang + ' · ' + p.status))),
          btn('', { icon: 'trash', cls: 'icon sm danger', aria: 'Xóa dự án', onclick: async () => { if (!await confirmBox('Xóa dự án?', 'Dự án "' + p.name + '" sẽ bị xóa.')) return; try { await api('/dub/' + encodeURIComponent(p.id), { method: 'DELETE' }); if (S.dub && S.dub.id === p.id) { S.dub = null; drawMain(); } drawPanel(); } catch (e) { toast(e.message, 'err'); } } })))
          : [h('div', { class: 'empty small' }, 'Chưa có dự án nào')]));
        return;
      }
      const src = langSelect(langs.translation.length ? langs.translation : langs.tts, 'auto', ['auto', 'Tự nhận diện']); src.value = 'auto';
      const tgt = langSelect(langs.translation.length ? langs.translation : langs.tts, 'vi');
      const go = btn('Tải lên & chép lời', { cls: 'primary block', disabled: true }); const holder = h('div');
      go.addEventListener('click', () => busy(go, async () => {
        const fd = new FormData(); fd.append('file', file, file.name); if (src.value !== 'auto') fd.append('source_lang', src.value); fd.append('target_lang', tgt.value);
        open(await withProgress(holder, p => runJob('/dub', { method: 'POST', form: fd }, p))); toast('Đã chép lời xong, hãy dịch và lồng tiếng', 'ok');
      }));
      body.append(h('div', { class: 'card' }, h('h3', null, h('span', { class: 'step' }, '1'), 'Tải lên & chép lời'),
        dropzone('Chọn hoặc kéo thả video / âm thanh', '.mp4,.mov,.mkv,.webm,.mp3,.wav,.flac,.m4a,video/*,audio/*', f => { file = f; go.disabled = false; }),
        h('div', { style: 'height:10px' }), field('Ngôn ngữ nói trong file', src), field('Ngôn ngữ muốn lồng sang', tgt), go, holder));
    }

    // ----- main -----
    function open(p) { S.dub = p; drawMain(); }
    function drawMain() {
      main.replaceChildren(); const p = S.dub;
      if (!p) { main.append(h('div', { class: 'empty', style: 'margin-top:80px' }, icon('dub', 40), h('h2', { class: 'page-h', style: 'margin-top:10px' }, 'Xưởng lồng tiếng video'), h('p', null, 'Tải một video ở bảng bên trái hoặc mở một dự án có sẵn.'))); return; }
      const warnBox = h('div'), actProg = h('div'); const taMap = new Map();
      const media = (cls, src, hasVideo) => hasVideo ? h('video', { controls: true, src, 'aria-label': cls }) : h('audio', { controls: true, src, 'aria-label': cls });
      const outBox = h('div', { class: 'card' }, h('div', { class: 'lbl', style: 'margin-bottom:6px' }, 'Bản lồng tiếng'));
      if (p.output) outBox.append(media('Bản lồng tiếng', API + p.output, p.has_video), h('div', { style: 'margin-top:8px' }, h('a', { class: 'btn sm', href: API + p.output, download: p.name + (p.has_video ? '.mp4' : '.m4a') }, icon('dl'), 'Tải xuống')));
      else outBox.append(h('div', { class: 'empty small' }, 'Chưa có. Bấm "Lồng tiếng" bên dưới.'));
      const engine = h('select', { 'aria-label': 'Công cụ dịch' }, h('option', { value: 'argos' }, 'Argos (offline)'), h('option', { value: 'llm' }, 'LLM (AI)'));
      const voice = voiceSelect(p.voice || '', ['', 'Giữ giọng người nói gốc']); voice.value = p.voice || '';
      const bg = h('input', { type: 'checkbox', checked: !!p.keep_background, 'aria-label': 'Giữ nhạc nền' });
      const strat = h('select', { 'aria-label': 'Cách khớp thời lượng' }, STRATS.map(([v, l]) => h('option', { value: v }, l)));
      const collect = () => [...taMap].map(([id, t]) => ({ id, translation: t.value }));
      const tbtn = btn('Dịch tự động', { icon: 'wand' }), rbtn = btn('Lồng tiếng', { cls: 'primary', icon: 'play' }), sbtn = btn('Lưu bản dịch');
      const doTranslate = () => busy(tbtn, async () => {
        warnBox.replaceChildren();
        try { open(await withProgress(actProg, pr => runJob('/dub/' + encodeURIComponent(p.id) + '/translate', { method: 'POST', json: { engine: engine.value } }, pr))); toast('Đã dịch xong', 'ok'); }
        catch (e) {
          if (e.error !== 'argos_pack_missing') throw e;
          const fix = btn('Cài gói dịch rồi thử lại', { cls: 'primary', onclick: ev => busy(ev.currentTarget, async () => {
            await withProgress(actProg, pr => runJob('/translation/packs', { method: 'POST', json: { from: p.source_lang && p.source_lang !== 'auto' ? p.source_lang : 'en', to: p.target_lang } }, pr)); await doTranslate(); }) });
          warnBox.replaceChildren(h('div', { class: 'card' }, h('p', null, e.message), h('div', { style: 'margin-top:8px' }, fix)));
        }
      });
      tbtn.addEventListener('click', doTranslate);
      sbtn.addEventListener('click', () => busy(sbtn, async () => { open(await api('/dub/' + encodeURIComponent(p.id), { method: 'PATCH', json: { segments: collect() } })); toast('Đã lưu', 'ok'); }));
      rbtn.addEventListener('click', () => busy(rbtn, async () => {
        await api('/dub/' + encodeURIComponent(p.id), { method: 'PATCH', json: { segments: collect(), voice: voice.value || null, keep_background: bg.checked } });
        open(await withProgress(actProg, pr => runJob('/dub/' + encodeURIComponent(p.id) + '/render', { method: 'POST', json: { strategy: strat.value } }, pr))); toast('Đã lồng tiếng xong', 'ok');
      }));
      const rows = p.segments.map(s => {
        const t = h('textarea', { rows: '2', 'aria-label': 'Bản dịch dòng ' + s.id, value: s.translation || '' }); taMap.set(s.id, t);
        return h('tr', null, h('td', { class: 'tm' }, fmtT(s.start) + ' – ' + fmtT(s.end)), h('td', { style: 'width:34%' }, s.text), h('td', null, t),
          h('td', null, s.fit ? h('span', { class: 'badge ' + s.fit }, { fits: 'Vừa khít', sped_up: 'Đã tăng tốc', overflow: 'Quá dài' }[s.fit] || s.fit) : ''));
      });
      main.append(h('div', { style: 'display:flex;flex-direction:column;gap:14px' },
        h('div', null, h('h2', { class: 'page-h' }, p.name), h('div', { class: 'muted small' }, (p.source_lang || 'auto') + ' → ' + p.target_lang + ' · ' + fmtDur(p.duration) + ' · trạng thái: ' + p.status)),
        h('div', { class: 'grid2' }, h('div', { class: 'card' }, h('div', { class: 'lbl', style: 'margin-bottom:6px' }, 'Bản gốc'), media('Bản gốc', API + '/dub/' + encodeURIComponent(p.id) + '/source', p.has_video)), outBox),
        h('div', { class: 'card' }, h('div', { class: 'row wrap', style: 'align-items:flex-end' },
          h('div', { style: 'width:170px' }, field('Công cụ dịch', engine)), tbtn, h('span', { style: 'width:12px' }),
          h('div', { style: 'width:200px' }, field('Giọng lồng', voice)), h('div', { style: 'width:200px' }, field('Cách khớp thời lượng', strat)),
          h('label', { class: 'switch', style: 'margin-bottom:14px' }, bg, 'Giữ nhạc nền'), h('span', { class: 'grow' }), h('div', { class: 'row', style: 'margin-bottom:10px' }, sbtn, rbtn)), actProg, warnBox),
        h('div', { class: 'card', style: 'padding:6px' }, h('table', { class: 'seg' }, h('thead', null, h('tr', null, h('th', null, 'Thời gian'), h('th', null, 'Lời gốc'), h('th', null, 'Bản dịch'), h('th', null, 'Khớp'))), h('tbody', null, rows)))));
    }
    drawPanel(); drawMain();
  },
};

/* ================= Sách nói ================= */
const SAMPLE_BOOK = '# Chương 1: Buổi sáng ở làng\n\nTrời vừa hửng sáng, sương còn đọng trên những mái nhà thấp. Tiếng gà gáy vọng lại từ cuối xóm.\n[pause 800ms]\nBà Tư mở cửa, hít một hơi thật sâu rồi mỉm cười.\n\n# Chương 2: Người khách lạ\n\nĐến trưa, một người đàn ông lạ mặt xuất hiện ở đầu ngõ. Anh mang theo một chiếc va-li cũ và một nụ cười mệt mỏi.\n[pause 0.5s]\nCả xóm im lặng nhìn theo.\n';
PAGES.audiobook = {
  title: 'Sách nói',
  mount(panel, main) {
    main.classList.add('flex'); let tab = 'make', planTimer = null, planSeq = 0;
    const tabs = h('div', { class: 'tabs', role: 'tablist' }, [['make', 'Sách nói'], ['done', 'Đã tạo']].map(([k, l]) => h('button', { type: 'button', role: 'tab', 'data-k': k, class: k === tab ? 'on' : '', onclick: () => { tab = k; tabs.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.k === k)); drawPanel(); } }, l)));
    const title = h('input', { type: 'text', placeholder: 'Tên sách', 'aria-label': 'Tên sách' }), author = h('input', { type: 'text', placeholder: 'Tác giả', 'aria-label': 'Tác giả' });
    const fmt = h('select', { 'aria-label': 'Định dạng' }, ['m4b', 'mp3', 'wav'].map(v => h('option', { value: v }, v)));
    const gap = h('input', { type: 'number', min: '0', max: '5000', step: '100', value: '600', 'aria-label': 'Khoảng nghỉ giữa đoạn (ms)' });
    const voiceList = h('div', { role: 'radiogroup', 'aria-label': 'Giọng mặc định', style: 'display:flex;flex-direction:column;gap:2px' });
    const create = btn('Tạo sách nói', { cls: 'primary block' }), cprog = h('div'); const doneBox = h('div', { style: 'display:flex;flex-direction:column;gap:8px' });
    const makeBox = h('div', { style: 'display:flex;flex-direction:column;gap:12px' }, h('div', { class: 'card' }, field('Tên sách', title), field('Tác giả', author), h('div', { class: 'grid2' }, field('Định dạng', fmt), field('Nghỉ giữa đoạn (ms)', gap))),
      h('div', { class: 'card' }, h('h3', null, 'Giọng mặc định'), voiceList), create, cprog);
    panel.append(tabs, makeBox, doneBox);
    function drawPanel() { makeBox.hidden = tab !== 'make'; doneBox.hidden = tab !== 'done'; if (tab === 'done') loadDone(); }
    function drawVoices() {
      if (!S.abVoice || !S.voices.find(v => v.id === S.abVoice)) S.abVoice = S.voices[0] && S.voices[0].id;
      voiceList.replaceChildren(...(S.voices.length ? S.voices.map(v => h('label', { class: 'vitem' + (v.id === S.abVoice ? ' on' : ''), style: 'cursor:pointer' }, h('input', { type: 'radio', name: 'abv', value: v.id, checked: v.id === S.abVoice, style: 'width:auto', onchange: () => { S.abVoice = v.id; drawVoices(); schedulePlan(); } }), h('span', { class: 'nm' }, v.name)))
        : [h('div', { class: 'empty small' }, 'Chưa có giọng nào. Hãy tạo ở mục Giọng nói.')]));
    }
    // ----- main editor -----
    const ta = h('textarea', { class: 'editor', style: 'resize:none;min-height:0;height:100%', 'aria-label': 'Kịch bản sách nói', placeholder: 'Viết hoặc dán kịch bản. Dòng bắt đầu bằng "# " là tên chương.', value: S.abScript });
    const outline = h('div', { class: 'card outline' }), stats = h('div', { class: 'stats' }), warnE = h('span', { class: 'warn' });
    const insert = text => { const a = ta.selectionStart, b = ta.selectionEnd; ta.setRangeText(text, a, b, 'end'); ta.focus(); onEdit(); };
    const vp = h('select', { 'aria-label': 'Giọng sẽ đổi sang' });
    const tbar = h('div', { class: 'toolbar' },
      btn('Chương', { icon: 'hash', cls: 'sm', onclick: () => { const pre = ta.selectionStart && ta.value[ta.selectionStart - 1] !== '\n' ? '\n' : ''; insert(pre + '# Tên chương\n'); } }),
      btn('Nghỉ', { icon: 'pause', cls: 'sm', title: 'Chèn [pause 800ms]', onclick: () => insert('[pause 800ms]') }),
      btn('Đổi giọng', { icon: 'voices', cls: 'sm', onclick: () => { if (vp.value) insert('[voice:' + vp.value + ']'); else toast('Chưa có giọng để chọn', 'err'); } }), vp,
      h('span', { class: 'grow' }), btn('Tải mẫu', { cls: 'sm', icon: 'wand', onclick: () => { ta.value = SAMPLE_BOOK; if (!title.value) title.value = 'Làng nhỏ ven sông'; onEdit(); } }),
      btn('Xóa kịch bản', { cls: 'sm', icon: 'trash', onclick: () => { ta.value = ''; onEdit(); } }));
    main.append(h('div', null, h('h2', { class: 'page-h' }, 'Kịch bản'), h('p', { class: 'muted' }, 'Viết hoặc nhập truyện, chèn giọng và quãng nghỉ rồi xuất thành sách nói có chương.')), tbar, h('div', { class: 'split' }, outline, ta), h('div', { class: 'row' }, stats, warnE));
    function chapters() { const out = []; let pos = 0; for (const ln of ta.value.split('\n')) { const m = ln.match(/^#\s+(.*)/); if (m) out.push({ t: m[1] || '(không tên)', pos }); pos += ln.length + 1; } return out; }
    function jump(pos) { // mirror div measures wrapped height up to pos
      const cs = getComputedStyle(ta), m = h('div'); m.style.cssText = 'position:absolute;visibility:hidden;white-space:pre-wrap;word-wrap:break-word;width:' + ta.clientWidth + 'px;font:' + cs.font + ';line-height:' + cs.lineHeight + ';padding:' + cs.padding + ';';
      m.textContent = ta.value.slice(0, pos); document.body.append(m); const y = m.scrollHeight; m.remove();
      ta.focus(); ta.setSelectionRange(pos, pos); ta.scrollTop = Math.max(0, y - 40);
    }
    function drawOutline() { const cs = chapters(); outline.replaceChildren(h('div', { class: 'lbl', style: 'margin-bottom:6px' }, 'Mục lục'), ...(cs.length ? cs.map(c => h('button', { type: 'button', title: c.t, onclick: () => jump(c.pos) }, c.t)) : [h('div', { class: 'muted small' }, 'Thêm dòng "# Tên chương" để có mục lục.')])); }
    function onEdit() { S.abScript = ta.value; drawOutline(); schedulePlan(); }
    function schedulePlan() { clearTimeout(planTimer); planTimer = setTimeout(plan, 500); }
    async function plan() {
      const seq = ++planSeq;
      if (!ta.value.trim()) { stats.textContent = '0 chương · 0 từ · 0:00'; warnE.textContent = ''; return; }
      try {
        const r = await api('/audiobook/plan', { method: 'POST', json: { script: ta.value, voice: S.abVoice || '' } }); if (seq !== planSeq) return;
        stats.textContent = r.chapters.length + ' chương · ' + r.words + ' từ · ~' + fmtDur(r.est_seconds);
        warnE.textContent = r.missing_voices && r.missing_voices.length ? '⚠ Thiếu giọng: ' + r.missing_voices.join(', ') : '';
      } catch (e) { if (seq === planSeq) { stats.textContent = ''; warnE.textContent = e.status === 402 ? '' : e.message; } }
    }
    ta.addEventListener('input', onEdit);
    create.addEventListener('click', () => {
      if (!ta.value.trim()) { toast('Kịch bản đang trống', 'err'); return; } if (!S.abVoice) { toast('Hãy chọn giọng mặc định', 'err'); return; }
      busy(create, async () => {
        const r = await withProgress(cprog, p => runJob('/audiobook', { method: 'POST', json: { script: ta.value, voice: S.abVoice, title: title.value.trim(), author: author.value.trim(), format: fmt.value, paragraph_gap_ms: +gap.value || 0 } }, p));
        toast('Đã tạo sách nói: ' + r.file_name, 'ok'); tab = 'done'; tabs.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.k === 'done')); drawPanel();
      });
    });
    async function loadDone() {
      let items = []; try { items = firstArray(await api('/audiobooks'), 'items', 'audiobooks'); } catch (e) { return; }
      doneBox.replaceChildren(...(items.length ? items.map(a => h('div', { class: 'take' }, h('div', { style: 'font-weight:600;word-break:break-all' }, a.file_name || a.title || a.id), h('div', { class: 'muted small' }, fmtDur(a.seconds) + (a.created ? ' · ' + fmtDate(a.created) : '')),
        h('audio', { controls: true, preload: 'none', src: API + '/audiobooks/' + encodeURIComponent(a.id) + '/download', 'aria-label': 'Nghe ' + (a.file_name || '') }),
        h('div', { class: 'acts' }, h('a', { class: 'btn sm', href: API + '/audiobooks/' + encodeURIComponent(a.id) + '/download', download: a.file_name || 'sach-noi' }, icon('dl'), 'Tải xuống'),
          btn('Xóa', { cls: 'sm danger', icon: 'trash', onclick: async () => { if (!await confirmBox('Xóa sách nói?', 'File sẽ bị xóa vĩnh viễn.')) return; try { await api('/audiobooks/' + encodeURIComponent(a.id), { method: 'DELETE' }); loadDone(); } catch (e) { toast(e.message, 'err'); } } }))))
        : [h('div', { class: 'empty small' }, 'Chưa có sách nói nào')]));
    }
    loadVoices().then(() => { drawVoices(); vp.replaceChildren(...S.voices.map(v => h('option', { value: v.name }, v.name))); plan(); });
    drawOutline(); drawPanel();
  },
};

/* ================= Chép lời ================= */
PAGES.transcribe = {
  title: 'Chép lời',
  mount(panel, main) {
    let curFile = null;
    const hist = h('div', { style: 'display:flex;flex-direction:column;gap:6px' }); panel.append(h('h3', { style: 'font-size:14px' }, 'Lịch sử'), hist);
    const lang = h('select', { 'aria-label': 'Ngôn ngữ trong file' }); const view = h('div'); const holder = h('div');
    const go = btn('Chép lời', { cls: 'primary', disabled: true });
    const pickFile = f => { curFile = f; go.disabled = false; };
    loadLangs().then(l => lang.append(h('option', { value: '' }, 'Tự nhận diện'), ...l.tts.map(x => h('option', { value: x.code }, x.name))));
    main.append(h('div', { class: 'setcol', style: 'max-width:900px' }, h('div', null, h('h2', { class: 'page-h' }, 'Chép lời'), h('p', { class: 'muted' }, 'Tải file âm thanh/video hoặc ghi âm để chuyển thành văn bản có mốc thời gian.')),
      h('div', { class: 'grid2' }, dropzone('Kéo thả hoặc bấm để chọn file', '.wav,.mp3,.m4a,.mp4,.webm,.flac,.ogg,audio/*,video/*', pickFile), recorder(pickFile)),
      h('div', { class: 'row', style: 'align-items:flex-end' }, h('div', { style: 'width:220px' }, field('Ngôn ngữ', lang)), h('div', { style: 'margin-bottom:10px' }, go)), holder, view));
    go.addEventListener('click', () => busy(go, async () => {
      const fd = new FormData(); fd.append('file', curFile, curFile.name); if (lang.value) fd.append('language', lang.value);
      const r = await withProgress(holder, p => runJob('/transcriptions', { method: 'POST', form: fd }, p));
      S.tUrls[r.id] = URL.createObjectURL(curFile); show(r); loadHist(); toast('Đã chép lời xong', 'ok');
    }));
    function show(r) {
      const au = S.tUrls[r.id] ? h('audio', { controls: true, src: S.tUrls[r.id], 'aria-label': 'File gốc' }) : null;
      const ex = f => h('a', { class: 'btn sm', href: API + '/transcriptions/' + encodeURIComponent(r.id) + '/export?format=' + f, download: (r.file_name || 'loi') + '.' + f }, icon('dl'), f.toUpperCase());
      view.replaceChildren(h('div', { class: 'card' }, h('div', { class: 'row wrap', style: 'margin-bottom:10px' }, h('div', { class: 'grow' }, h('div', { style: 'font-weight:600;word-break:break-all' }, r.file_name), h('div', { class: 'muted small' }, (r.language || '') + ' · ' + fmtDur(r.seconds))),
        btn('Chép văn bản', { icon: 'copy', cls: 'sm', onclick: () => navigator.clipboard.writeText(r.text).then(() => toast('Đã chép vào bộ nhớ tạm', 'ok'), () => toast('Không chép được', 'err')) }), ex('txt'), ex('srt'), ex('vtt')),
        au, h('div', { class: 'seglist', style: 'margin-top:10px' }, (r.segments || []).map(s => h('button', { type: 'button', title: 'Nhảy tới đoạn này', onclick: () => { if (au) { au.currentTime = s.start; au.play().catch(() => {}); } } }, h('span', { class: 'tm' }, fmtT(s.start)), h('span', null, s.text))))));
    }
    async function loadHist() {
      let items = []; try { items = firstArray(await api('/transcriptions'), 'items'); } catch (e) { return; }
      hist.replaceChildren(...(items.length ? items.map(i => h('div', { class: 'vitem' }, h('button', { class: 'grow vitem', type: 'button', style: 'padding:0;flex-direction:column;align-items:flex-start;gap:0', onclick: async () => { try { show(await api('/transcriptions/' + encodeURIComponent(i.id))); } catch (e) { toast(e.message, 'err'); } } },
        h('div', { class: 'nm', style: 'max-width:200px' }, i.file_name), h('div', { class: 'muted small', style: 'max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap' }, i.text || '')),
        btn('', { icon: 'trash', cls: 'icon sm danger', aria: 'Xóa', onclick: async () => { if (!await confirmBox('Xóa bản chép lời?', '"' + i.file_name + '" sẽ bị xóa.')) return; try { await api('/transcriptions/' + encodeURIComponent(i.id), { method: 'DELETE' }); view.replaceChildren(); loadHist(); } catch (e) { toast(e.message, 'err'); } } })))
        : [h('div', { class: 'empty small' }, 'Chưa có bản chép lời nào')]));
    }
    loadHist();
  },
};

/* ================= Cài đặt ================= */
const SECS = [['general', 'Chung'], ['models', 'Model'], ['ai', 'Dịch bằng AI'], ['license', 'License'], ['storage', 'Bộ nhớ'], ['about', 'Giới thiệu']];
const ATTR = 'Built with Higgs Materials licensed from Boson AI USA, Inc., Copyright Boson AI USA, Inc., All Rights Reserved and Meta Llama 3 licensed under the Meta Llama 3 Community License, Copyright Meta Platforms, Inc., All Right Reserved. based on Meta Llama 3';
PAGES.settings = {
  title: 'Cài đặt',
  mount(panel, main) {
    const nav = h('nav', { class: 'setnav', 'aria-label': 'Mục cài đặt' }); panel.append(nav);
    const col = h('div', { class: 'setcol' }); main.append(col);
    const drawNav = () => nav.replaceChildren(...SECS.map(([k, l]) => h('a', { href: '#/settings', role: 'button', tabindex: '0', class: k === S.setSec ? 'on' : '', onclick: () => { S.setSec = k; drawNav(); draw(); }, onkeydown: e => { if (e.key === 'Enter') e.currentTarget.click(); } }, l)));
    const patch = async (obj, msg) => { S.settings = await api('/settings', { method: 'PATCH', json: obj }); toast(msg || 'Đã lưu', 'ok'); return S.settings; };
    async function draw() {
      col.replaceChildren(); let st = S.settings;
      try { st = S.settings = await api('/settings'); } catch (e) { toast(e.message, 'err'); return; }
      const sec = S.setSec; col.append(h('h2', { class: 'page-h' }, (SECS.find(s => s[0] === sec) || SECS[0])[1]));
      const sel = (opts, val, onch, aria) => { const s = h('select', { 'aria-label': aria }, opts.map(([v, l]) => h('option', { value: v }, l))); s.value = val; s.addEventListener('change', () => onch(s.value).catch(e => toast(e.message, 'err'))); return s; };
      if (sec === 'general') col.append(h('div', { class: 'card' },
        field('Thiết bị tính toán', sel([['auto', 'Tự động'], ['cuda', 'GPU (CUDA)'], ['cpu', 'CPU']], st.device, v => patch({ device: v }), 'Thiết bị')),
        field('Chất lượng mặc định', sel([['fast', 'Nhanh'], ['balanced', 'Cân bằng'], ['quality', 'Chất lượng']], st.quality, v => patch({ quality: v }), 'Chất lượng')),
        field('Model chép lời', sel([['large-v3', 'large-v3 (chính xác, nặng)'], ['small', 'small (nhanh, nhẹ)']], st.asr_model, v => patch({ asr_model: v }), 'Model chép lời'))));
      if (sec === 'models') await modelsSection();
      if (sec === 'ai') {
        const llm = st.llm || {}; const url = h('input', { type: 'text', value: llm.base_url || '', placeholder: 'https://api.openai.com/v1' }), mdl = h('input', { type: 'text', value: llm.model || '', placeholder: 'tên model' }), key = h('input', { type: 'password', autocomplete: 'off', placeholder: llm.has_key ? 'Đã lưu khóa (nhập để thay)' : 'API key' });
        col.append(h('div', { class: 'card' }, h('p', { class: 'muted', style: 'margin-bottom:10px' }, 'Dùng cho dịch tự động bằng AI (API tương thích OpenAI). Khóa chỉ lưu trên máy này.'), field('Base URL', url), field('Model', mdl), field('API key', key),
          h('div', { class: 'row' }, btn('Lưu', { cls: 'primary', onclick: e => busy(e.currentTarget, async () => { const l = { base_url: url.value.trim(), model: mdl.value.trim() }; if (key.value) l.api_key = key.value; await patch({ llm: l }); draw(); }) }), h('span', { class: 'muted small' }, llm.has_key ? '✓ Đã có API key' : 'Chưa có API key'))));
      }
      if (sec === 'license') licenseSection();
      if (sec === 'storage') col.append(h('div', { class: 'card' }, h('div', { class: 'lbl' }, 'Thư mục dữ liệu'), h('p', { style: 'word-break:break-all;margin:4px 0 12px' }, st.data_dir || ''),
        h('div', { class: 'row wrap' }, window.vc && window.vc.showItemInFolder ? btn('Mở thư mục', { icon: 'folder', onclick: () => window.vc.showItemInFolder(st.data_dir) }) : null, btn('Giải phóng bộ nhớ GPU', { onclick: e => busy(e.currentTarget, async () => { await api('/model/unload', { method: 'POST' }); toast('Đã giải phóng model khỏi GPU', 'ok'); }) }))));
      if (sec === 'about') col.append(h('div', { class: 'card' }, h('p', null, 'VoiceClone Studio · phiên bản ' + ((S.health && S.health.version) || '?') + (window.vc && window.vc.version ? ' (ứng dụng ' + window.vc.version + ')' : ''))),
        h('div', { class: 'card' }, h('h3', null, 'Ghi công'), h('p', { class: 'attr' }, ATTR), h('p', { class: 'attr', style: 'margin-top:10px' }, 'OmniVoice (k2-fsa, Apache-2.0) · faster-whisper (MIT) · Demucs (MIT) · Argos Translate (MIT) · FFmpeg (LGPL)')));
    }
    async function modelsSection() {
      let m; try { m = await api('/models'); } catch (e) { toast(e.message, 'err'); return; }
      const card = h('div', { class: 'card' }); card.append(h('h3', null, 'Model giọng nói'));
      for (const x of m.models) {
        const holder = h('div'); const b = x.installed ? h('span', { class: 'badge fits' }, 'Đã cài') : btn('Tải xuống', { icon: 'dl', cls: 'sm', onclick: e => busy(e.currentTarget, async () => { await withProgress(holder, p => runJob('/models/' + encodeURIComponent(x.id) + '/download', { method: 'POST' }, p)); toast('Đã tải ' + x.name, 'ok'); refreshHealth(); draw(); }) });
        card.append(h('div', { class: 'mrow', style: 'flex-wrap:wrap' }, h('div', { class: 'grow' }, h('div', { style: 'font-weight:600' }, x.name + (x.required ? ' *' : '')), h('div', { class: 'muted small' }, fmtSize(x.size_mb) + (x.license ? ' · ' + x.license : ''))), b, h('div', { style: 'width:100%' }, holder)));
      }
      const langs = await loadLangs(); const tl = langs.translation.length ? langs.translation : langs.tts; const from = langSelect(tl, 'en'), to = langSelect(tl, 'vi'); const ph = h('div');
      const pk = h('div', { class: 'card' }, h('h3', null, 'Gói dịch offline (Argos)'), (m.translation_packs || []).length ? h('div', { class: 'chips', style: 'margin-bottom:12px' }, m.translation_packs.map(p => h('span', { class: 'badge' + (p.installed ? ' fits' : '') }, p.from + ' → ' + p.to + (p.installed ? ' ✓' : '')))) : h('p', { class: 'muted small' }, 'Chưa có gói nào.'),
        h('div', { class: 'row', style: 'align-items:flex-end' }, h('div', { class: 'grow' }, field('Từ', from)), h('div', { class: 'grow' }, field('Sang', to)), h('div', { style: 'margin-bottom:10px' }, btn('Cài gói', { onclick: e => busy(e.currentTarget, async () => { await withProgress(ph, p => runJob('/translation/packs', { method: 'POST', json: { from: from.value, to: to.value } }, p)); toast('Đã cài gói dịch', 'ok'); draw(); }) }))), ph);
      col.append(card, pk);
    }
    function licenseSection() {
      const hh = S.health || {}, lic = hh.license; const key = h('input', { type: 'text', placeholder: 'Dán license key', 'aria-label': 'License key', autocomplete: 'off' });
      const exp = lic && lic.exp ? fmtDate(lic.exp) : 'Không giới hạn';
      col.append(h('div', { class: 'card' }, lic ? [h('div', { class: 'lbl' }, 'Khách hàng'), h('p', null, lic.sub), h('div', { class: 'lbl', style: 'margin-top:8px' }, 'Tính năng'), h('div', { class: 'chips', style: 'margin:4px 0' }, (lic.features || []).map(f => h('span', { class: 'badge fits' }, f))), h('div', { class: 'lbl', style: 'margin-top:8px' }, 'Hết hạn'), h('p', null, exp)] : h('p', { class: 'muted' }, 'Chưa có license. Nhập key để mở khóa các tính năng.')),
        h('div', { class: 'card' }, field('License key', key), h('div', { class: 'row' }, btn('Kích hoạt', { cls: 'primary', onclick: e => busy(e.currentTarget, async () => { await api('/license', { method: 'POST', json: { key: key.value.trim() } }); toast('Đã kích hoạt license', 'ok'); await refreshHealth(); draw(); }) }),
          lic ? btn('Gỡ key', { cls: 'danger', onclick: async e => { if (!await confirmBox('Gỡ license?', 'Các tính năng cần license sẽ bị khóa.')) return; busy(e.currentTarget, async () => { await api('/license', { method: 'DELETE' }); toast('Đã gỡ license'); await refreshHealth(); draw(); }); } }) : null)));
    }
    drawNav(); draw();
  },
};

/* ---------- boot ---------- */
buildRail();
$('#retry').addEventListener('click', () => refreshHealth().then(route));
window.addEventListener('hashchange', route);
refreshHealth().then(() => api('/settings').then(s => { S.settings = s; }).catch(() => {})).finally(route);
setInterval(refreshHealth, 15000);
