/* Lodestar dashboard. Talks only to the local /api routes; long actions are background tasks polled by run(). */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
let S = null, cur = null, CT = null, chatHist = [];  // cur: the job in the drawer; CT: the contact in it
const TOPICS = ['strategy', 'resume', 'gap', 'outreach', 'stories', 'pivot', 'questions', 'negotiation', 'tools', 'custom'];

const TOKEN = window.LODESTAR_TOKEN || '', CAPTURE = window.LODESTAR_CAPTURE || '';
const safeUrl = u => /^https?:\/\//i.test(u || '') ? u : '';
const api = (p, body) => fetch(p, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', 'X-Lodestar-Token': TOKEN }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json());
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const opt = (list, sel) => list.map(s => `<option ${s === sel ? 'selected' : ''}>${s}</option>`).join('');
// stored timestamps are UTC ('YYYY-MM-DD HH:MM:SS', SQLite datetime('now')); show them in this computer's time zone.
// n: how many characters to keep (10 = the date, 16 = date and minutes). Dates and local times (interview rounds) pass
// through untouched: only call this on stored UTC times.
function localTs(s, n = 19) {
  const m = /^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d(?::\d\d)?)/.exec(s || ''); if (!m) return String(s ?? '').slice(0, n);
  const d = new Date(`${m[1]}T${m[2]}Z`); if (isNaN(d)) return String(s).slice(0, n);
  const p = x => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`.slice(0, n);
}
function toast(m, kind = '') { const t = $('#toast'); t.textContent = m; t.className = kind; t.style.display = 'block'; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', 4500); }
function show(id, text) { const e = $('#' + id); e.style.display = 'block'; e.textContent = typeof text === 'string' ? text : JSON.stringify(text, null, 2); }
function gapText(g) {  // the gap check as sentences: the verdict first, then what to work on
  const list = (label, a) => Array.isArray(a) && a.length ? [`\n${label}:`, ...a.map(x => '- ' + x)] : [];
  return [g.verdict ? `Verdict: ${g.verdict}${g.why ? ' - ' + g.why : ''}` : (g.note || 'no AI verdict'),
    `JD coverage: ${g.match_score ?? '-'}%` + (g.missing_keywords?.length ? ` (missing: ${g.missing_keywords.slice(0, 15).join(', ')})` : ''),
    ...list('Weak areas', g.weak_areas), ...list('Suggestions', g.suggestions), ...list('Red flags', g.red_flags),
    g.salary_in_posting?.length ? `\nPay in the posting: ${g.salary_in_posting.join(', ')}` : '',
    g.market_range ? `Your market range: ${g.market_range.low}-${g.market_range.high} (${g.market_range.city})` : ''].filter(Boolean).join('\n');
}
function mailText(r) {
  if (!r.draft) return r.text || (r.gap ? gapText(r.gap) : r.answer || ('wrote ' + (r.path || '')));
  const p = r.proposal || {};
  return `Subject: ${r.draft.subject}\n\n${r.draft.body}\n\n-> ${p.status}${p.id ? ' (inbox #' + p.id + ')' : ''}${p.reason ? ' - ' + p.reason : ''}`;
}

/* ---- navigation ---- */
$$('nav button[data-tab]').forEach(b => b.onclick = () => go(b.dataset.tab));
function go(tab) {
  $$('nav button[data-tab], main section').forEach(x => x.classList.remove('on'));
  $(`nav button[data-tab="${tab}"]`).classList.add('on'); $('#' + tab).classList.add('on');
  if (tab !== 'board' || CT) closeDrawer();
  if (tab === 'contacts') loadContacts();
  if (tab === 'insights') loadInsights();
  if (tab === 'setup') loadEmail();
}

/* ---- background tasks ---- */
async function run(action, params, done, btn, fail) {  // fail(error): the caller also shows a refusal in place
  if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = 'working…'; }
  const finish = () => { if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label; } };
  const { task, error } = await api(action.startsWith('/') ? action : '/api/run/' + action, params);  // or a route that starts a task
  if (error) { finish(); fail && fail(error); return toast('error: ' + error, 'err'); }
  const poll = async () => {
    const t = await api('/api/tasks/' + task);
    if (t.status === 'running') return setTimeout(poll, 1200);
    finish();
    if (t.status === 'error') { fail && fail(t.error); return toast('error: ' + t.error, 'err'); }
    done && done(t.result); load();
  };
  poll();
}

/* ---- state ---- */
async function load() {
  S = await api('/api/state');
  const st = S.stats, pct = x => Math.round(x * 100) + '%';
  $('#stats').innerHTML = `<span>tracked <b>${S.jobs.length}</b></span><span>applied <b>${st.applied_total}</b></span><span>response <b>${pct(st.response_rate)}</b></span><span>interview <b>${pct(st.interview_rate)}</b></span><span>providers <b>${Object.values(S.providers).filter(Boolean).length}</b></span><span>tokens today <b>${(S.usage_today.input + S.usage_today.output).toLocaleString()}</b></span>`;
  const pill = $('#codesPill'); pill.style.display = S.codes_count ? '' : 'none'; pill.textContent = `Codes (${Number(S.codes_count)})`;
  if (S.codes_count !== CODES.length && (S.codes_count || $('#codesPanel').open)) codesLoad();
  const badge = $('#inboxN'); badge.textContent = S.pending.length; badge.classList.toggle('zero', !S.pending.length);
  renderOnboard(); renderLoop(); renderUpdate(); $('#ver').textContent = 'Lodestar ' + S.version;
  if (!$('#fStatus').options.length) initFilters();
  renderBoard(); renderInbox(); renderSearchless(); renderMonitor(); renderAnswers(); renderStories(); renderIdeas(); renderTools(); renderSetup(); fillCoachJobs(); renderTrend();
}

/* ---- board: filters, sort, view (kept in localStorage), drag and drop, table, Today ---- */
const VIEW_KEY = 'ls_board_view';
let V = { view: 'board', key: 'updated_at', dir: -1, q: '', status: '', remote: '', minSal: '', tag: '', dl: false };
try { Object.assign(V, JSON.parse(localStorage.getItem(VIEW_KEY) || '{}')); } catch (_) { /* storage blocked or corrupt: defaults */ }
const saveView = () => { try { localStorage.setItem(VIEW_KEY, JSON.stringify(V)); } catch (_) { /* storage blocked */ } };
const SORTS = { updated: ['updated_at', -1], stale: ['updated_at', 1], match: ['match_score', -1], salary: ['salary', -1], excitement: ['excitement', -1], deadline: ['deadline', 1] };
const tagsOf = j => (j.tags || '').split(',').map(t => t.trim()).filter(Boolean);
const payOf = j => j.salary_max ?? j.salary_min ?? null;
const sortVal = (j, k) => k === 'salary' ? payOf(j) : k === 'status' ? S.statuses.indexOf(j.status) : j[k] ?? null;
const k0 = n => n >= 1000 ? Math.round(n / 1000) + 'k' : String(n);
const salaryText = j => payOf(j) == null ? '' : (j.currency ? j.currency + ' ' : '') + (j.salary_min != null && j.salary_max != null && j.salary_min !== j.salary_max ? k0(j.salary_min) + '–' + k0(j.salary_max) : k0(payOf(j)));
const stars = j => { const n = Math.max(0, Math.min(5, j.excitement | 0)); return n ? `<span class="stars" title="excitement ${n} of 5" aria-label="excitement ${n} of 5">${'★'.repeat(n)}${'☆'.repeat(5 - n)}</span>` : ''; };
function daysTo(d) { const t = new Date(); t.setHours(0, 0, 0, 0); return Math.round((new Date(d + 'T00:00:00') - t) / 864e5); }
function deadlineChip(j) {
  if (!j.deadline) return '';
  const d = daysTo(j.deadline);
  return `<span class="chip ${d <= 3 ? 'due' : ''}" title="deadline ${esc(j.deadline)}">${d < 0 ? 'deadline passed' : d === 0 ? 'due today' : 'due in ' + d + 'd'}</span>`;
}
const where = j => [j.location, j.remote].filter(Boolean).join(' · ');
function visibleJobs() {
  const q = V.q.trim().toLowerCase(), tag = V.tag.trim().toLowerCase(), min = Number(V.minSal) || 0;
  return S.jobs.filter(j => (!q || [j.company, j.title, j.location, j.tags].join(' ').toLowerCase().includes(q))
    && (!V.status || j.status === V.status) && (!V.remote || j.remote === V.remote) && (!min || payOf(j) == null || payOf(j) >= min)
    && (!tag || tagsOf(j).some(t => t.toLowerCase() === tag)) && (!V.dl || j.deadline))
    .sort((a, b) => {  // missing values always last; ties keep the server order (most recent activity first)
      const x = sortVal(a, V.key), y = sortVal(b, V.key);
      if (x === y) return 0; if (x == null) return 1; if (y == null) return -1;
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * V.dir;
    });
}
function initFilters() {
  $('#fStatus').innerHTML = '<option value="">any status</option>' + opt(S.statuses, V.status);
  $('#bulkStatus').innerHTML = opt(S.statuses);
  $('#fQ').value = V.q; $('#fRemote').value = V.remote; $('#fSal').value = V.minSal; $('#fTag').value = V.tag; $('#fDl').checked = V.dl;
  syncSort();
  ['#fQ', '#fStatus', '#fRemote', '#fSal', '#fTag', '#fDl'].forEach(s => $(s).addEventListener('input', () => {
    V.q = $('#fQ').value; V.status = $('#fStatus').value; V.remote = $('#fRemote').value; V.minSal = $('#fSal').value; V.tag = $('#fTag').value; V.dl = $('#fDl').checked;
    saveView(); renderBoard();
  }));
  $('#fSort').addEventListener('change', e => { if (!SORTS[e.target.value]) return; [V.key, V.dir] = SORTS[e.target.value]; saveView(); renderBoard(); });
}
function syncSort() { $('#fSort').value = Object.keys(SORTS).find(k => SORTS[k][0] === V.key && SORTS[k][1] === V.dir) || ''; }
function sortBy(k) {  // table header: same column flips the direction; numbers start high-first, text and dates A-Z / soonest
  if (V.key === k) V.dir = -V.dir; else { V.key = k; V.dir = ['match_score', 'excitement', 'salary', 'updated_at'].includes(k) ? -1 : 1; }
  saveView(); syncSort(); renderBoard();
}
function clearFilters() {
  Object.assign(V, { q: '', status: '', remote: '', minSal: '', tag: '', dl: false }); saveView();
  $('#fQ').value = $('#fStatus').value = $('#fRemote').value = $('#fSal').value = $('#fTag').value = ''; $('#fDl').checked = false;
  renderBoard();
}
function toggleView() { V.view = V.view === 'table' ? 'board' : 'table'; saveView(); renderBoard(); }
function card(j) {
  const chips = [stars(j), salaryText(j) && `<span>${esc(salaryText(j))}</span>`, j.match_score != null && `<span>match ${esc(j.match_score)}%</span>`,
    where(j) && `<span>${esc(where(j))}</span>`, deadlineChip(j), staleChip(j.ghost), sponsorChip(j.sponsor), warmChip(j.warm)].filter(Boolean).join('');
  return `<div class="card ${S.followups.includes(j.id) ? 'late' : ''} ${cur && cur.job.id === j.id ? 'sel' : ''}" data-id="${j.id}" draggable="true" tabindex="0" role="button"
    aria-label="${esc(`#${j.id} ${j.company} - ${j.title}, ${j.status}`)}" ondragstart="event.dataTransfer.setData('text/plain','${j.id}');event.dataTransfer.effectAllowed='move'"
    onclick="openJob(${j.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openJob(${j.id})}">
    <div class="co">${esc(j.company)}</div><div class="ti">${esc(j.title)}</div>${chips ? `<div class="chips">${chips}</div>` : ''}
    <div class="meta"><span>#${j.id}</span><span>${esc(localTs(j.updated_at, 10))}</span></div></div>`;
}
function dragOver(e) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; e.currentTarget.classList.add('drop'); }
function dropJob(e, status) { e.preventDefault(); e.currentTarget.classList.remove('drop'); const id = Number(e.dataTransfer.getData('text/plain')); if (id) moveJob(id, status); }
async function moveJob(id, status) {  // a drag or the drawer's move button (a select's change fires per arrow key): backward and 'accepted' ask first
  const j = S.jobs.find(x => x.id === id);
  const forward = j && S.statuses.indexOf(status) > S.statuses.indexOf(j.status);
  if (j && j.status !== status && (status === 'accepted'
      ? confirm(`Mark #${id} ${j.company} - ${j.title} accepted? Withdrawing your other open applications will be proposed in the Inbox.`)
      : forward || confirm(`Move #${id} ${j.company} - ${j.title} back from "${j.status}" to "${status}"?`))) {
    const r = await api(`/api/jobs/${id}/status`, { status, note: '(moved by you)' });
    if (r.error) toast('error: ' + r.error, 'err');
    else { toast(`#${id} → ${status}` + (status === 'accepted' ? '. Withdrawing your other open applications is proposed in the Inbox.' : ''), 'ok'); await load(); }
  }
  if (cur && cur.job.id === id) openJob(id);  // also resets the drawer select after a cancelled move
}
function renderToday() {
  const t = S.today, el = $('#today');
  const item = (i, label, cls = '') => `<button class="b ghost sm ${cls}" onclick="openJob(${i.id})">${esc(label)} · #${i.id} ${esc(i.company)} - ${esc(i.title)}</button>`;
  const parts = [...t.actions.map(i => item(i, (i.overdue ? 'overdue ' + i.when : 'today') + ': ' + i.what, i.overdue ? 'due' : '')),
    ...t.deadlines.map(i => item(i, i.days === 0 ? 'deadline today' : `deadline in ${i.days}d`, 'due')),
    ...t.interviews.map(i => item(i, 'interview ' + i.when)), ...t.followups.map(i => item(i, 'follow up')),
    ...(t.contacts || []).map(c => `<button class="b ghost sm" onclick="openContact(${Number(c.id)})">get in touch (due ${esc(c.when)}) · ${esc(c.name)}${c.company ? ' (' + esc(c.company) + ')' : ''}</button>`)];
  const em = (t.emails || []).map((s, i) => `<div class="row"><span class="chip ${s.priority === 1 ? 'due' : ''}">${esc(dueText(s.due))}</span><span>${esc(s.reason)} · #${Number(s.job_id)} ${esc(s.company)}${s.to ? ' → ' + esc(s.to) : ''}</span>
    <button class="b ghost sm" onclick="suggestDraft(${i},this)">Draft options</button><button class="b ghost sm" onclick="suggestDismiss(${i})">Dismiss for now</button></div>`);
  el.style.display = parts.length || em.length || t.pending ? '' : 'none';
  el.innerHTML = `<h3>Today</h3><div class="row">${parts.join('')}${t.pending ? `<button class="b sm" onclick="go('inbox')">${t.pending} waiting in the Inbox</button>` : ''}</div>`
    + (em.length ? `<h4>Suggested emails</h4>${em.join('')}` : '');
}
let SEL = new Set();  // table checkboxes; survives the 60 s refresh
const COLS = [['id', '#'], ['company', 'Company'], ['title', 'Title'], ['status', 'Status'], ['salary', 'Salary'], ['match_score', 'Match'], ['excitement', 'Excitement'], ['deadline', 'Deadline'], ['location', 'Location'], ['updated_at', 'Last activity']];
function renderTable(jobs) {
  const shown = new Set(jobs.map(j => j.id)); SEL = new Set([...SEL].filter(id => shown.has(id)));  // bulk acts on what you see
  const sortAttr = k => V.key === k ? (V.dir > 0 ? 'ascending' : 'descending') : 'none';
  $('#jobTable').innerHTML = `<table class="jobs"><thead><tr><th><input type="checkbox" aria-label="select all shown jobs" ${jobs.length && SEL.size === jobs.length ? 'checked' : ''} onchange="selAll(this.checked)"></th>`
    + COLS.map(([k, l]) => `<th aria-sort="${sortAttr(k)}"><button class="th" onclick="sortBy('${k}')">${l}${V.key === k ? (V.dir > 0 ? ' ▲' : ' ▼') : ''}</button></th>`).join('') + '</tr></thead><tbody>'
    + jobs.map(j => `<tr class="${S.followups.includes(j.id) ? 'late' : ''}"><td><input type="checkbox" aria-label="select #${j.id}" ${SEL.has(j.id) ? 'checked' : ''} onchange="selOne(${j.id},this.checked)"></td>
      <td>${j.id}</td><td><a href="#" onclick="openJob(${j.id});return false">${esc(j.company)}</a></td><td>${esc(j.title)}</td><td>${esc(j.status)}</td><td>${esc(salaryText(j))}</td>
      <td>${esc(j.match_score ?? '')}</td><td>${stars(j)}</td><td>${deadlineChip(j)}</td><td>${esc(where(j))}</td><td>${esc(localTs(j.updated_at, 10))}</td></tr>`).join('')
    + '</tbody></table>';  // no match: #filterEmpty (renderBoard) says so for both views
  renderBulk();
}
function renderBulk() { $('#bulk').style.display = V.view === 'table' && SEL.size ? '' : 'none'; $('#bulkN').textContent = SEL.size + ' selected'; }
function selOne(id, on) { if (on) SEL.add(id); else SEL.delete(id); renderBulk(); }
function selAll(on) { SEL = new Set(on ? visibleJobs().map(j => j.id) : []); renderBoard(); }
async function bulk(fn, done) {
  const ids = [...SEL]; let bad = 0;
  for (const id of ids) { const r = await fn(id); if (!r || r.error) bad++; }
  SEL.clear(); toast(bad ? `${bad} of ${ids.length} failed` : done(ids.length), bad ? 'err' : 'ok'); load();
}
function bulkStatus() {
  const s = $('#bulkStatus').value; if (!confirm(`Set ${SEL.size} job(s) to "${s}"?`)) return;
  bulk(id => api(`/api/jobs/${id}/status`, { status: s, note: '(bulk, by you)' }), n => `${n} job(s) → ${s}`);
}
function bulkTag() {
  const t = $('#bulkTag').value.trim(); if (!t) return toast('type a tag first', 'err');
  bulk(id => { const j = S.jobs.find(x => x.id === id); return j && api(`/api/jobs/${id}/fields`, { tags: [...new Set([...tagsOf(j), t])].join(',') }); }, n => `tagged ${n} job(s)`);
}
function bulkDelete() {
  if (!confirm(`Delete ${SEL.size} job(s) with their timelines? This cannot be undone.`)) return;
  if (cur && SEL.has(cur.job.id)) closeDrawer();
  bulk(id => api(`/api/jobs/${id}/delete`, {}), n => `deleted ${n} job(s)`);
}

function renderBoard() {
  renderToday();
  const jobs = visibleJobs(), table = V.view === 'table';
  $('#fView').textContent = table ? 'Board view' : 'Table view'; $('#fView').setAttribute('aria-pressed', String(table));
  $('#cols').style.display = table ? 'none' : ''; $('#jobTable').style.display = table ? '' : 'none';
  if (table) renderTable(jobs);
  else {
    renderBulk();
    $('#cols').innerHTML = S.statuses.map(s => {
      const col = jobs.filter(j => j.status === s);
      return `<div class="col" data-s="${s}" ondragover="dragOver(event)" ondragleave="this.classList.remove('drop')" ondrop="dropJob(event,'${s}')"><h3>${s} <span>${col.length}</span></h3>` + col.map(card).join('') + '</div>';
    }).join('');
  }
  // filters are remembered across restarts: say so when they hide every job, with a way out
  $('#filterEmpty').style.display = S.jobs.length && !jobs.length ? '' : 'none';
  const f = S.funnel.stages;
  $('#funnel').innerHTML = f.applied.reached ? 'funnel: ' + Object.entries(f).map(([s, d]) => `<span class="pill">${s} ${d.reached}${d.conversion != null ? ' → ' + Math.round(d.conversion * 100) + '%' : ''}${d.median_days_to_next != null ? ' · ' + d.median_days_to_next + 'd' : ''}</span>`).join('') : '';
  $('#upcoming').innerHTML = S.upcoming.length ? 'upcoming interviews: ' + S.upcoming.map(i => `<button class="b ghost sm" onclick="openJob(${i.job_id})">${esc(i.when)} · #${i.job_id} ${esc(i.company)} - ${esc(i.title)}</button>`).join(' ') : '';
  $('#variants').innerHTML = S.variants.length ? 'resume variants: ' + S.variants.map(v => `<span class="pill">${v.variant}: ${v.applied} sent, ${Math.round(v.interview_rate * 100)}% interview</span>`).join(' ') : '';
  $('#boardEmpty').style.display = S.jobs.length ? 'none' : '';
}

/* ---- onboarding + health ---- */
function renderOnboard() {
  const s = S.setup, todo = [];
  if (!s.profile_ready) todo.push(`<b>1.</b> Fill in your master resume <button class="b sm" onclick="go('profile')">Profile</button> or import one there`);
  const keySetup = `<button class="b sm" onclick="go('setup');$('#keysCard').scrollIntoView()">Setup</button>`;
  if (!s.provider_ready) todo.push(`<b>2.</b> Link an AI key ${keySetup} (checked at once; kept in the OS keyring)`);
  (s.provider_problems || []).forEach(p => todo.push(`<span style="color:var(--warn)">${esc(p.label)} key failed: ${esc(p.detail)}</span> ${keySetup}`));
  if (s.email_problem) todo.push(`<span style="color:var(--warn)">Email check failed: ${esc(s.email_problem)}</span> <button class="b sm" onclick="go('setup');$('#emailCard').scrollIntoView()">Setup</button>`);
  if (s.email_needs_signin) todo.push(`<span style="color:var(--bad)">Email sign-in expired: Lodestar cannot read or send mail</span> <button class="b sm" onclick="go('setup');$('#emailCard').scrollIntoView()">Sign in again</button>`);
  else if (!s.email_ready) todo.push(`<b>3.</b> Optional: <button class="b sm" onclick="go('setup');$('#emailCard').scrollIntoView()">Connect email</button> so replies are classified and drafted`);
  const uf = S.update && S.update.failed;  // the last update failed or was refused: rolled back, say so once here
  if (uf) todo.push(`<span style="color:var(--warn)">Last update ${uf.result.startsWith('refused') ? 'was refused' : 'failed'} (${esc(String(uf.at).slice(0, 16))}): ${esc(uf.result)}</span> <button class="b sm" onclick="go('setup');$('#updCard').scrollIntoView()">Updates</button>`);
  const el = $('#onboard');
  el.style.display = todo.length ? '' : 'none';
  el.innerHTML = todo.length ? `<h3>Getting started</h3><div class="row" style="gap:18px">${todo.map(t => `<span>${t}</span>`).join('')}</div>` : '';
  if (!s.provider_ready && !sessionStorage.getItem('ls_setup_shown') && !S.jobs.length) { sessionStorage.setItem('ls_setup_shown', '1'); go('setup'); }
}
function renderLoop() {
  const l = S.loop, el = $('#loopStat');
  if (!l.running) { el.textContent = 'monitor loop: not running in this process'; el.title = 'start with the Lodestar shortcut, lodestar desktop, or lodestar run'; return; }
  el.textContent = `monitor loop: every ${l.every} min · last cycle ${l.last_cycle || 'starting'} · ${l.cycles} run${l.cycles === 1 ? '' : 's'}${l.last_error ? ' · last problem: ' + l.last_error : ''}`;
  el.title = l.last_error || '';
}

/* ---- job drawer ---- */
let OPENER = null;  // what had focus when the drawer opened: focus returns there when it closes
function openDrawer(label) {
  const d = $('#drawer');
  if (!d.classList.contains('open')) OPENER = document.activeElement;
  d.setAttribute('aria-label', label); d.inert = false; d.setAttribute('aria-modal', 'true'); d.classList.add('open');
  $('#drawer .close')?.focus();
}
function closeDrawer() {
  const d = $('#drawer'), id = cur && cur.job.id, wasOpen = d.classList.contains('open');
  const inside = d.contains(document.activeElement) || document.activeElement === document.body;
  d.classList.remove('open'); d.inert = true; d.removeAttribute('aria-modal');  // closed: no focus, no screen reader
  cur = CT = null; $$('.card.sel').forEach(c => c.classList.remove('sel'));
  if (wasOpen && inside) {  // the board re-renders every minute: fall back to the job's card when the opener is gone
    const back = OPENER && OPENER.isConnected ? OPENER : id && $(`.card[data-id="${Number(id)}"]`);
    back?.focus();
  }
  if (wasOpen) OPENER = null;
}
async function openJob(id) {
  const d = await api('/api/jobs/' + id); if (d.error) return toast(d.error, 'err');
  cur = d; CT = null; const j = d.job, docs = Object.keys(d.docs);
  $$('.card').forEach(c => c.classList.toggle('sel', c.dataset.id === String(id)));
  $('#drawer').innerHTML = `
    <div class="head"><b>${esc(j.company)}</b><span class="muted">${esc(j.title)} · #${j.id}</span>
      ${safeUrl(j.url) ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">posting ↗</a>` : ''}
      <select id="jStatus" aria-label="Status">${opt(S.statuses, j.status)}</select><button class="b ghost sm" onclick="moveJob(${j.id},$('#jStatus').value)">move</button>
      <button class="b ghost sm close" onclick="closeDrawer()" aria-label="Close job details">✕</button></div>
    <div class="muted">contact: ${esc(j.contact_name || '')} ${esc(j.contact_email || '(none; replies and follow-ups need one)')}</div>
${detailsForm(j)}
${peopleGroup(d)}
${roundsGroup(d)}

    <div class="group"><h4>Match</h4>
      <div class="row"><button class="b" onclick="jobMatch(this)">${savedCoverage(d) ? 'Recompute' : 'Compute'} JD coverage</button><button class="b ghost" onclick="jobLint(this)">Check resume</button><button class="b ghost" onclick="run('audit',{id:${j.id}},r=>{$('#jCheck').innerHTML=auditHtml(r)},this)">Audit resume.docx</button></div>
      <div class="muted">JD coverage is the share of the posting's keywords your current resume (tailored, else your profile) mentions: a guide for tailoring, not an ATS pass/fail. No AI involved.</div>
      <div id="jMatch"></div><div id="jCheck"></div></div>

    <div class="group"><h4>Documents</h4><div class="row">
      <button class="b" onclick="jobRun('gap',{},this)">Gap check (coverage + AI verdict)</button>
      <button class="b" onclick="jobRun('tailor',{docx:true,base:baseOpt()},this)">Tailor resume (+docx)</button>
      <button class="b" onclick="tailorBullets(this)">Tailor by bullet</button>
      <button class="b" onclick="jobRun('cover',{docx:true,tone:$('#jTone').value,words:$('#jWords').value},this)">Cover letter (+docx)</button>
      <button class="b ghost" onclick="draftOptions('cover',{id:${j.id},tone:$('#jTone').value,words:$('#jWords').value},'jOpts',this)" title="up to 3 letters from one AI call; Use this opens one in the editor">Cover options</button>
      <input id="jTone" placeholder="tone: confident, warm, specific" style="width:190px"><input id="jWords" type="number" min="100" max="800" placeholder="words (300)" style="width:100px">
      <button class="b ghost" onclick="jobRun('prep',{},this)">Interview prep</button>
      <button class="b ghost" onclick="jobRun('research',{},this)">Company research</button>
      <button class="b ghost" onclick="run('checklist',{id:${j.id}},r=>show('jOut',r.checklist.map(c=>(c.done?'[x] ':c.na?'[-] ':'[ ] ')+c.item+(c.na?' (n/a yet)':c.done?'':'   -> '+c.next)).join('\\n')),this)">Checklist</button>
      <label class="muted"><input type="checkbox" id="jCouncil"> council (all providers)</label></div>
      <div class="row">${S.bases.length ? `<label class="muted">tailor from <select id="jBase"><option value="">master profile</option>${S.bases.map(b => `<option value="${esc(b.id)}">saved: ${esc(b.name)} (${esc(b.added.slice(0, 10))})</option>`).join('')}</select></label>` : ''}
        <label class="muted">style <select id="jStyle" onchange="setPref('resume_style',this.value)">${opt(S.pref_choices.resume_style, S.prefs.resume_style)}</select></label>
        <button class="b ghost" onclick="exportPdf(this)">Export PDF</button></div>
      <div id="jBullets"></div></div>

    <div class="group"><h4>Communicate</h4>
      <div class="row"><input id="jIntent" class="grow" placeholder="reply intent, e.g. accept interview, propose Tue/Wed afternoons"><button class="b ghost" onclick="jobRun('reply',{intent:$('#jIntent').value},this)">Draft reply</button></div>
      <div class="row"><input id="jPerson" class="grow" placeholder="outreach to: Name, title (optional)"><select id="jChannel"><option value="linkedin">LinkedIn note</option><option value="email">Email</option></select><button class="b ghost" onclick="jobRun('outreach',{person:$('#jPerson').value,channel:$('#jChannel').value},this)">Draft outreach</button></div>
      <div class="row"><button class="b ghost" onclick="jobRun('followup',{template:$('#jTpl').checked},this)">Follow-up email</button><input id="jInt" placeholder="interviewer" style="width:140px"><input id="jTnotes" class="grow" placeholder="something specific from the interview"><button class="b ghost" onclick="jobRun('thanks',{interviewer:$('#jInt').value,notes:$('#jTnotes').value,template:$('#jTpl').checked},this)">Thank-you note</button></div>
      <div class="row"><button class="b ghost" onclick="jobRun('withdraw',{template:$('#jTpl').checked},this)">Withdrawal email</button><label class="muted"><input type="checkbox" id="jTpl" ${Object.values(S.providers).some(Boolean) ? '' : 'checked disabled'}> plain template, no AI (follow-up, thank-you, withdrawal; used automatically without a provider)</label></div>
      <div class="row"><label class="muted">options for <select id="jOk"><option value="followup">follow-up</option><option value="thanks">thank-you (interviewer, notes above)</option><option value="withdraw">withdrawal</option><option value="outreach">outreach email (person above)</option><option value="checkin">offer check-in</option></select></label>
        <button class="b ghost" onclick="commOptions(this)" title="up to 3 drafts from one AI call, one recommended; the one you use waits in the Inbox for review">Options</button></div>
      <div id="jOpts"></div></div>

${mailGroup(d)}

    <div class="group"><h4>Schedule and decide</h4>
      <div class="row"><input id="jWhen" placeholder="interview: YYYY-MM-DD HH:MM" style="width:200px"><input id="jMin" type="number" min="5" placeholder="minutes (60)" style="width:110px"><button class="b ghost" onclick="jobRun('ics',{when:$('#jWhen').value,minutes:$('#jMin').value||60},this)">Calendar .ics</button></div>
      <div class="row"><input id="oSal" placeholder="base" style="width:90px"><input id="oBon" placeholder="bonus" style="width:90px"><input id="oEq" placeholder="equity" style="width:90px"><input id="oBen" placeholder="benefits" style="width:120px"><input id="oDl" placeholder="deadline" style="width:100px"><input id="oNotes" class="grow" placeholder="notes"><button class="b ghost" onclick="jobRun('offer',{salary:$('#oSal').value,bonus:$('#oBon').value,equity:$('#oEq').value,benefits:$('#oBen').value,deadline:$('#oDl').value,notes:$('#oNotes').value},this)">Evaluate offer</button></div></div>

    <div class="group"><h4>Admin</h4>
      <div class="row"><input id="jNote" class="grow" placeholder="add a note"><button class="b ghost sm" onclick="jobAdmin('note',{text:$('#jNote').value})">note</button></div>
      <div class="row"><input id="jCn" placeholder="contact name" style="width:160px" value="${esc(j.contact_name || '')}"><input id="jCe" class="grow" placeholder="contact email (replies, follow-ups and thank-yous go here)" value="${esc(j.contact_email || '')}"><button class="b ghost sm" onclick="api('/api/jobs/${j.id}/contact',{name:$('#jCn').value,email:$('#jCe').value}).then(r=>{if(r.error)return toast('error: '+r.error,'err');toast('contact saved (also filed under Contacts as recruiter)','ok');openJob(${j.id})})">set contact</button></div>
      <div class="row"><input id="jJd" class="grow" placeholder="set job description: URL or pasted text"><button class="b ghost sm" onclick="jobAdmin('jd',{source:$('#jJd').value})">set JD</button></div>
      <div class="row"><button class="b ghost sm" onclick="jobRun('packet',{},this)">export packet (zip)</button><button class="b danger sm" onclick="if(confirm('Delete job #${j.id}?'))api('/api/jobs/${j.id}/delete',{}).then(()=>{closeDrawer();load()})">delete job</button></div></div>

    <div class="tabs" id="docTabs">${['timeline', 'description', ...docs].map((n, i) => `<button class="${i === 0 ? 'on' : ''}" onclick="showDoc('${n}',this)">${n}</button>`).join('')}</div>
    <pre id="docView"></pre>
    <div class="row"><button class="b ghost sm" onclick="editDoc()">Edit document</button><input id="dAdj" class="grow" placeholder="adjust this document with AI: shorter / warmer / lead with X"><button class="b ghost sm" onclick="adjustDoc(this)">Adjust</button><button class="b ghost sm" onclick="reviewDoc(this)">Review</button></div>
    <textarea id="docEdit" style="display:none; min-height:260px"></textarea><button class="b sm" id="docSave" style="display:none" onclick="saveDoc()">Save document</button>
    <div class="out"><h4 class="muted">AI output</h4><pre id="jOut">(run an action above)</pre></div>`;
  openDrawer('Job details');
  renderCoverage(savedCoverage(d));
  renderBullets(savedBullets(d), false);
  showDoc('timeline', $('#docTabs button'));
}
function showDoc(n, btn) {
  $$('#docTabs button').forEach(b => b.classList.remove('on')); if (btn) btn.classList.add('on');
  const ed = $('#docEdit');  // an open editor belongs to its own tab: hidden elsewhere, back (edits kept) on return
  if (ed) { const mine = ed.dataset.open === '1' && ed.dataset.name === n; ed.style.display = $('#docSave').style.display = mine ? '' : 'none'; }
  $('#docView').textContent = n === 'timeline' ? cur.events.map(e => `${localTs(e.ts)}  ${e.kind.padEnd(16)} ${e.detail || ''}`).join('\n')
    : n === 'description' ? (cur.job.jd || '(no job description on file; set one in Admin)') : cur.docs[n];
}
const DETAILS = ['location', 'remote', 'salary_min', 'salary_max', 'currency', 'excitement', 'match_score', 'deadline', 'posted_at', 'source', 'tags', 'next_action', 'next_action_at'];
function detailsForm(j) {
  const inp = (k, label, attrs = '') => `<label class="fld">${label}<input id="d_${k}" value="${esc(j[k] ?? '')}" ${attrs}></label>`;
  const sel = (k, label, vals) => `<label class="fld">${label}<select id="d_${k}"><option value="">-</option>${vals.map(([v, t]) => `<option value="${v}" ${String(j[k] ?? '') === String(v) ? 'selected' : ''}>${t}</option>`).join('')}</select></label>`;
  return `<div class="group"><h4>Details</h4>
    <div class="row">${inp('location', 'location', 'style="width:150px"')}${sel('remote', 'workplace', [['onsite', 'onsite'], ['hybrid', 'hybrid'], ['remote', 'remote']])}
      ${inp('salary_min', 'salary min', 'type="number" min="0" step="1000" style="width:105px"')}${inp('salary_max', 'salary max', 'type="number" min="0" step="1000" style="width:105px"')}
      ${inp('currency', 'currency', 'maxlength="3" style="width:62px"')}${sel('excitement', 'excitement', [1, 2, 3, 4, 5].map(n => [n, '★'.repeat(n)]))}
      ${inp('match_score', 'match %', 'type="number" min="0" max="100" style="width:72px"')}</div>
    <div class="row">${inp('deadline', 'deadline', 'type="date"')}${inp('posted_at', 'posted', 'type="date"')}${inp('source', 'source', 'style="width:130px"')}${inp('tags', 'tags (comma)', 'style="width:190px"')}</div>
    <div class="row">${inp('next_action', 'next action', 'style="width:260px" placeholder="e.g. ask Sam for a referral"')}${inp('next_action_at', 'due', 'type="date"')}
      <button class="b sm" onclick="saveDetails(${j.id})">Save details</button></div></div>`;
}
async function saveDetails(id) {  // every field is sent; an empty one clears it (the server validates each)
  const r = await api(`/api/jobs/${id}/fields`, Object.fromEntries(DETAILS.map(k => [k, $('#d_' + k).value.trim()])));
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('details saved', 'ok'); await load(); openJob(id);
}
async function jobAdmin(op, body) {  // the drawer's note / set JD: a blank note is refused, a blank JD asks first
  const id = cur.job.id;
  if (op === 'note' && !body.text.trim()) return toast('type a note first', 'err');
  if (op === 'jd' && !body.source.trim() && !confirm('Clear the stored job description of #' + id + '?')) return;
  const r = await api(`/api/jobs/${id}/${op}`, body); if (r.error) return toast('error: ' + r.error, 'err');
  toast(op === 'note' ? 'note added' : body.source.trim() ? 'job description saved' : 'job description cleared', 'ok'); openJob(id);
}
function jobRun(action, extra, btn) {
  const id = cur.job.id;
  run(action, { id, council: $('#jCouncil')?.checked, ...extra }, r => { const t = mailText(r); openJob(id).then(() => { $('#jOut').textContent = t; }); }, btn);
}

/* ---- JD coverage, resume check, file audit (lodestar/ats.py, lodestar/lint.py); all deterministic, no AI ---- */
let COV = null;  // keywords stay in JS; the "not mine" buttons carry only an index
function savedCoverage(d) { try { return JSON.parse(d.docs['coverage.json'] || 'null') || JSON.parse(d.docs['gap.json'] || '{}').coverage || null; } catch (_) { return null; } }
const covBar = (label, c) => `<div class="cov-row"><span>${esc(label)}</span><span class="bar" role="img" aria-label="${esc(label)} ${esc(c.score)}%"><i style="width:${Math.max(0, Math.min(100, Number(c.score) || 0))}%"></i></span><span>${esc(c.score)}% · ${esc(c.matched)}/${esc(c.total)}</span></div>`;
function renderCoverage(cov) {
  COV = cov; const el = $('#jMatch'); if (!el) return;
  if (!cov) { el.innerHTML = ''; return; }
  const c = cov.categories, t = cov.title_match, edu = cov.education_required;
  const names = { hard: 'hard skills', soft: 'soft skills', title: 'job title', education: 'education', other: 'other posting terms' };
  el.innerHTML = `<div class="row"><b class="cov-score">${esc(cov.score)}%</b><span class="muted">JD coverage</span></div>`
    + Object.entries(names).filter(([k]) => c[k].total).map(([k, l]) => covBar(l, c[k])).join('')
    + (t ? `<div class="muted">title "${esc(t.title)}": ${t.found ? 'found in your resume' : 'not found in your resume'}</div>` : '')
    + (edu.length ? `<div class="muted">posting names ${esc(edu.join(', '))}: ${c.education.matched ? 'covered by your resume' : 'not found in your resume'}</div>` : '')
    + (cov.stuffing.length ? `<div class="warnbox">Repeated far more often than the posting does (can read as keyword stuffing): ${esc(cov.stuffing.join(', '))}</div>` : '')
    + (cov.keywords.length ? `<table class="kw"><thead><tr><th>keyword</th><th>kind</th><th>in posting</th><th>in resume</th><th></th></tr></thead><tbody>`
      + cov.keywords.map((k, i) => `<tr class="${k.skipped ? 'skip' : k.matched ? 'hit' : 'miss'}"><td>${esc(k.term)}</td><td>${esc(k.kind)}</td><td>${esc(k.jd_count)}×</td>
        <td>${k.skipped ? 'not mine' : k.matched ? esc(k.resume_count) + '× ✓' : 'missing'}</td>
        <td><button class="b ghost sm" onclick="skipTerm(${i})" aria-label="${esc((k.skipped ? 'count again: ' : 'not mine: ') + k.term)}">${k.skipped ? 'undo' : 'not mine'}</button></td></tr>`).join('')
      + '</tbody></table>' : '<div class="muted">no known keywords found in the posting</div>')
    + `<div class="muted">${esc(cov.note)}</div>`;
}
function syncScore(c) {  // coverage rewrote match_score on the server: keep Save details from writing back a stale one
  const el = $('#d_match_score'); if (el && c) el.value = el.defaultValue = String(c.score);
}
function jobMatch(btn) { run('match', { id: cur.job.id }, r => { cur.docs = r.docs; renderCoverage(r.coverage); syncScore(r.coverage); toast('JD coverage ' + r.coverage.score + '%', 'ok'); }, btn); }
async function skipTerm(i) {  // "not mine": the keyword leaves the score for this job; again to undo
  const k = COV && COV.keywords[i]; if (!k || !cur) return;
  const r = await api(`/api/jobs/${cur.job.id}/skip`, { term: k.term });
  if (r.error) return toast('error: ' + r.error, 'err');
  renderCoverage(r.coverage); syncScore(r.coverage); toast(`${k.skipped ? 'counting' : 'not counting'} "${k.term}" · coverage ${r.coverage.score}%`, 'ok'); load();
}
function issuesHtml(r) {
  return ['high', 'medium', 'low', 'info'].map(s => [s, r.issues.filter(i => i.severity === s)]).filter(([, l]) => l.length)
    .map(([s, l]) => `<div class="iss ${s}"><b>${s} (${l.length})</b><ul>${l.map(i => `<li>${i.line ? 'line ' + esc(i.line) + ': ' : ''}${esc(i.text)}<div class="muted">${esc(i.hint)}</div></li>`).join('')}</ul></div>`).join('')
    || '<div class="muted">no issues found</div>';
}
const lintHtml = r => `<h4 class="muted">Resume check</h4>${issuesHtml(r)}<div class="muted">score ${esc(r.score)}/100 (secondary: the list is what to fix)</div>`;
const auditHtml = r => `<h4 class="muted">File audit: ${esc(r.file)}</h4>${issuesHtml(r)}<div class="muted">${esc(r.note)}</div><details><summary class="muted">What a parser sees</summary><pre>${esc(r.text || '(no text extracted)')}</pre></details>`;
function jobLint(btn) {  // the open resume.md, unsaved edits included
  const editing = $('#docEdit').style.display !== 'none' && $('#docEdit').dataset.name === 'resume.md';
  const text = editing ? $('#docEdit').value : cur.docs['resume.md'];
  if (!(text || '').trim()) return toast('no tailored resume yet: Tailor resume first, then Check it', 'err');
  run('lint', { text }, r => { $('#jCheck').innerHTML = lintHtml(r); }, btn);
}

/* ---- bullet-level tailoring and PDF export (resume.tailor_bullets / apply_bullets / export_pdf) ---- */
let BUL = null;  // proposals stay in JS; the checkboxes carry only an index
const baseOpt = () => $('#jBase')?.value || '';
function savedBullets(d) { try { return JSON.parse(d.docs['bullets.json'] || 'null'); } catch (_) { return null; } }
function marked(t, spans) {  // escape every slice; only the server's offsets for added keywords become <mark>
  let out = '', at = 0;
  for (const [s, e] of (spans || []).map(x => [Number(x[0]), Number(x[1])]).sort((a, b) => a[0] - b[0])) {
    if (!(s >= at && e > s && e <= t.length)) continue;
    out += esc(t.slice(at, s)) + '<mark>' + esc(t.slice(s, e)) + '</mark>'; at = e;
  }
  return out + esc(t.slice(at));
}
function renderBullets(data, open = true) {
  BUL = data; const el = $('#jBullets'); if (!el) return;
  if (!data) { el.innerHTML = ''; return; }
  const rows = data.proposals, flagged = rows.filter(r => r.flags.length).length;
  el.innerHTML = `<details ${open ? 'open' : ''}><summary class="muted">Tailor by bullet: ${rows.filter(r => r.changed).length} of ${rows.length} bullets rewritten, ${flagged} flagged (${esc(data.created)})</summary>
    <table class="kw bul"><thead><tr><th>#</th><th>original</th><th>proposed</th><th>accept</th></tr></thead><tbody>`
    + rows.map((r, i) => `<tr class="${r.flags.length ? 'flag' : ''}"><td>${esc(r.id)}</td><td><div class="muted">${esc(r.role)}</div>${esc(r.original)}</td>
      <td>${!r.changed ? '<span class="muted">unchanged</span>' : r.drop ? '<i>drop this bullet</i>' : marked(r.proposed, r.marks)}
        ${r.reason ? `<div class="muted">${esc(r.reason)}</div>` : ''}
        ${r.unsupported.length ? `<div class="flagtxt">unsupported: ${esc(r.unsupported.join(', '))} (not found in your profile or bank)</div>` : ''}
        ${r.new_numbers.length ? `<div class="flagtxt">new number: ${esc(r.new_numbers.join(', '))} (not in the original bullet)</div>` : ''}</td>
      <td>${r.changed ? `<input type="checkbox" id="bul${i}" ${r.accepted ? 'checked' : ''} aria-label="accept bullet ${esc(r.id)}">` : ''}</td></tr>`).join('')
    + `</tbody></table><div class="row"><button class="b ghost sm" onclick="bulletsUnflagged()">Accept all unflagged</button><button class="b sm" onclick="buildBullets(this)">Build resume</button>
      <span class="muted">Unchecked rows keep the original text; bullets follow the suggested order within each role. The previous resume.md is kept in history/.</span></div></details>`;
}
function bulletsUnflagged() { BUL.proposals.forEach((r, i) => { const c = $('#bul' + i); if (c) c.checked = !r.flags.length; }); }
function tailorBullets(btn) {
  run('bullets', { id: cur.job.id, base: baseOpt() }, r => { cur.docs = r.docs; renderBullets(r); toast('bullet proposals ready: review, then Build resume', 'ok'); }, btn);
}
function buildBullets(btn) {
  const id = cur.job.id, accept = BUL.proposals.filter((r, i) => $('#bul' + i)?.checked).map(r => r.id);
  run('bullets_apply', { id, accept }, r => { toast(`resume built: ${r.accepted.length} rewrite(s), coverage ${r.coverage.before} -> ${r.coverage.after}`, 'ok'); openJob(id); }, btn);
}
function exportPdf(btn) {
  const id = cur.job.id;
  if (!cur.docs['resume.md']) return toast('no tailored resume yet: Tailor resume first, then Export PDF', 'err');
  run('export_pdf', { id }, r => {
    const t = `${r.method === 'html' ? 'print page (opened in your browser)' : 'PDF'}: ${r.path}\n${r.note}` + (r.tried.length ? '\n\ntried first:\n' + r.tried.join('\n') : '');
    toast(r.method === 'html' ? 'opened a print page: Save as PDF from there' : 'PDF written with ' + (r.method === 'word' ? 'Microsoft Word' : 'LibreOffice'), 'ok');
    openJob(id).then(() => { $('#jOut').textContent = t; });
  }, btn);
}

/* ---- people: warm paths, job links, contacts tab and drawer (lodestar/contacts.py) ---- */
const roleOpt = (sel = 'other') => (S.contact_roles || []).map(r => `<option value="${esc(r)}" ${r === sel ? 'selected' : ''}>${esc(r.replace('_', ' '))}</option>`).join('');
const people = w => (w || []).map(p => p.name + (p.position ? ' (' + p.position + ')' : '')).join(', ');
const warmChip = w => w && w.length ? `<span class="chip warm" title="${esc(people(w))}">you know ${w.length} ${w.length === 1 ? 'person' : 'people'} here</span>` : '';
function peopleGroup(d) {
  const linked = new Set(d.people.map(p => p.id)), others = d.warm.filter(p => !linked.has(p.id)), id = d.job.id;
  const who = p => `<a href="#" onclick="openContact(${Number(p.id)});return false">${esc(p.name)}</a>${p.position ? ` <span class="muted">${esc(p.position)}</span>` : ''}`;
  const ask = p => `<button class="b ghost sm" title="draft a referral ask: an email into the Inbox (always reviewed) when they have an address, else a LinkedIn note" onclick="jobRun('referral',{contact_id:${Number(p.id)}},this)">Ask for referral</button><button class="b ghost sm" title="up to 3 referral asks, one recommended (shown under Communicate)" onclick="draftOptions('referral',{id:${id},contact_id:${Number(p.id)}},'jOpts',this)">options</button>`;
  return `<div class="group"><h4>People</h4>
    ${d.people.map(p => `<div class="row">${who(p)}<span class="pill">${esc(p.role.replace('_', ' '))}</span>${p.email ? `<span class="muted">${esc(p.email)}</span>` : ''}${ask(p)}
      <button class="b ghost sm" onclick="contactOp(${Number(p.id)},'unlink',{job_id:${id}})">unlink</button></div>`).join('') || '<div class="muted">nobody linked to this job yet</div>'}
    ${d.warm.length ? `<div class="row"><span class="chip warm">you know ${d.warm.length} ${d.warm.length === 1 ? 'person' : 'people'} here</span></div>` : ''}
    ${others.map(p => `<div class="row">${who(p)}<select id="jRole${Number(p.id)}" aria-label="role for ${esc(p.name)}">${roleOpt()}</select>
      <button class="b ghost sm" onclick="contactOp(${Number(p.id)},'link',{job_id:${id},role:$('#jRole${Number(p.id)}').value})">link</button>${ask(p)}</div>`).join('')}</div>`;
}
async function contactOp(cid, op, body, msg) {  // edit / link / unlink / delete; refreshes whichever drawer is open
  const r = await api(`/api/contacts/${cid}/${op}`, body || {});
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(msg || ({ link: 'linked', unlink: 'unlinked', edit: 'saved', delete: 'contact removed' }[op]), 'ok');
  if (op === 'delete') closeDrawer(); else if (CT) openContact(CT.contact.id); else if (cur) openJob(cur.job.id);
  loadContacts(); load();
}
let CTS = [];  // contacts list (GET /api/contacts); markup carries only ids
const CT_KEY = 'ls_contacts_view';
let CV = { key: 'name', dir: 1 };
try { Object.assign(CV, JSON.parse(localStorage.getItem(CT_KEY) || '{}')); } catch (_) { /* storage blocked or corrupt: defaults */ }
const CT_COLS = [['name', 'Name'], ['company', 'Company'], ['position', 'Position'], ['last_touch', 'Last touch'], ['next_touch', 'Next touch'], ['jobs', 'Linked jobs']];
const isDue = c => c.next_touch && c.next_touch <= new Date().toLocaleDateString('en-CA') && !(c.last_touch && c.last_touch >= c.next_touch);
async function loadContacts() { const r = await api('/api/contacts'); if (r.error) return toast('error: ' + r.error, 'err'); CTS = r.contacts; renderContacts(); }
function sortContacts(k) { if (CV.key === k) CV.dir = -CV.dir; else { CV.key = k; CV.dir = k === 'jobs' || k === 'last_touch' ? -1 : 1; } try { localStorage.setItem(CT_KEY, JSON.stringify(CV)); } catch (_) { /* storage blocked */ } renderContacts(); }
function renderContacts() {
  const q = ($('#ctQ').value || '').trim().toLowerCase(), dueOnly = $('#ctDue').checked, MAX = 500;
  const rows = CTS.filter(c => (!q || [c.name, c.company, c.position, c.email].join(' ').toLowerCase().includes(q)) && (!dueOnly || isDue(c)))
    .sort((a, b) => { const x = a[CV.key] ?? null, y = b[CV.key] ?? null; if (x === y) return 0; if (x == null || x === '') return 1; if (y == null || y === '') return -1; return (typeof x === 'string' ? x.localeCompare(y) : x - y) * CV.dir; });
  $('#ctN').textContent = `${rows.length} of ${CTS.length}` + (rows.length > MAX ? ` (first ${MAX} shown: filter to narrow)` : '');
  const sortAttr = k => CV.key === k ? (CV.dir > 0 ? 'ascending' : 'descending') : 'none';
  $('#ctTable').innerHTML = CTS.length ? `<table class="jobs"><thead><tr>` + CT_COLS.map(([k, l]) => `<th aria-sort="${sortAttr(k)}"><button class="th" onclick="sortContacts('${k}')">${l}${CV.key === k ? (CV.dir > 0 ? ' ▲' : ' ▼') : ''}</button></th>`).join('') + '</tr></thead><tbody>'
    + rows.slice(0, MAX).map(c => `<tr class="${isDue(c) ? 'due' : ''}"><td><a href="#" onclick="openContact(${Number(c.id)});return false">${esc(c.name)}</a></td><td>${esc(c.company)}</td><td>${esc(c.position)}</td>
      <td>${esc(c.last_touch)}</td><td>${esc(c.next_touch)}${isDue(c) ? ' <span class="chip due">due</span>' : ''}</td><td title="${esc(c.job_list)}">${c.jobs ? esc(c.job_list) : ''}</td></tr>`).join('')
    + '</tbody></table>' + (rows.length ? '' : '<div class="empty">No contacts match.</div>')
    : '<div class="empty">No contacts yet. Add one above, import your LinkedIn connections, or set a job\'s contact in its drawer.</div>';
}
async function addContact() {
  const body = { name: $('#ctName').value, email: $('#ctEmail').value, company: $('#ctCo').value, position: $('#ctPos').value };
  if (!body.name.trim()) return toast('type a name first', 'err');
  const r = await api('/api/contacts', body); if (r.error) return toast('error: ' + r.error, 'err');
  ['#ctName', '#ctEmail', '#ctCo', '#ctPos'].forEach(s => { $(s).value = ''; }); toast('contact added', 'ok'); await loadContacts(); load(); openContact(r.id);
}
function importContacts(btn) {
  const f = $('#ctFile').files[0]; if (!f) return toast('choose your LinkedIn .zip or Connections.csv first', 'err');
  const rd = new FileReader();
  rd.onload = () => run('contacts_import', { name: f.name, data: rd.result.split(',')[1] }, r => {
    toast(`${r.rows} connection(s): ${r.added} added, ${r.updated} updated, ${r.skipped} unchanged or skipped`, 'ok'); loadContacts();
  }, btn);
  rd.readAsDataURL(f);
}
const CT_FIELDS = [['name', 'name'], ['email', 'email'], ['phone', 'phone'], ['linkedin_url', 'LinkedIn URL'], ['company', 'company'], ['position', 'position'], ['how_met', 'how you met']];
async function openContact(id) {
  const d = await api('/api/contacts/' + id); if (d.error) return toast(d.error, 'err');
  cur = null; CT = d; const c = d.contact, today = new Date().toLocaleDateString('en-CA');
  $$('.card.sel').forEach(x => x.classList.remove('sel'));
  $('#drawer').innerHTML = `
    <div class="head"><b>${esc(c.name)}</b><span class="muted">${esc([c.position, c.company].filter(Boolean).join(' at '))} · contact #${Number(c.id)}</span>
      ${safeUrl(c.linkedin_url) ? `<a href="${esc(c.linkedin_url)}" target="_blank" rel="noopener">LinkedIn ↗</a>` : ''}
      <button class="b ghost sm close" onclick="closeDrawer()" aria-label="Close contact details">✕</button></div>
    <div class="muted">source: ${esc(c.source || 'manual')} · added ${esc(localTs(c.created_at, 10))}</div>
    <div class="group"><h4>Details</h4>
      <div class="row">${CT_FIELDS.map(([k, l]) => `<label class="fld">${l}<input id="c_${k}" value="${esc(c[k] ?? '')}" style="width:${k === 'linkedin_url' || k === 'how_met' ? 260 : 170}px"></label>`).join('')}</div>
      <label class="fld">notes<textarea id="c_notes" style="min-height:90px">${esc(c.notes || '')}</textarea></label>
      <div class="row"><label class="fld">last touch<input id="c_last_touch" type="date" value="${esc(c.last_touch || '')}"></label>
        <label class="fld">next touch<input id="c_next_touch" type="date" value="${esc(c.next_touch || '')}"></label>
        <button class="b sm" onclick="saveContact()">Save</button>
        <button class="b ghost sm" title="sets last touch to today" onclick="contactOp(${Number(c.id)},'edit',{last_touch:'${today}'},'last touch: today')">Touched today</button>
        <button class="b danger sm" onclick="if(confirm('Remove this contact? Linked jobs stay.'))contactOp(${Number(c.id)},'delete',{})">delete</button></div>
      <div class="muted">Mail from or to their exact address updates last touch. A next touch puts them on the Today list once it comes, until you are in touch again; nothing is drafted or sent for it.</div></div>
    <div class="group"><h4>Linked jobs</h4>
      ${d.jobs.map(j => `<div class="row"><a href="#" onclick="go('board');openJob(${Number(j.id)});return false">#${Number(j.id)} ${esc(j.company)} - ${esc(j.title)}</a><span class="pill">${esc(j.role.replace('_', ' '))}</span><span class="muted">${esc(j.status)}</span>
        <button class="b ghost sm" onclick="contactOp(${Number(c.id)},'unlink',{job_id:${Number(j.id)}})">unlink</button></div>`).join('') || '<div class="muted">not linked to any job</div>'}
      <div class="row"><select id="cJobSel" aria-label="Job to link">${S.jobs.map(j => `<option value="${Number(j.id)}">#${Number(j.id)} ${esc(j.company)} - ${esc(j.title)}</option>`).join('')}</select>
        <select id="cRoleSel" aria-label="Role">${roleOpt()}</select><button class="b ghost sm" onclick="if($('#cJobSel').value)contactOp(${Number(c.id)},'link',{job_id:$('#cJobSel').value,role:$('#cRoleSel').value})">link to job</button></div></div>
    <div class="group"><h4>Recent activity with ${esc(c.email || 'them')}</h4>
      ${c.email ? (d.events.map(e => `<div class="muted">${esc(localTs(e.ts))} · #${Number(e.job_id)} ${esc(e.company || '')} · ${esc(e.kind)}: ${esc(e.detail)}</div>`).join('') || '<div class="muted">no timeline entries mention this address yet</div>') : '<div class="muted">add an email address to see mail sent to them</div>'}</div>`;
  openDrawer('Contact details');
}
function saveContact() {  // every field is sent; an empty one clears it (the server validates each)
  const body = Object.fromEntries([...CT_FIELDS.map(([k]) => k), 'notes', 'last_touch', 'next_touch'].map(k => [k, $('#c_' + k).value]));
  contactOp(CT.contact.id, 'edit', body, 'contact saved');
}

/* ---- interview rounds, question bank, story prompt (lodestar/interview.py) ---- */
let ROUNDS = [], STRESS = { stressed: [], missing: [] };  // rows stay in JS; buttons carry only an index
const R_FIELDS = ['round', 'kind', 'at', 'interviewers', 'notes', 'questions_asked', 'outcome'];
function roundsGroup(d) {
  ROUNDS = d.rounds || []; STRESS = d.stress || STRESS;
  const st = STRESS, bank = d.bank || [];
  const prompt = st.stressed.length ? `<div class="muted">This posting stresses ${esc(st.stressed.join(', '))}.${st.missing.length
    ? ` No story tagged ${esc(st.missing.join(', '))} yet: worth preparing one before the interview? <button class="b ghost sm" onclick="newStory(STRESS.missing[0])">Add a story</button>`
    : ' You have a story tagged with each.'}</div>` : '';
  const rows = ROUNDS.map((r, i) => `<div class="row"><b>round ${Number(r.round)}</b><span class="pill">${esc(r.kind)}</span><span>${esc(r.at || 'no date')}</span>
      <span class="pill ${r.outcome === 'passed' ? 'ok' : r.outcome === 'rejected' ? 'warn' : ''}">${esc(r.outcome)}</span><span class="muted">${esc(r.interviewers || '')}</span>
      <button class="b ghost sm" onclick="editRound(${i})">edit</button><button class="b ghost sm" onclick="deleteRound(${i})">delete</button></div>
    ${r.questions_asked ? `<ul class="muted qs">${r.questions_asked.split('\n').map(q => `<li>${esc(q)}</li>`).join('')}</ul>` : ''}${r.notes ? `<div class="muted" style="white-space:pre-wrap">${esc(r.notes)}</div>` : ''}`).join('')
    || '<div class="muted">no rounds logged yet</div>';
  return `<div class="group"><h4>Interview rounds</h4>${prompt}${rows}
    <details id="rForm"><summary class="muted">Log a round</summary><input type="hidden" id="r_id">
      <div class="row"><label class="fld">round<input id="r_round" type="number" min="1" max="50" placeholder="next" style="width:70px"></label>
        <label class="fld">kind<select id="r_kind">${opt(S.round_kinds, 'other')}</select></label>
        <label class="fld">when<input id="r_at" placeholder="YYYY-MM-DD HH:MM" style="width:150px"></label>
        <label class="fld">outcome<select id="r_outcome">${opt(S.round_outcomes, 'pending')}</select></label>
        <label class="fld">interviewers<input id="r_interviewers" style="width:170px"></label></div>
      <label class="fld">questions you were asked, one per line<textarea id="r_questions_asked" style="min-height:90px"></textarea></label>
      <label class="fld">notes<textarea id="r_notes" style="min-height:60px"></textarea></label>
      <div class="row"><button class="b sm" onclick="saveRound()">Save round</button><span class="muted" id="rMode"></span></div></details>
    ${bank.length ? `<details><summary class="muted">Question bank: ${bank.length} question(s) logged at this company or for similar titles</summary>
      <ul class="muted qs">${bank.map(x => `<li>${esc(x.q)} <span class="pill">${esc(x.source)}</span>${esc(x.where)}</li>`).join('')}</ul></details>` : ''}
    <div class="muted">A round with a time reminds you like a calendar file (upcoming interviews, Today). Prep packs and mock interviews ask the questions logged here first.</div></div>`;
}
function editRound(i) {
  const r = ROUNDS[i]; if (!r) return;
  $('#r_id').value = r.id; R_FIELDS.forEach(k => { $('#r_' + k).value = r[k] ?? ''; });
  $('#rMode').textContent = 'editing round ' + Number(r.round); $('#rForm').open = true; $('#r_at').focus();
}
async function saveRound() {
  const id = Number($('#r_id').value), body = Object.fromEntries(R_FIELDS.map(k => [k, $('#r_' + k).value]));
  const r = await api(id ? `/api/rounds/${id}/edit` : `/api/jobs/${cur.job.id}/rounds`, body);
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(id ? 'round saved' : 'round logged', 'ok'); await load(); openJob(cur.job.id);
}
async function deleteRound(i) {
  const r = ROUNDS[i]; if (!r || !confirm(`Delete round ${Number(r.round)} and the questions logged with it?`)) return;
  const res = await api(`/api/rounds/${Number(r.id)}/delete`, {}); if (res.error) return toast('error: ' + res.error, 'err');
  toast('round deleted', 'ok'); await load(); openJob(cur.job.id);
}

/* ---- STAR stories: rows of the answer bank with structured fields (lodestar/interview.py) ---- */
const ST_FIELDS = ['title', 'situation', 'task', 'action', 'result', 'metrics'];
const stIn = k => $('#st' + k[0].toUpperCase() + k.slice(1));
function renderStories() {
  if (!$('#stComps').children.length) $('#stComps').innerHTML = S.competencies.map(c => `<label class="muted"><input type="checkbox" value="${esc(c)}"> ${esc(c)}</label>`).join('');
  const have = new Set(S.stories.flatMap(s => s.competencies)), none = S.competencies.filter(c => !have.has(c));
  $('#storyList').innerHTML = (S.stories.length && none.length ? `<div class="muted">no story tagged yet: ${esc(none.join(', '))}</div>` : '') + `<div class="list">`
    + (S.stories.map((s, i) => `<div><b>${esc(s.title)}</b> ${s.competencies.map(c => `<span class="pill">${esc(c)}</span>`).join('')}${s.missing.length ? `<span class="chip stale">incomplete: no ${esc(s.missing.join(', '))}</span>` : ''}
      <button class="b ghost sm" onclick="editStory(${i})">edit</button><button class="b ghost sm" onclick="deleteStory(${i})">remove</button>
      <div class="muted" style="white-space:pre-wrap">${esc(['situation', 'task', 'action', 'result', 'metrics'].filter(k => s[k]).map(k => k[0].toUpperCase() + k.slice(1) + ': ' + s[k]).join('\n'))}</div></div>`).join('')
      || '<div class="empty">No stories yet. Write one above, or use "Save as story" on an idea of the stories topic (Ideas tab).</div>') + '</div>';
}
function clearStory() { $('#stId').value = ''; ST_FIELDS.forEach(k => { stIn(k).value = ''; }); $$('#stComps input').forEach(e => { e.checked = false; }); $('#stHint').textContent = ''; }
function editStory(i) {
  const s = S.stories[i]; if (!s) return;
  clearStory(); $('#stId').value = s.id; ST_FIELDS.forEach(k => { stIn(k).value = s[k] || ''; });
  $$('#stComps input').forEach(e => { e.checked = s.competencies.includes(e.value); });
  $('#stHint').textContent = 'editing story #' + Number(s.id); $('#storyPanel').scrollIntoView(); stIn('title').focus();
}
function newStory(comp) { go('answers'); clearStory(); $$('#stComps input').forEach(e => { e.checked = e.value === comp; }); $('#storyPanel').scrollIntoView(); stIn('title').focus(); }
async function saveStory() {
  const body = Object.fromEntries(ST_FIELDS.map(k => [k, stIn(k).value]));
  body.competencies = $$('#stComps input:checked').map(e => e.value);
  if ($('#stId').value) body.id = Number($('#stId').value);
  const r = await api('/api/stories', body); if (r.error) return toast('error: ' + r.error, 'err');
  $('#stId').value = r.id; $('#stHint').textContent = 'editing story #' + Number(r.id); toast('story saved', 'ok'); load();
}
async function deleteStory(i) {
  const s = S.stories[i]; if (!s || !confirm(`Remove the story "${s.title}"?`)) return;
  const r = await api(`/api/answers/${Number(s.id)}`, {}); if (r.error) return toast('error: ' + r.error, 'err');
  if (Number($('#stId').value) === s.id) clearStory();
  toast('story removed', 'ok'); load();
}
async function storyFromIdea(id) {
  const r = await api('/api/stories', { from_idea: id }); if (r.error) return toast('error: ' + r.error, 'err');
  await load(); go('answers'); const k = S.stories.findIndex(s => s.id === r.id); if (k >= 0) editStory(k);
  toast('saved as a story: fill in the task, action and result in your own words', 'ok');
}

/* ---- board add ---- */
async function addJob() {
  const r = await api('/api/jobs', { company: $('#nCo').value, title: $('#nTi').value, jd: $('#nJd').value });
  if (r.error) return toast(r.error, 'err');
  $('#nCo').value = $('#nTi').value = $('#nJd').value = ''; await load(); openJob(r.id);
}

/* ---- inbox ---- */
function renderInbox() {
  // the 60 s refresh re-renders the inbox: carry over draft edits, or Approve would send the original AI text
  const edited = {}; $$('#inboxList input[id], #inboxList textarea[id]').forEach(e => { if (e.value !== e.defaultValue) edited[e.id] = e.value; });
  const fe = document.activeElement && document.activeElement.closest('#inboxList') ? document.activeElement : null;
  const focused = fe && { id: fe.id, s: fe.selectionStart, e: fe.selectionEnd, top: fe.scrollTop };  // keep the caret where it was
  $('#inboxList').innerHTML = S.pending.map(r => {
    const p = r.payload, mail = r.kind === 'send_email';
    return `<div class="item"><div class="hd"><b>#${r.id}</b><span class="pill">${r.tool}</span><span class="pill">${r.kind}</span>${p.unverified ? '<span class="pill warn" title="the mail this answers was not authenticated or not tied to the job: check the address before you send; sending it moves no job">unverified sender</span>' : ''}${esc(r.summary)}<span class="muted">${esc(localTs(r.ts, 16))}</span></div>
      ${mail ? `<div class="row"><input id="to${r.id}" value="${esc(p.to)}" style="width:260px"><input id="sub${r.id}" class="grow" value="${esc(p.subject)}"></div><textarea id="body${r.id}">${esc(p.body)}</textarea>${'chosen_time' in p ? `<div class="row"><input id="ct${r.id}" value="${esc(p.chosen_time || '')}" placeholder="YYYY-MM-DD HH:MM" style="width:170px"><span class="muted">interview slot this reply accepts; an .ics is written on send. Empty = no .ics.</span></div>` : ''}`
        : `<textarea id="js${r.id}" spellcheck="false" style="font-family:monospace">${esc(JSON.stringify(p, null, 2))}</textarea>`}
      ${mail && r.job_id ? `<div class="row" id="att${r.id}">${attHtml(r)}</div>` : ''}
      ${mail && hasAI() ? `<div class="row"><button class="b ghost sm" onclick="draftOptions('pending',{pending_id:${r.id}},'p${r.id}',this)" title="up to 3 alternatives (one AI call); Use this changes only the subject and body">Options</button>${HOWS.map(([k, l]) => `<button class="b ghost sm" onclick="rewritePending(${r.id},'${k}',this)">${l}</button>`).join('')}<button class="b ghost sm" onclick="rewritePending(${r.id},'',this)">custom…</button></div>${optsHtml('p' + r.id)}` : ''}
      ${r.result ? `<div class="row"><span class="pill warn">${esc(r.result)}</span></div>` : ''}
      <div class="row"><button class="b" onclick="decide(${r.id},'approve',${mail})">${mail && r.result ? 'Retry send' : 'Approve' + (mail ? ' and send' : '')}</button><button class="b ghost" onclick="decide(${r.id},'reject',false)">Reject</button></div></div>`;
  }).join('') || '<div class="empty">Inbox empty. Automatic actions appear here when a tool is enabled but not set to auto.</div>';
  for (const [id, v] of Object.entries(edited)) { const e = document.getElementById(id); if (e) e.value = v; }
  const back = focused && document.getElementById(focused.id);
  if (back) { back.focus(); try { back.setSelectionRange(focused.s, focused.e); } catch (_) { /* not a text field */ } back.scrollTop = focused.top; }
  attFetch();
  $('#decidedList').innerHTML = S.decided.map(r => `<div>#${r.id} <b>${r.status}</b> ${esc(r.summary)} <span class="muted">${esc((r.result || '').slice(0, 140))}</span></div>`).join('') || '<div class="muted">nothing decided yet</div>';
  renderUnmatched();
}
async function decide(id, op, mail) {
  let body = op === 'approve' && mail ? { edits: { to: $('#to' + id).value, subject: $('#sub' + id).value, body: $('#body' + id).value } } : {};
  const js = op === 'approve' && !mail && $('#js' + id);  // other kinds: the payload is edited as JSON
  if (js) { try { body = { edits: JSON.parse(js.value) }; } catch (e) { return toast('not valid JSON: ' + e.message, 'err'); }
    if (!body.edits || typeof body.edits !== 'object' || Array.isArray(body.edits)) return toast('the payload must be a JSON object', 'err'); }
  const ct = $('#ct' + id); if (body.edits && ct) body.edits.chosen_time = ct.value.trim() || null;
  if (body.edits && mail && ATT[id]) body.edits.attachments = ATT[id];  // re-checked by the server before anything is sent
  const r = await api(`/api/approvals/${id}/${op}`, body);
  toast(r.error ? 'error: ' + r.error : op === 'approve' ? `#${id} ${r.status}: ${r.result || ''}` : `#${id} rejected`, r.error ? 'err' : 'ok'); load();
}

/* ---- attachments on Inbox email cards: names only. The server allows resume / cover letter (.pdf, .docx) and the job's
   attach/ folder, re-checks them before the claim and at send, and never serves a file's bytes to this page ---- */
const ATT = {}, JFILES = {};  // pending id -> chosen names (kept across the 60 s re-render); job id -> attachable files
function attHtml(r) {
  const id = Number(r.id), jid = Number(r.job_id), files = JFILES[jid] || [];
  const names = ATT[id] || (ATT[id] = [...(Array.isArray(r.payload.attachments) ? r.payload.attachments : [])]);
  const size = n => { const f = files.find(x => x.name === n); return f ? ' · ' + kb(f.size) : ''; };
  const add = files.map((f, i) => [f, i]).filter(([f]) => !names.includes(f.name));
  return `<span class="muted">Attachments:</span> ` + (names.map((n, k) => `<span class="pill">${esc(n + size(n))} <button class="b ghost sm" aria-label="remove attachment" onclick="attRemove(${id},${k})">×</button></span>`).join(' ') || '<span class="muted">none</span>')
    + (add.length ? ` <select aria-label="attach a file from this job's folder" onchange="attAdd(${id},${jid},this.value)"><option value="">Add from this job's files…</option>${add.map(([f, i]) => f.blocked ? `<option value="" disabled title="${esc(f.blocked)}">${esc(f.name)} · can't attach: ${esc(f.blocked.slice(0, 90))}</option>` : `<option value="${i}">${esc(f.name + ' · ' + kb(f.size))}</option>`).join('')}</select>` : '')
    + ` <button class="b ghost sm" title="Put a portfolio or transcript here to attach it (pdf, docx, png, jpg)" onclick="openJobFolder(${jid},'attach')">Show attach folder</button>`
    + (r.payload.unverified && names.length ? ' <span class="pill warn">the recipient is not verified: check the address before sending a file</span>' : '');
}
function attPaint(id) { const r = S.pending.find(x => x.id === id), el = $('#att' + id); if (r && el) el.innerHTML = attHtml(r); }
async function attFetch() {  // once per render per job: the folder may have changed since
  const jobs = [...new Set(S.pending.filter(r => r.kind === 'send_email' && r.job_id).map(r => Number(r.job_id)))];
  await Promise.all(jobs.map(async j => { const r = await api(`/api/jobs/${j}/files`); JFILES[j] = r.files || []; }));
  S.pending.filter(r => r.kind === 'send_email' && r.job_id).forEach(r => attPaint(r.id));
}
function attAdd(id, jid, i) { if (i === '') return; const f = (JFILES[jid] || [])[Number(i)]; if (f && !f.blocked && !(ATT[id] ||= []).includes(f.name)) ATT[id].push(f.name); attPaint(id); }
function attRemove(id, k) { (ATT[id] || []).splice(k, 1); attPaint(id); }
async function openJobFolder(jid, sub) {  // reveals the folder in Explorer; Lodestar never opens a file in it
  const r = await api('/api/open_folder', { which: 'job', id: Number(jid), sub }); if (r.error) toast('error: ' + r.error, 'err');
}

/* ---- emailed sign-in codes (lodestar/codes.py): memory only on the server, shown here with the sender's domain ---- */
let CODES = [];
async function codesLoad() { const r = await api('/api/codes'); if (!r.error) codesPaint(r.codes || []); }
async function codesCheck(btn) {
  btn.disabled = true; btn.textContent = 'checking…';
  try { const r = await api('/api/codes/check', {}); if (r.error) return toast('error: ' + r.error, 'err'); codesPaint(r.codes || []); if (!CODES.length) toast('no code in the last 15 minutes', 'ok'); }
  finally { btn.disabled = false; btn.textContent = 'Check for a code now'; }
}
function codesPaint(list) {
  if (list.length > CODES.length) $('#codesPanel').open = true;  // a new code opens the panel; you may close it again
  CODES = list;
  $('#codesN').textContent = list.length ? `(${list.length})` : '';
  $('#codesList').innerHTML = list.map((c, i) => `<div class="item"><div class="row"><code id="code${i}" style="font-size:22px;letter-spacing:2px">${esc(c.code)}</code>
      <button class="b sm" onclick="codeCopy(${i})">Copy</button><span>from <b style="font-size:15px">${esc(c.domain)}</b></span><span class="muted">${esc(c.subject)} · expires in ${Math.max(1, Math.ceil(Number(c.expires_s) / 60))} min</span>
      <button class="b ghost sm" onclick="codeDismiss(${i})">Dismiss</button></div>
    <div class="muted">Enter this only on the site you are signing in to right now. Never read it out or send it to anyone.</div></div>`).join('') || '<div class="muted">no code in the last 15 minutes</div>';
}
async function codeCopy(i) {
  const c = CODES[i]; if (!c) return;
  try { await navigator.clipboard.writeText(c.code); toast('copied', 'ok'); }
  catch (_) { const r = document.createRange(); r.selectNodeContents($('#code' + i)); const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r); toast('selected: press Ctrl+C', 'ok'); }
}
async function codeDismiss(i) { const c = CODES[i]; if (!c) return; await api(`/api/codes/${encodeURIComponent(c.id)}/dismiss`, {}); codesLoad(); }
setInterval(() => { if ($('#codesPanel').open && CODES.length) codesLoad(); }, 20000);

/* ---- mail: Unmatched mail (Inbox) and the drawer's Mail group. Subjects, senders, snippets are attacker-controlled:
   every one goes through esc, and markup carries only the numeric mail id (MAILS keeps the rows) ---- */
const MAILS = {};
/* mail-render */
const kb = n => n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB';
function mailItem(m, actions) {
  const id = Number(m.id), out = m.direction === 'out';
  return `<div class="item" id="mail${id}"><div class="hd"><b>${out ? '→ to ' + esc(m.to_addr) : esc(m.from_addr)}</b>
    <span class="chip">${esc(m.category || 'mail')}</span>${out ? '' : m.trusted ? '<span class="pill ok" title="DKIM/DMARC-aligned and tied to the job by address or company domain">trusted</span>' : '<span class="pill warn" title="not authenticated, or not tied to this company: Lodestar never acts on it unreviewed">unverified</span>'}
    <span class="muted">${esc(localTs(m.sent_at || m.created_at, 16))}${m.linked_by ? ' · linked by ' + esc(m.linked_by) : ''}</span></div>
    <details><summary>${esc(m.subject || '(no subject)')}</summary>${m.summary ? `<div class="muted">${esc(m.summary)}</div>` : ''}<pre>${esc(m.snippet || '')}</pre></details>
    ${mailFiles(m)}
    ${actions ? `<div class="row">${actions}</div>` : ''}</div>`;
}
function mailFiles(m) {  // saved files: name + size, revealed in Explorer only; skipped ones: why
  let a = []; try { a = JSON.parse(m.attachments || '[]'); } catch (_) { /* not JSON: show nothing */ }
  if (!Array.isArray(a) || !a.length) return '';
  const saved = a.filter(f => !f.skipped), skip = a.filter(f => f.skipped);
  return `<div class="row"><span class="muted">${m.direction === 'out' ? 'Attached' : 'Attachments'}:</span>`
    + saved.map(f => `<span class="pill">${esc(f.name)}${f.size ? ' · ' + esc(kb(Number(f.size))) : ''}</span>`).join('')
    + skip.map(f => `<span class="muted">${esc(f.name)}: ${esc(f.skipped)}</span>`).join(' ')
    + (m.direction === 'in' && m.job_id && saved.length ? ` <button class="b ghost sm" title="opens the folder; Lodestar never opens a received file" onclick="openJobFolder(${Number(m.job_id)},'mail')">Show in folder</button>` : '') + '</div>';
}
/* /mail-render */
function renderUnmatched() {
  const el = $('#mailList'); if (!el) return;
  const jobs = S.jobs.map(j => `<option value="${Number(j.id)}">#${Number(j.id)} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
  const keep = $$('#mailList select').map(x => [x.id, x.value]);  // the 60 s refresh must not reset a chosen job
  el.innerHTML = S.mail_unmatched.map(m => { MAILS[m.id] = m; const id = Number(m.id);
    return mailItem(m, `<select id="ml${id}" aria-label="job to file this mail under"><option value="">choose a job…</option>${jobs}</select>
      <button class="b ghost sm" onclick="if(!$('#ml${id}').value)return toast('choose the job first','err');mailOp(${id},'link',{job_id:Number($('#ml${id}').value)})" ${jobs ? '' : 'disabled'}>Link to job</button>
      <button class="b ghost sm" onclick="trackMail(${id})">Track as new job</button>
      <button class="b ghost sm" onclick="mailOp(${id},'dismiss')">Dismiss</button>`);
  }).join('') || '<div class="muted">no unmatched mail: relevant mail no job claims appears here</div>';
  keep.forEach(([id, v]) => { const x = document.getElementById(id); if (x) x.value = v; });
}
function mailGroup(d) {
  return `<div class="group"><h4>Mail</h4>${(d.mail || []).map(m => { MAILS[m.id] = m; const id = Number(m.id);
    return mailItem(m, (m.linked_by === 'user' ? `<button class="b ghost sm" onclick="mailOp(${id},'unlink')">Unlink</button>` : '')
      + (m.direction === 'in' ? `<button class="b ghost sm" onclick="replyMail(${id},this)" title="up to 3 reply drafts, one recommended; the one you use goes to the Inbox for review">Reply with options</button>` : ''));
  }).join('') || '<div class="muted">no mail on file for this job yet (scanned replies and mail Lodestar sends show here)</div>'}</div>`;
}
async function mailOp(id, op, body) {
  const r = await api(`/api/mail/${id}/${op}`, body || {});
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(op === 'track' ? `tracking job #${r.id}` : `mail #${id}: ${op} done`, 'ok'); await load();
  if (op === 'track') openJob(r.id); else if (cur && $('#drawer').classList.contains('open')) openJob(cur.job.id);
}
function trackMail(id) {
  const m = MAILS[id], company = prompt('Company for the new job', m.company || ''); if (company === null) return;
  const title = prompt('Role', m.title || ''); if (title === null) return;
  mailOp(id, 'track', { company, title });
}
function replyMail(id, btn) { if (cur) draftOptions('reply', { id: cur.job.id, mail_id: Number(id) }, 'jOpts', btn); }

/* ---- draft options (lodestar/drafts.py): up to 3 from one AI call, one recommended. Option text stays in OPTS; markup
   carries only indexes. 'Use this' never changes who a mail goes to: the server takes the recipient from the job, the
   mail being answered or the contact, and a pending item keeps everything but its subject and body ---- */
let OPTS = { list: [], kind: '', ctx: {}, target: '' };
const HOWS = [['shorter', 'shorter'], ['warmer', 'warmer'], ['formal', 'more formal'], ['direct', 'more direct']];
const hasAI = () => Object.values(S.providers).some(Boolean);  // rewrite chips need a provider: hidden without one
function draftOptions(kind, ctx, target, btn) {
  run('draft_options', { kind, ...ctx }, r => { OPTS = { list: r.options, kind, ctx, target, ai: hasAI() }; renderOpts(); $('#' + target)?.scrollIntoView({ block: 'nearest' }); }, btn);
}
function optsHtml(target) {
  if (OPTS.target !== target || !OPTS.list.length) return '';
  return `<div class="opts">` + OPTS.list.map((o, i) => `<div class="item opt${o.recommended ? ' rec' : ''}">
    <div class="hd"><b>${esc(o.label)}</b>${o.tone ? `<span class="chip">${esc(o.tone)}</span>` : ''}${o.recommended ? `<span class="pill ok">recommended</span><span class="muted">${esc(o.why)}</span>` : ''}</div>
    ${o.subject ? `<div><b>Subject:</b> ${esc(o.subject)}</div>` : ''}<pre>${esc(o.body)}</pre>
    <div class="row"><button class="b sm" onclick="useOpt(${i},this)">Use this</button>${OPTS.ai ? HOWS.map(([k, l]) => `<button class="b ghost sm" onclick="rewriteOpt(${i},'${k}',this)">${l}</button>`).join('') + `<button class="b ghost sm" onclick="rewriteOpt(${i},'',this)">custom…</button>` : ''}</div></div>`).join('')
    + `<div class="row"><button class="b ghost sm" onclick="closeOpts()">close options</button></div></div>`;
}
function renderOpts() { if (OPTS.target.startsWith('p')) renderInbox(); else { const el = $('#' + OPTS.target); if (el) el.innerHTML = optsHtml(OPTS.target); } }
function closeOpts() { const t = OPTS.target; OPTS = { list: [], kind: '', ctx: {}, target: '' }; if (t.startsWith('p')) renderInbox(); else if ($('#' + t)) $('#' + t).innerHTML = ''; }
function pendingSet(id, d) {  // the item's fields take the saved text as their own, so the refresh does not restore the old edits
  [['sub', d.subject], ['body', d.body]].forEach(([k, v]) => { const e = $(`#${k}${id}`); if (e && v != null) e.value = e.defaultValue = v; });
}
async function useOpt(i, btn) {
  const o = OPTS.list[i], t = OPTS.target; if (!o) return;
  if (t.startsWith('p')) {  // a pending Inbox email: only subject and body change, it stays pending
    const id = Number(t.slice(1)), r = await api(`/api/approvals/${id}/edit`, { subject: o.subject, body: o.body });
    if (r.error) return toast('error: ' + r.error, 'err');
    pendingSet(id, r.payload); closeOpts(); toast(`inbox #${id} updated; still waiting for your approval`, 'ok'); return load();
  }
  if (t === 'aOpts') { $('#bQ').value = OPTS.ctx.question || ''; $('#bA').value = o.body; closeOpts(); return toast('filled in under Answer bank: edit it, then Save', 'ok'); }
  if (OPTS.kind === 'cover') { openEditor('cover_letter.md', o.body); closeOpts(); return toast('the letter is in the editor: review, then Save document', 'ok'); }
  run('draft_use', { kind: OPTS.kind, ...OPTS.ctx, subject: o.subject, body: o.body }, r => {
    const txt = mailText(r); closeOpts();
    if (t === 'ctrOpts') show('ctrOut', txt); else if (cur) openJob(cur.job.id).then(() => { $('#jOut').textContent = txt; });
  }, btn);
}
function rewriteOpt(i, how, btn) {
  const o = OPTS.list[i]; if (!o) return;
  if (!how && !(how = (prompt('How should it change? e.g. mention my portfolio link, drop the second paragraph') || '').trim())) return;
  run('draft_rewrite', { kind: OPTS.kind, subject: o.subject, body: o.body, how }, r => { o.body = r.body; if (r.subject != null) o.subject = r.subject; renderOpts(); }, btn);
}
function rewritePending(id, how, btn) {  // rewrite chips on an Inbox email: the current text (your edits included), saved in place
  if (!how && !(how = (prompt('How should this email change?') || '').trim())) return;
  run('draft_rewrite', { kind: 'email', subject: $('#sub' + id).value, body: $('#body' + id).value, how }, async r => {
    const s = await api(`/api/approvals/${id}/edit`, { subject: r.subject, body: r.body });
    if (s.error) return toast('error: ' + s.error, 'err');
    pendingSet(id, s.payload); toast(`inbox #${id} rewritten; still waiting for your approval`, 'ok'); load();
  }, btn);
}
function commOptions(btn) {  // the drawer's Communicate group: options for the chosen kind, from the fields already there
  const kind = $('#jOk').value, ctx = { id: cur.job.id };
  if (kind === 'thanks') Object.assign(ctx, { interviewer: $('#jInt').value, notes: $('#jTnotes').value });
  if (kind === 'outreach') ctx.person = $('#jPerson').value;
  draftOptions(kind, ctx, 'jOpts', btn);
}
const dueText = d => { const n = daysTo(d); return n < 0 ? `overdue since ${d}` : n === 0 ? 'due today' : `due in ${n}d`; };
function suggestDraft(i, btn) {
  const s = (S.today.emails || [])[i]; if (!s) return;
  const ctx = { id: s.job_id }; if (s.mail_id) ctx.mail_id = s.mail_id; if (s.contact_id) ctx.contact_id = s.contact_id;
  openJob(s.job_id).then(() => draftOptions(s.kind, ctx, 'jOpts', btn));
}
async function suggestDismiss(i) {
  const s = (S.today.emails || [])[i]; if (!s) return;
  const r = await api('/api/suggest/dismiss', { job_id: s.job_id, kind: s.kind });
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('dismissed for 3 days', 'ok'); load();
}

/* ---- search ---- */
function renderSearchless() { /* search results are rendered on demand */ }
let RESULTS = [];  // listings stay in JS; markup carries only an index (listing text inside an onclick attribute is an XSS hole)
const searchParams = () => ({ query: $('#sQ').value, keywords: $('#sK').value, location: $('#sLoc').value, min_salary: $('#sSal').value, posted_within: $('#sDays').value, seniority: $('#sLevel').value });
const GHOST_SHOW = 30;  // web_monitor.GHOST_SHOW
const staleChip = g => g && g.score >= GHOST_SHOW ? `<span class="chip stale" title="${esc(g.reasons.join('; '))}">possibly stale</span>` : '';
const sponsorChip = s => s ? `<span class="chip" title="from the USCIS H-1B data you imported (${esc(s.name)}); a loose name match, not a promise">possible H-1B sponsor (${esc(s.approvals)} approvals)</span>` : '';
function listingHtml(j, i) {
  const unknown = ['salary', 'location', 'date'].filter(k => j[k + '_unknown']).map(k => `<span class="chip" title="the listing does not say; kept rather than dropped">${k} unknown</span>`).join('');
  const cov = j.coverage ? `<span class="chip" title="${esc('matched: ' + (j.coverage.matched.join(', ') || '-') + ' · missing: ' + (j.coverage.missing.join(', ') || '-'))}">JD coverage ${esc(j.coverage.score)}%</span>` : '';
  const host = u => { try { return new URL(u).hostname; } catch (_) { return 'link'; } };
  const more = (j.urls || []).slice(1).filter(safeUrl).map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))} ↗</a>`).join(' ');
  const g = j.ghost && j.ghost.score >= GHOST_SHOW ? `<div class="muted">possibly stale: ${esc(j.ghost.reasons.join('; '))}</div>` : '';
  const c = j.coverage && (j.coverage.matched.length || j.coverage.missing.length) ? `<div class="muted">matched: ${esc(j.coverage.matched.join(', ') || '-')} · missing: ${esc(j.coverage.missing.join(', ') || '-')}</div>` : '';
  return `<div>${j.score != null ? `<span class="score">${esc(j.score)}</span>` : ''}<b>${esc(j.title)}</b> @ ${esc(j.company)} <span class="muted">${esc(j.location)} ${esc(j.salary)} &lt;${esc((j.sources || [j.source]).join(', '))}&gt;</span>
    ${safeUrl(j.url) ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">open ↗</a>` : ''} ${more} <button class="b ghost sm" onclick="saveListing(${i})">track</button>
    <div class="chips">${j.tracked ? `<span class="chip" title="already on your Board">tracked as #${esc(j.tracked)}</span>` : ''}${cov}${staleChip(j.ghost)}${sponsorChip(j.sponsor)}${warmChip(j.warm)}${unknown}${j.seniority ? `<span class="chip">${esc(j.seniority)}</span>` : ''}</div>${c}${g}${j.why ? `<div class="muted">${esc(j.why)}</div>` : ''}</div>`;
}
function doSearch(btn) {
  $('#sRes').innerHTML = '<div class="muted">searching…</div>';
  run('search', { ...searchParams(), rank: $('#sRank').checked }, r => {
    RESULTS = r.results || []; const errs = r.errors || [];
    const none = errs.length && !RESULTS.length && errs.filter(e => !e.startsWith('AI rank')).length >= (r.boards || Infinity)
      ? 'No job board could be reached, so nothing was checked. Check your connection and try again.' : 'nothing found';
    $('#sRes').innerHTML = (errs.length ? `<div class="warnbox" role="alert">${errs.map(e => 'could not ' + (e.startsWith('AI rank') ? 'rank: ' + esc(e.slice(9)) : 'read ' + esc(e))).join('<br>')}</div>` : '')
      + `<div class="list">` + (RESULTS.map(listingHtml).join('') || `<div class="empty">${esc(none)}</div>`) + '</div>';
  }, btn);
}
async function saveSearch() {
  const p = searchParams(); if (!p.query.trim()) return toast('type a query first', 'err');
  const r = await api('/api/watches', { ...p, url: p.query, search: true });
  toast(r.error ? 'error: ' + r.error : r.updated ? `updated the existing saved search "${p.query}" (blank fields kept its keywords and filters)` : `saved: new listings for "${p.query}" will alert (Monitor > Watches)`, r.error ? 'err' : 'ok'); load();
}
async function saveListing(i) {
  const j = RESULTS[i]; if (!j) return;
  const r = await api('/api/jobs', { company: j.company, title: j.title, url: j.url, jd: (j.salary ? `Salary (from ${j.source}): ${j.salary}\n\n` : '') + (j.desc || ''), notes: 'found via ' + j.source, location: j.location || '', date: j.date || '', ats_feed: j.ats_feed || '' });
  if (r.error) return toast('error: ' + r.error, 'err');
  toast((j.tracked ? 'already on your Board as #' : 'tracked as #') + r.id, 'ok'); j.tracked = r.id; load();
}

/* ---- monitor ---- */
function renderMonitor() {
  const filt = f => Object.entries(f || {}).map(([k, v]) => k + '=' + v).join(', ');
  $('#wList').innerHTML = `<div class="list">` + (S.watches.map(w => `<div>${esc(w.url)} <span class="muted">kw=${esc(w.keywords || '-')}${filt(w.filters) ? ' · ' + esc(filt(w.filters)) : ''} · last ${esc(w.last_seen ? localTs(w.last_seen, 16) : 'never')}</span>${w.last_error ? ` <span class="chip stale" title="${esc(w.last_error)}">${w.last_error.startsWith('partial:') ? 'some boards unreachable' : 'last run failed'}</span> <span class="muted">${esc(w.last_error.replace(/^partial: some boards unreachable: /, '').slice(0, 160))}</span>` : ''} <button class="b ghost sm" onclick="api('/api/watches/${w.id}',{}).then(load)">remove</button></div>`).join('') || '<div class="empty">No watches yet. Add a careers page URL or a saved search.</div>') + '</div>';
  $('#coList').innerHTML = `<div class="list">` + (S.companies.map(c => `<div><b>${esc(c.name)}</b> <span class="pill">${esc(c.vendor)}:${esc(c.slug)}</span><span class="muted">kw=${esc(c.keywords || '-')} · last ${esc(c.last_seen ? localTs(c.last_seen, 16) : 'never')}</span>${c.last_error ? ` <span class="chip stale" title="${esc(c.last_error)}">last read failed</span>` : ''} <button class="b ghost sm" onclick="api('/api/companies/${c.id}',{}).then(load)">remove</button></div>`).join('') || '<div class="empty">No companies yet.</div>') + '</div>';
  $('#alerts').textContent = S.alerts.join('\n') || '(no alerts yet)';
}
function exportObsidian(btn) {  // writes outside Lodestar's folder: name the target and ask first
  if (!confirm(`Write one note per tracked job into\n${S.obsidian_dir}\n\nNotes Lodestar wrote there before are updated. To use another vault, store OBSIDIAN_VAULT (the vault folder) in Setup > Vault first.`)) return;
  run('obsidian', {}, r => toast('vault notes written to ' + r.path, 'ok'), btn);
}
async function addWatch() {
  const r = await api('/api/watches', { url: $('#wUrl').value, keywords: $('#wKw').value, search: $('#wSearch').checked });
  if (r.error) return toast('error: ' + r.error, 'err');
  $('#wUrl').value = ''; load();
}
async function addCompany() {
  const r = await api('/api/companies', { source: $('#cSrc').value, name: $('#cName').value, keywords: $('#cKw').value });
  if (r.error) return toast('error: ' + r.error, 'err');
  ['#cSrc', '#cName', '#cKw'].forEach(s => { $(s).value = ''; }); toast(`watching ${r.name} (${r.vendor}:${r.slug})`, 'ok'); load();
}

/* ---- answers ---- */
function renderAnswers() {
  $('#bank').innerHTML = `<div class="list">` + (S.answers.map((a, i) => `<div><b>${esc(a.question)}</b> ${a.private ? '<span class="pill" title="never sent to an employer">private</span> ' : ''}<button class="b ghost sm" onclick="answerPrivate(${i})">${a.private ? 'allow for employers' : 'make private'}</button> <button class="b ghost sm" onclick="api('/api/answers/${Number(a.id)}',{}).then(load)">remove</button><div class="muted" style="white-space:pre-wrap">${esc(a.answer)}</div></div>`).join('') || '<div class="empty">No saved answers yet. Draft one above; it is saved through the Inbox unless the answers tool is auto.</div>') + '</div>';
  const keep = $('#aJob').value;  // the refresh must not switch the job an answer is being drafted for
  $('#aJob').innerHTML = S.jobs.map(j => `<option value="${j.id}">#${j.id} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
  if (keep && S.jobs.some(j => String(j.id) === keep)) $('#aJob').value = keep;
}
async function saveAnswer(btn) {
  const question = $('#bQ').value.trim(), answer = $('#bA').value.trim();
  if (!question || !answer) return toast('type both a question and an answer', 'err');
  btn.disabled = true; const r = await api('/api/answers', { question, answer, tags: $('#bT').value, private: $('#bP').checked }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  ['#bQ', '#bA', '#bT'].forEach(s => { $(s).value = ''; }); $('#bP').checked = false; toast('answer saved', 'ok'); load();
}
async function answerPrivate(i) {  // private answers stay out of drafted answers, letters and form autofill
  const a = S.answers[i]; const r = await api('/api/answers', { question: a.question, answer: a.answer, tags: a.tags || '', private: !a.private });
  if (r.error) toast('error: ' + r.error, 'err'); load();
}
function answerOptions(btn) { draftOptions('answer', { id: $('#aJob').value, question: $('#aQ').value }, 'aOpts', btn); }
function askAnswer(btn) { run('answer', { id: $('#aJob').value, question: $('#aQ').value }, r => show('aOut2', r.answer + '\n\n[reused: ' + (r.reused.join(' | ') || 'none') + ']  [save -> ' + r.proposal.status + ']'), btn); }

/* ---- ideas ---- */
function renderIdeas() {
  if (!$('#iTopic').options.length) $('#iTopic').innerHTML = opt(TOPICS);
  const keep = $('#iJob').value;
  $('#iJob').innerHTML = '<option value="">(no job focus)</option>' + S.jobs.map(j => `<option value="${j.id}">#${j.id} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
  if (S.jobs.some(j => String(j.id) === keep)) $('#iJob').value = keep;
  $('#ideaList').innerHTML = S.ideas.map(i => { const id = Number(i.id); return `<div class="panel"><div class="row" style="margin-top:0"><b>${esc(i.title)}</b><span class="pill">${esc(i.topic)}</span><span class="pill">score ${esc(i.score)}</span><span class="muted">impact ${esc(i.impact ?? '?')} · effort ${esc(i.effort ?? '?')} · fit ${esc(i.fit ?? '?')} · ${esc(i.time || '')}</span>
      <select aria-label="status of this idea" onchange="api('/api/ideas/${id}/status',{status:this.value}).then(load)">${opt(S.idea_statuses, i.status)}</select><button class="b ghost sm" onclick="api('/api/ideas/${id}/delete',{}).then(load)">remove</button></div>
      <div>${esc(i.idea || '')}</div><div class="muted">why: ${esc(i.why_it_works || '')}</div>
      <ol class="muted">${(Array.isArray(i.plan) ? i.plan : []).map(s => `<li>${esc(s)}</li>`).join('')}</ol><div class="muted">metric: ${esc(i.metric || '')}</div>
      ${i.topic === 'stories' ? `<div class="row"><button class="b ghost sm" title="becomes a STAR story (Answers > Stories) with this title and sketch; you fill in the rest" onclick="storyFromIdea(${id})">Save as story</button></div>` : ''}
      <div class="row"><input id="rf${id}" class="grow" placeholder="feedback: make it cheaper / focus on X / too vague"><button class="b ghost sm" onclick="run('refine',{idea_id:${id},feedback:$('#rf${id}').value},r=>toast('refined: '+r.idea.title,'ok'),this)">Refine</button></div></div>`; }).join('')
    || '<div class="empty">No ideas yet. Pick a topic and craft.</div>';
}
function craft(btn) {
  run('craft', { topic: $('#iTopic').value, id: $('#iJob').value || undefined, role: $('#iRole').value, extra: $('#iExtra').value, n: $('#iN').value || 8, single: $('#iSingle').checked }, r => toast(r.ideas.length + ' idea(s) saved', 'ok'), btn);
}

/* ---- tools and setup ---- */
let PK = [];  // pref keys: markup carries an index, never a key from settings.json
function renderTools() {
  $('#toolTable').innerHTML = `<table><tr><th>Tool</th><th>enabled</th><th>auto</th></tr>${S.tools.map((t, i) => `<tr><td><b>${esc(t.tool)}</b><div class="muted">${esc(t.description)}</div></td>
    <td><input type="checkbox" aria-label="${esc(t.tool)} enabled" ${t.enabled ? 'checked' : ''} onchange="api('/api/tools',{tool:S.tools[${i}].tool,enabled:this.checked}).then(load)"></td>
    <td><input type="checkbox" aria-label="${esc(t.tool)} auto" ${t.auto ? 'checked' : ''} onchange="api('/api/tools',{tool:S.tools[${i}].tool,auto:this.checked}).then(load)"></td></tr>`).join('')}</table>`;
  PK = Object.keys(S.prefs);
  // each preference: a plain label (aria-labelledby) and one line of help; the raw key stays visible for the terminal
  $('#prefs').innerHTML = PK.map((k, i) => [k, S.prefs[k], `PK[${i}]`, (S.pref_help || {})[k] || [k, '']]).map(([k, v, ref, [label, help]], i) => `<div class="row"><span style="width:220px" id="pl${i}">${esc(label)}<span class="muted" style="display:block">${esc(help)}${label !== k ? ` (${esc(k)})` : ''}</span></span>${S.pref_choices[k] ? `<select aria-labelledby="pl${i}" onchange="setPref(${ref},this.value)">${S.pref_choices[k].map(c => `<option value="${esc(c)}" ${c === v ? 'selected' : ''}>${esc(c || '(automatic)')}</option>`).join('')}</select>`
    : typeof v === 'boolean' ? `<input type="checkbox" aria-labelledby="pl${i}" ${v ? 'checked' : ''} onchange="setPref(${ref},this.checked)">`
    : typeof v === 'object' && v ? `<span class="muted">${esc(Object.entries(v).map(([p, m]) => p + '=' + (m || '(default)')).join(', ') || (k === 'weekly_goals' ? 'none set' : 'none pinned'))}</span><input class="grow" aria-labelledby="pl${i}" placeholder="${k === 'weekly_goals' ? 'goal=number, e.g. contacts=5 (0 clears); also on the Insights tab' : 'provider=model to pin (empty model = default); Setup > List models shows ids'}" onchange="setPref(${ref},this.value)">`
    : `<input class="grow" aria-labelledby="pl${i}" value="${esc(v)}" onchange="setPref(${ref},this.value)">`}</div>`).join('');
}
async function setPref(key, value) { const r = await api('/api/prefs', { key, value }); if (r.error) toast('error: ' + r.error, 'err'); load(); }
function renderSetup() {
  renderKeys();
  $('#vList').innerHTML = S.vault.map((v, i) => `<span class="pill">${esc(v.name + (v.user ? ' (' + v.user + ')' : ''))} <button class="b ghost sm" aria-label="remove" onclick="delVault(${i})">×</button></span>`).join(' ') || 'empty';
  const u = Object.entries(S.usage).filter(([k]) => k !== 'total');
  $('#usage').innerHTML = u.length ? 'last 30 days: ' + u.map(([k, d]) => `<span class="pill">${esc(k)}: ${d.calls} calls · ${(d.input + d.output).toLocaleString()} tokens</span>`).join(' ') : '';
  $('#pPath').textContent = S.profile_path;
  $('#pNotify').checked = !!S.prefs.desktop_notifications;
  const rates = Object.entries(S.comp).flatMap(([t, cities]) => Object.entries(cities).map(([c, [lo, hi]]) => ({ t, c, lo, hi })));
  $('#compList').innerHTML = rates.map((r, i) => `<div><b>${esc(r.t)}</b> <span class="muted">${esc(r.c === '*' ? 'any city' : r.c)}</span> ${esc(r.lo.toLocaleString())} - ${esc(r.hi.toLocaleString())} <button class="b ghost sm" onclick="compOp({op:'delete',title:RATES[${i}].t,city:RATES[${i}].c})">remove</button></div>`).join('') || '<div class="muted">none recorded: gap checks, offer evaluation and interview prep then say "none recorded"</div>';
  RATES = rates;
  const o = location.origin;
  $('#bm').href = `javascript:(()=>{const t=document.title,u=location.href,d=(document.querySelector('main')||document.body).innerText.slice(0,12000);fetch('${o}/api/capture?t=${CAPTURE}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,url:u,desc:d})}).then(r=>r.json()).then(r=>alert(r.error?('Lodestar: '+r.error):('Lodestar tracked #'+r.id+': '+r.company+' - '+r.title))).catch(e=>alert('Lodestar UI not running? '+e))})();`;
  $('#af').href = `javascript:(()=>{fetch('${o}/api/autofill?t=${CAPTURE}').then(r=>r.json()).then(d=>{if(d.error){alert('Lodestar could not autofill: '+d.error);return}const map={first_name:/first.?name|given|fname|legalname.*first/i,last_name:/last.?name|surname|family|lname|legalname.*last/i,name:/^(full.?)?name$|your.?name|^name$|cards\\[.*\\]\\[name\\]/i,email:/e-?mail/i,phone:/phone|mobile|tel/i,linkedin:/linkedin/i,github:/github/i,website:/website|portfolio|^url|personal.?site/i,location:/city|location|address|where.*located/i};const ats={first_name:['#first_name','input[name=\"first_name\"]','[data-automation-id=\"legalNameSection_firstName\"]','#first-name','input[name=\"_systemfield_first_name\"]'],last_name:['#last_name','input[name=\"last_name\"]','[data-automation-id=\"legalNameSection_lastName\"]','#last-name','input[name=\"_systemfield_last_name\"]'],name:['input[name=\"name\"]','input[name=\"_systemfield_name\"]','#full_name'],email:['#email','input[name=\"email\"]','input[name=\"_systemfield_email\"]','[data-automation-id=\"email\"]','input[type=\"email\"]'],phone:['#phone','input[name=\"phone\"]','[data-automation-id=\"phone-number\"]','#phone-number','input[type=\"tel\"]'],linkedin:['input[name=\"urls[LinkedIn]\"]','#linkedin','input[name*=\"linkedin\" i]'],github:['input[name=\"urls[GitHub]\"]','input[name*=\"github\" i]'],website:['input[name=\"urls[Portfolio]\"]','input[name*=\"website\" i]','input[name*=\"portfolio\" i]'],location:['input[name=\"job_application[location]\"]','#location','input[name*=\"location\" i]']};let n=0;for(const k in ats){if(!d[k])continue;for(const sel of ats[k]){const el=document.querySelector(sel);if(el&&!el.value&&!el.dataset.ls){el.value=d[k];el.dataset.ls='1';el.dispatchEvent(new Event('input',{bubbles:true}));n++;break}}}document.querySelectorAll('input,textarea').forEach(el=>{if(el.type==='hidden'||el.type==='password'||el.value||el.dataset.ls)return;const lab=(el.labels&&el.labels[0]?el.labels[0].innerText:'')+' '+(el.name||'')+' '+(el.id||'')+' '+(el.placeholder||'')+' '+(el.getAttribute('aria-label')||'')+' '+(el.getAttribute('data-automation-id')||'')+' '+(el.getAttribute('autocomplete')||'')+' '+(el.getAttribute('data-qa')||'');for(const k in map){if(map[k].test(lab)&&d[k]){el.value=d[k];el.dispatchEvent(new Event('input',{bubbles:true}));n++;break}}});alert('Lodestar filled '+n+' field(s). Review everything, then submit yourself.')}).catch(e=>alert('Lodestar UI not running? '+e))})();`;
}
/* ---- updates (updater.py): check, the commit range + changelog, Update now, Restart (desktop), the log ---- */
let UPLAN = null;  // the last check this page made: Update now applies exactly its target
function renderUpdate() {
  const u = S.update || {}, pill = $('#updPill');
  const label = u.restart_needed ? 'Restart to finish the update' : u.available ? 'Update available' : '';
  pill.style.display = label ? '' : 'none'; pill.textContent = label;
  pill.title = (u.restart_needed ? u.last_update : u.last_check)?.result || '';
  if (document.activeElement !== $('#uMode')) $('#uMode').value = u.mode || 'notify';
  if (document.activeElement !== $('#uEvery')) $('#uEvery').value = u.every_hours ?? 24;
  const kind = { git: 'git install', exe: 'standalone build: an update is announced with its download link, never installed', none: 'not a git install: reinstall with install.ps1 to get updates' }[u.kind] || '';
  const last = e => e ? `${esc(String(e.at).slice(0, 16))}: ${esc(e.result)}` : 'never';
  $('#uInfo').innerHTML = `${esc(kind)} · Lodestar ${esc(u.version || S.version)}<br>last check ${last(u.last_check)}${u.last_update ? '<br>last update ' + last(u.last_update) : ''}${u.error ? '<br>' + esc(u.error) : ''}`;
  $('#uLog').innerHTML = (u.log || []).map(e => `<div><span class="pill ${e.kind === 'apply' ? (e.ok ? 'ok' : 'warn') : ''}">${esc(e.kind)}</span> <span class="muted">${esc(String(e.at).slice(0, 16))}</span> ${e.from || e.to ? `<code>${esc(String(e.from).slice(0, 7))}..${esc(String(e.to).slice(0, 7))}</code> ` : ''}${esc(e.result)}</div>`).join('') || '<div class="muted">no checks yet</div>';
  if (u.updating && !$('#uProgress')) {  // another tab or the loop is updating: no Restart until it ends
    if (!$('#uBusy')) $('#uResult').innerHTML = '<div class="muted" id="uBusy">An update is running. Restart comes back when it has finished.</div>';
  } else if (u.restart_needed && !$('#uProgress') && !$('#uRestartRow')) $('#uResult').innerHTML = restartHtml();
  else if (!u.updating) $('#uBusy')?.remove();
}
const restartHtml = () => S.update.restart
  ? '<div class="row" id="uRestartRow"><span>Updated. Restart Lodestar to run the new version.</span><button class="b" id="uRestart" onclick="updRestart(this)">Restart</button></div>'
  : '<div class="row" id="uRestartRow">Updated. Close Lodestar and start it again to run the new version.</div>';
function updCheck(btn) { run('/api/update/check', {}, p => { UPLAN = p; updPlan(p); }, btn); }
function updPlan(p) {
  if (!p.available) { $('#uPlan').innerHTML = `<div ${p.result.startsWith('could not') ? 'style="color:var(--warn)"' : 'class="muted"'} id="uUpToDate">${esc(p.result)}</div>`; return; }
  const n = Number(p.behind), url = safeUrl(p.url);
  $('#uPlan').innerHTML = `<h4 id="uHead">Update available: ${p.kind === 'git' ? `${n} commit${n === 1 ? '' : 's'}` : esc(p.current + ' → ' + p.target)}</h4>
    ${p.kind === 'git' ? `<div class="muted" id="uRange">from <code>${esc(p.current.slice(0, 7))}</code> to <code>${esc(p.target.slice(0, 7))}</code>${p.origin ? ' · ' + esc(p.origin) : ''}</div>
    <ul class="muted" id="uCommits">${p.commits.map(c => `<li><code>${esc(c.split(' ')[0])}</code> ${esc(c.split(' ').slice(1).join(' '))}</li>`).join('')}</ul>` : ''}
    ${p.changelog ? `<details open><summary class="muted">What's new (changelog)</summary><pre id="uChangelog">${esc(p.changelog)}</pre></details>` : ''}
    ${p.blocked ? `<div style="color:var(--warn)" id="uBlocked">Not now: ${esc(p.blocked)}</div>` : ''}
    <div class="row">${p.kind === 'git' ? `<button class="b" id="uApply" ${p.blocked ? 'disabled' : ''} onclick="updApply(this)">Update now</button>`
      : url ? `<a class="b" href="${esc(url)}" target="_blank" rel="noopener">Download</a>` : ''}</div>`;
}
function updApply(btn) {
  const p = UPLAN, n = p ? Number(p.behind) : 0;
  if (!p || !confirm(`Update Lodestar ${p.current.slice(0, 7)} → ${p.target.slice(0, 7)} (${n} commit${n === 1 ? '' : 's'})?\n\nA backup is taken first; the tests and lodestar doctor then run on the new code, and anything that fails is rolled back. This takes a minute or two.`)) return;
  const t0 = Date.now(), check = $('#uCheck'), prog = s => 'Updating: backup, fast-forward, then the tests and doctor on the new code… ' + s;
  $('#uResult').innerHTML = `<div class="muted" id="uProgress">${prog('')}</div>`; check.disabled = true;
  const tick = setInterval(() => {  // run() re-enables the button when the task ends, whatever its outcome
    if (!btn.disabled) { clearInterval(tick); check.disabled = false; $('#uProgress')?.remove(); return; }
    $('#uProgress').textContent = prog(Math.round((Date.now() - t0) / 1000) + ' s');
  }, 1000);
  run('/api/update/apply', { target: p.target }, r => {
    UPLAN = null; $('#uPlan').innerHTML = ''; check.disabled = false;
    $('#uResult').innerHTML = (r.ok ? restartHtml() : `<div style="color:var(--warn)" id="uFail">${esc(r.result)}</div>`) + (r.backup ? `<div class="muted">backup: ${esc(r.backup)}</div>` : '');
    toast(r.result, r.ok ? 'ok' : 'err');
  }, btn, err => {  // refused before it ran (the origin moved, another update running): the old plan is gone
    UPLAN = null; $('#uPlan').innerHTML = ''; check.disabled = false;
    $('#uResult').innerHTML = `<div style="color:var(--warn)" id="uFail">${esc(err)}</div>`; load();
  });
}
async function updRestart(btn) {
  btn.disabled = true;
  const r = await api('/api/update/restart', {});
  if (r.error) { btn.disabled = false; return toast('error: ' + r.error, 'err'); }
  toast('restarting Lodestar…', 'ok');
}
function showDoctor(rows) {
  const mark = { ok: ['PASS', 'ok'], warn: ['WARN', 'warn'], fail: ['FAIL', ''] };
  $('#doctorOut').innerHTML = `<div class="list">` + rows.map(r => `<div><span class="pill ${mark[r.status][1]}" ${r.status === 'fail' ? 'style="background:#4d1f1f;color:var(--bad)"' : ''}>${mark[r.status][0]}</span><b>${esc(r.what)}</b> <span class="muted">${esc(r.detail)}</span></div>`).join('') + '</div>';
}
let RATES = [];  // titles stay in JS; markup carries only an index
async function compOp(body) {
  const r = await api('/api/comp', body); if (r.error) return toast('error: ' + r.error, 'err');
  if (body.op !== 'delete') ['#mTitle', '#mCity', '#mLow', '#mHigh'].forEach(s => { $(s).value = ''; });
  toast(body.op === 'delete' ? 'removed' : 'recorded', 'ok'); load();
}
async function delVault(i) {  // names stay in JS; markup carries only an index
  const v = S.vault[i]; if (!v || !confirm(`Remove ${v.name} from the OS keyring?`)) return;
  const r = await api('/api/vault', { name: v.name, delete: true }); toast(r.error || 'removed ' + v.name, r.error ? 'err' : 'ok'); load();
}
/* ---- link an AI key (the key goes in once and never comes back from the server) ---- */
let KEYS = [];  // provider names stay in JS; markup carries only an index
const KSTAT = { verified: ['Verified', 'ok'], failed: ['Failed', 'bad'], unreachable: ["Couldn't reach, will retry", 'warn'], unchecked: ['Not checked', ''] };
function renderKeys() {
  const c = S.connections || { keys: {} }, sel = $('#kProv'), was = sel.value;
  KEYS = Object.keys(c.keys);
  sel.innerHTML = KEYS.map(n => `<option value="${esc(n)}">${esc(c.keys[n].label + (c.keys[n].linked ? ' (linked)' : ''))}</option>`).join('');
  if (KEYS.includes(was)) sel.value = was;
  keyHint();
  $('#kList').innerHTML = (c.checking ? '<div class="muted">checking...</div>' : '') + KEYS.map((n, i) => {
    const k = c.keys[n];
    if (!k.linked) return `<div class="muted">${esc(k.label)}: not linked</div>`;
    const [label, cls] = KSTAT[k.status] || KSTAT.unchecked, when = k.checked_at ? ' ' + localTs(k.checked_at, 16) : '';
    const env = k.source === 'env';
    return `<div><b>${esc(k.label)}</b> <span class="pill ${cls}" ${cls === 'bad' ? 'style="background:#4d1f1f;color:var(--bad)"' : ''}>${esc(label + (k.status === 'verified' ? when : ''))}</span>`
      + (k.model ? ` <span class="muted">model ${esc(k.model)}</span>` : '')
      + (k.detail && k.status !== 'verified' ? ` <span class="muted">${esc(k.detail)}</span>` : '')
      + ` <button class="b ghost sm" onclick="keyCheck(${i},this)">Re-check</button>`
      + (n === 'ollama' ? '' : ` <button class="b ghost sm" ${env ? 'disabled title="set in .env or the environment: remove it there"' : ''} onclick="keyRemove(${i})">Remove</button>`) + '</div>';
  }).join('');
}
function keyHint() {
  const k = (S.connections?.keys || {})[$('#kProv').value]; if (!k) return;
  const u = safeUrl(k.get);
  $('#kHint').innerHTML = (u ? `Get a key: <a href="${esc(u)}" target="_blank" rel="noopener">${esc(u)}</a>` : '') + (k.hint ? ` <span>(${esc(k.hint)})</span>` : '');
  $('#kVal').disabled = $('#kProv').value === 'ollama';
  $('#kVal').placeholder = $('#kProv').value === 'ollama' ? 'no key: Link checks Ollama on this computer' : 'paste the key';
}
async function keyLink(btn) {
  btn.disabled = true;
  try {
    const r = await api('/api/keys/link', { name: $('#kProv').value, key: $('#kVal').value });
    if (r.error) return toast('error: ' + r.error, 'err');
    toast(`${r.label}: ${(KSTAT[r.status] || KSTAT.unchecked)[0]} - ${r.detail}${r.prefix_warning ? ' (' + r.prefix_warning + ')' : ''}${r.shadowed ? ' (' + r.shadowed + ')' : ''}`, r.status === 'failed' ? 'err' : 'ok');
  } finally { $('#kVal').value = ''; btn.disabled = false; load(); }
}
async function keyCheck(i, btn) {
  const n = KEYS[i]; if (!n) return;
  btn.disabled = true;
  const r = await api('/api/keys/check', { name: n }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  load();
}
async function keyRemove(i) {
  const n = KEYS[i], k = (S.connections?.keys || {})[n]; if (!k || !confirm(`Remove the ${k.label} key from the OS keyring?`)) return;
  const r = await api('/api/keys/remove', { name: n }); toast(r.error ? 'error: ' + r.error : 'removed', r.error ? 'err' : 'ok'); load();
}
/* ---- connect email: a Google / Microsoft sign-in (every 2-step method runs on their page) or an app password. The
   password, client secret and tokens go in once and never come back from the server ---- */
let EM = null;  // {status, presets, clients, oauth} from /api/email/status
const EF = { imap_host: '#eImapHost', imap_port: '#eImapPort', imap_mode: '#eImapMode', smtp_host: '#eSmtpHost', smtp_port: '#eSmtpPort', smtp_mode: '#eSmtpMode', smtp_user: '#eSmtpUser', cafile: '#eCafile' };
const OAUTH_LABEL = { google: 'Google', microsoft: 'Microsoft' };
const CLIENT_STEPS = {  // the one-time client setup, shortened from docs/CONNECT.md: [step, link]
  google: [
    ['Google Cloud console: create a project named "Lodestar".', 'https://console.cloud.google.com/'],
    ['APIs & Services > Library: enable "Gmail API".', ''],
    ['Google Auth Platform > Branding: app name "Lodestar (personal)", your address as support and developer contact. Audience: External. Data access: add the scope https://mail.google.com/ (plus openid, email).', ''],
    ['Clients > Create client > Desktop app. Copy the Client ID and Client secret into the boxes below right away: Google shows the secret only once.', ''],
    ['Audience > Test users: add your own address.', ''],
    ['Audience > Publish app ("In production"). Unverified is fine for your own use; skip this and the sign-in stops after 7 days.', ''],
    ['Save the client here, then Sign in with Google. On "Google hasn\'t verified this app": Advanced > Go to Lodestar (it is your own app).', ''],
  ],
  microsoft: [
    ['You need a Microsoft Entra tenant to register an app (work or school: ask IT; personal: a free tenant). Not for you? Forward Outlook mail to Gmail and connect that.', 'https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-create-new-tenant'],
    ['Entra admin center > App registrations > New registration: name "Lodestar", account types "Any Entra ID Tenant + Personal Microsoft accounts", redirect platform "Public client/native (mobile & desktop)" with http://localhost.', 'https://entra.microsoft.com'],
    ['Authentication > Advanced settings > Allow public client flows: Yes. Save.', ''],
    ['API permissions > Add > APIs my organization uses > Office 365 Exchange Online > Delegated: IMAP.AccessAsUser.All and SMTP.Send (plus offline_access, openid, email, profile). Work accounts: an admin may need to consent.', ''],
    ['Copy the Application (client) ID into the box below. There is no secret.', ''],
    ['Outlook.com only: turn on IMAP (Outlook.com > Settings > Mail > Forwarding and IMAP).', 'https://support.microsoft.com/en-us/outlook/pop-imap-and-smtp-settings-for-outlook-com'],
  ],
};
async function loadEmail() {
  const r = await api('/api/email/status'); if (r.error) return toast('error: ' + r.error, 'err');
  EM = r; const s = r.status;
  if (!$('#eProv').options.length) $('#eProv').innerHTML = Object.entries(r.presets).map(([k, p]) => `<option value="${esc(k)}">${esc(p.label)}${p.unsupported ? ' (not supported)' : ''}</option>`).join('');
  if (s.user && !$('#eUser').value) $('#eUser').value = s.user;
  $('#eProv').value = r.presets[s.preset] ? s.preset : (s.configured ? 'custom' : 'gmail');
  emailPreset(s); emailLine();
}
function emailGuess() {  // the address box: pick the preset its domain belongs to (Outlook and Microsoft 365 sign in only)
  if (!EM) return;
  const dom = $('#eUser').value.trim().toLowerCase().split('@')[1] || '';
  const k = Object.keys(EM.presets).find(n => (EM.presets[n].domains || []).includes(dom));
  if (k && k !== $('#eProv').value) { $('#eProv').value = k; emailPreset(); }
}
function emailPreset(s) {  // s: the stored connection when it uses this preset, else the preset's own servers
  const k = $('#eProv').value, p = EM.presets[k] || {}, v = s && (s.preset === k || (!s.preset && s.configured)) ? s : p, off = !!p.unsupported;
  Object.entries(EF).forEach(([f, sel]) => { $(sel).value = f === 'smtp_user' && v.smtp_user === v.user ? '' : (v[f] || (f.endsWith('_mode') ? 'ssl' : '')); });
  ['#ePass', '#eConnect', '#eSend'].forEach(x => { $(x).disabled = off; });  // the address stays editable: a typo must not lock it
  $('#emailCard').style.opacity = off ? '.6' : '';
  $('#eAdv').open = k === 'custom' || !!p.cert;
  const prov = p.oauth || '', st = EM.status || {}, signedIn = st.auth === 'oauth' && st.oauth_provider === prov && st.configured;
  $('#eOauth').style.display = prov ? '' : 'none';
  $('#ePw').style.display = $('#eConnect').style.display = p.oauth_only ? 'none' : '';  // Microsoft takes no passwords
  $('#ePwSum').textContent = prov ? 'Or use an app password' : 'App password';
  $('#ePw').open = !(prov && signedIn);
  if (prov) emailOauthCard(k, prov);
  const help = safeUrl(p.help);
  $('#eHelp').innerHTML = off ? `<b>Not supported:</b> ${esc(p.unsupported)}`
    : `${esc(p.steps || '')} ${help ? `<a href="${esc(help)}" target="_blank" rel="noopener">${prov ? 'Provider help' : 'Open the app password page'}</a>` : ''}`;
}
function emailOauthCard(k, prov) {
  const label = OAUTH_LABEL[prov], set = !!((EM.clients || {})[prov] || {}).set;
  $('#eSignin').textContent = `Sign in with ${label}`;
  $('#eSignin').disabled = !set; $('#eSignin').title = set ? '' : `set up your ${label} client first (below)`;
  $('#eAcct').style.display = prov === 'microsoft' ? '' : 'none';
  $$('input[name=eAcct]').forEach(x => { x.checked = x.value === (k === 'm365' ? 'work' : 'personal'); });
  $('#eOauthNote').textContent = `Your 2-step verification (authenticator app, text code, phone prompt, passkey, security key) happens on ${label}'s page. Lodestar never sees your password or codes.`
    + (set ? '' : ` First set up your own ${label} client below (one time, about 10 minutes).`);
  $('#eClientSum').textContent = set ? `${label} client set up · Change client` : `Set up your ${label} client (one time)`;
  $('#eClient').open = !set;
  $('#eCsec').style.display = prov === 'google' ? '' : 'none';
  $('#eCid').placeholder = prov === 'google' ? 'Client ID (ends in .apps.googleusercontent.com)' : 'Application (client) ID';
  $('#eClientSteps').innerHTML = CLIENT_STEPS[prov].map(([t, u]) => `<li>${esc(t)}${safeUrl(u) ? ` <a href="${esc(safeUrl(u))}" target="_blank" rel="noopener">open</a>` : ''}</li>`).join('');
}
async function emailClient(btn) {  // the user's own OAuth client; the values never come back
  const k = $('#eProv').value, prov = (EM.presets[k] || {}).oauth; if (!prov) return;
  btn.disabled = true;
  try {
    const r = await api('/api/email/client', { provider: prov, client_id: $('#eCid').value.trim(), client_secret: $('#eCsec').value.trim() });
    if (r.error) return toast('error: ' + r.error, 'err');
    EM.clients = r.clients; emailOauthCard(k, prov); toast(`${OAUTH_LABEL[prov]} client saved: now Sign in with ${OAUTH_LABEL[prov]}`, 'ok');
  } finally { $('#eCid').value = ''; $('#eCsec').value = ''; btn.disabled = false; }
}
async function emailSignin(btn) {  // opens the provider's page in the system browser (never this window), then tests
  const prov = (EM.presets[$('#eProv').value] || {}).oauth; if (!prov) return;
  const account = prov === 'microsoft' ? (($('input[name=eAcct]:checked') || {}).value || 'personal') : 'personal';
  btn.disabled = true;
  const r = await api('/api/email/signin', { provider: prov, account, login_hint: $('#eUser').value.trim() });
  if (r.error) { btn.disabled = false; return emailLine(null, r.error); }
  $('#eWait').innerHTML = `Waiting for you to finish signing in in your browser… <span id="eWaitLink"></span> <button class="b ghost sm" onclick="api('/api/email/signin_cancel',{})">Cancel</button>`;
  setTimeout(emailSigninLink, 1000);
  const poll = async () => {
    const t = await api('/api/tasks/' + r.task);
    if (t.status === 'running') return setTimeout(poll, 1500);
    btn.disabled = false; $('#eWait').innerHTML = '';
    if (t.status !== 'done') return emailLine(null, t.error || 'the sign-in did not finish');
    EM.status = t.result.status; const test = t.result.test || {};
    emailLine(test.error ? null : test, test.error); load();
  };
  poll();
}
async function emailSigninLink() {  // the fallback when no browser opened: the same page, in the system browser
  const r = await api('/api/email/signin'), u = safeUrl(r.url), el = $('#eWaitLink');
  if (el && r.pending && u) el.innerHTML = `<a href="${esc(u)}" target="_blank" rel="noopener">Open the sign-in page</a>`;
}
function emailLine(test, err) {
  const s = EM.status, ok = b => `<span class="pill ${b ? 'ok' : ''}">${b ? 'ok' : 'failed'}</span>`;
  const failed = test && !(test.imap.ok && test.smtp.ok);  // a stored password the server refused is not a connection
  const via = s.auth === 'oauth' ? { google: 'Google', microsoft: 'Microsoft' }[s.oauth_provider] || '' : '';
  let h = failed ? `Saved, but sign-in failed for <b>${esc(s.user)}</b> (${esc(s.label || s.preset || 'custom')}): Lodestar cannot read or send mail until the test passes`
    : s.configured ? `${via ? 'Signed in with ' + esc(via) + ' as' : 'Connected as'} <b>${esc(s.user)}</b> (${esc(s.label || s.preset || 'custom')}${via ? ', OAuth' : ''}) · IMAP ${esc(s.imap_host)}:${esc(s.imap_port)} · SMTP ${esc(s.smtp_host)}:${esc(s.smtp_port)} ${esc(s.smtp_mode)}`
    : `Not connected${s.user ? ' (address ' + esc(s.user) + ' saved, no app password or sign-in)' : ''}`;
  if (via && s.needs_signin) h += `<div style="color:var(--bad)">Sign-in expired: ${esc(s.needs_signin)} <button class="b sm" onclick="emailSignin(document.getElementById('eSignin'))">Sign in again</button></div>`;
  if (via && s.refresh_expires) h += `<div class="warnbox">Your Google app is in Testing: this sign-in stops on ${esc(String(s.refresh_expires).slice(0, 10))}. Publish it (docs/CONNECT.md, Google step 6), then sign in again.</div>`;
  if (s.shadowed && s.shadowed.length) h += `<div class="muted">${esc(s.shadowed.join(', '))} set in the environment or .env override these settings</div>`;
  (s.conflicts || []).forEach(c => { h += `<div class="warnbox">${esc(c)}</div>`; });
  if (test) h += `<div>IMAP ${ok(test.imap.ok)} ${esc(test.imap.detail)}</div><div>SMTP ${ok(test.smtp.ok)} ${esc(test.smtp.detail)}</div>${test.hint ? `<div><b>What to do:</b> ${esc(test.hint)}</div>` : ''}`;
  if (err) h += `<div style="color:var(--bad)">${esc(err)}</div>`;
  $('#eStatus').innerHTML = h;
}
async function emailConnect(btn) {
  const body = { preset: $('#eProv').value, user: $('#eUser').value.trim(), password: $('#ePass').value };
  Object.entries(EF).forEach(([f, sel]) => { body[f] = $(sel).value.trim(); });
  btn.disabled = true; $('#eStatus').textContent = 'connecting and testing…';
  try {
    const r = await api('/api/email/connect', body); if (r.error) return emailLine(null, r.error);
    $('#ePass').value = ''; EM.status = r;
    if (!r.configured) return emailLine(null, 'enter the app password to finish connecting');
    const t = await api('/api/email/test', {}); emailLine(t.error ? null : t, t.error);
    load();
  } finally { btn.disabled = false; }
}
async function emailSend(btn) {
  btn.disabled = true;
  try { const r = await api('/api/email/test_send', {}); if (r.error) return emailLine(null, r.error); toast('test email sent to ' + r.to + ': check that inbox', 'ok'); emailLine(); }
  finally { btn.disabled = false; }
}
async function emailDisconnect() {
  const s = EM.status;
  if (!confirm(s.auth === 'oauth' ? `Sign out and revoke Lodestar's access to ${s.user}? Lodestar stops reading and sending mail until you sign in again.`
    : 'Remove the stored app password? Lodestar stops reading and sending mail until you connect again.')) return;
  const r = await api('/api/email/disconnect', {}); if (r.error) return emailLine(null, r.error);
  EM.status = r; emailLine(); toast(r.note || 'email disconnected', 'ok'); load();
}
async function setVault() { const r = await api('/api/vault', { name: $('#vName').value, user: $('#vUser').value, value: $('#vVal').value }); toast(r.error || 'stored', r.error ? 'err' : 'ok'); $('#vVal').value = ''; load(); }

/* ---- profile and coach ---- */
let PROFILE_LOADED = '';  // last text loaded from / saved to disk: tells unsaved editor edits apart
async function loadProfile() { $('#pText').value = PROFILE_LOADED = (await api('/api/profile')).text; }
function adjustProfile(btn) {
  const ins = $('#pAdj').value.trim(); if (!ins) return toast('type an instruction first', 'err');
  run('adjust', { text: $('#pText').value, instruction: ins, kind: 'master profile' }, r => { $('#pText').value = r.text; toast('adjusted; review, then Save', 'ok'); }, btn);
}
/* ---- profile bank: saved resumes + pooled facts (lodestar/profile.py) ---- */
let BANK = null;
async function loadBank() { const r = await api('/api/profile/bank'); if (!r.error) renderBank(r); }
function renderBank(v) {
  BANK = v; const b = v.bank, chip = (kind, i, label) => `<span class="pill">${esc(label)} <button class="b ghost sm" aria-label="remove" onclick="bankRemove('${kind}',${i})">×</button></span>`;
  $('#liUrl').value = b.contact.linkedin || ''; $('#liExport').href = v.linkedin_export_url;
  $('#bSkills').innerHTML = b.skills.map((s, i) => chip('skills', i, s.name + (s.category ? ' · ' + s.category : ''))).join(' ') || '<span class="muted">none yet: import a resume or LinkedIn, or add one</span>';
  $('#bLangs').innerHTML = b.languages.map((l, i) => chip('languages', i, l.name + (l.proficiency ? ' · ' + l.proficiency : ''))).join(' ') || '<span class="muted">none yet</span>';
  $('#bCerts').innerHTML = b.certifications.map((c, i) => chip('certifications', i, c.name + (c.issuer ? ' · ' + c.issuer : ''))).join(' ') || '<span class="muted">none yet</span>';
  $('#bCounts').textContent = `${b.experience.length} roles · ${b.education.length} education · ${b.certifications.length} certifications · ${b.projects.length} projects · ${b.resumes.length} saved resume(s)`;
  $('#bResumes').innerHTML = b.resumes.map(r => `<div>${esc(r.added.slice(0, 10))} <span class="pill">${esc(r.source)}</span>${esc(r.name)} <span class="muted">resumes/${esc(r.file)}</span></div>`).join('') || '<div class="muted">none yet</div>';
  $('#bOnFile').style.display = v.on_file ? '' : 'none'; $('#bOnFile').textContent = v.on_file;
}
async function bankOp(body, okMsg) {
  if (body.op === 'contact' && !String(body.value || '').trim()) return toast('paste your LinkedIn profile URL first', 'err');
  if (body.op === 'add' && !String(body.name || '').trim()) return toast('type a name first', 'err');
  const r = await api('/api/profile/bank', body);
  if (r.error) return toast('error: ' + r.error, 'err');
  renderBank(r);
  if (!r.changed) return toast(body.op === 'add' ? 'already in the bank (or not a valid entry)' : 'nothing changed', 'err');
  toast(okMsg, 'ok');
  if (body.op === 'add') ({ skills: ['#bSkill', '#bSkillCat'], languages: ['#bLang', '#bLangLvl'], certifications: ['#bCert', '#bCertIss'] }[body.kind] || []).forEach(s => { $(s).value = ''; });
}
function bankRemove(kind, i) { const it = BANK.bank[kind][i]; if (it) bankOp({ op: 'remove', kind, name: it.name }, 'removed ' + it.name); }
function importToBank(inputId, linkedin, btn) {
  const f = $('#' + inputId).files[0]; if (!f) return toast('choose a file first', 'err');
  const rd = new FileReader();
  rd.onload = () => run('profile_import', { name: f.name, data: rd.result.split(',')[1], linkedin, ai: $('#pNoAi').checked ? false : undefined }, r => {
    renderBank(r);
    const got = Object.entries(r.added).filter(([, n]) => n).map(([k, n]) => n + ' ' + k).join(', ') || 'nothing new';
    toast(`${r.new_file ? 'saved' : 'already saved'} ${f.name}: ${got} (${r.used_ai ? 'AI' : 'offline'} extraction)${r.seeded_master ? '; master profile filled in' : ''}`, 'ok');
    if (r.seeded_master) {  // never clobber text typed into the editor but not saved yet
      if ($('#pText').value === PROFILE_LOADED) loadProfile();
      else toast('profile.md was filled in from the bank; your unsaved editor text was kept (Save would replace the filled-in file)', 'err');
    }
    if (!linkedin) { $('#pImport').value = r.text; $('#pImport').style.display = ''; $('#pImportActions').style.display = ''; }
  }, btn);
  rd.readAsDataURL(f);
}
function rebuildMaster(btn) {
  const dirty = $('#pText').value !== PROFILE_LOADED;
  if (!confirm('Replace profile.md with a version built from the bank? The saved file is snapshotted to profile-history/ first.' +
    (dirty ? '\n\nThe editor has UNSAVED changes; they are not in any snapshot and will be lost. Save first to keep them.' : ''))) return;
  run('profile_rebuild', {}, r => { $('#pText').value = PROFILE_LOADED = r.text; renderBank(r); toast('master rebuilt from the bank', 'ok'); }, btn);
}
const editable = n => (S.doc_names || []).includes(n);  // coverage.json, gap.json, bullets.json are computed, not edited
function openEditor(n, text) { const ed = $('#docEdit'); ed.value = text; ed.dataset.name = n; ed.dataset.open = '1'; ed.style.display = $('#docSave').style.display = ''; }
function editDoc() {
  const n = $('#docTabs button.on')?.textContent; if (!n || n === 'timeline' || n === 'description') return toast('pick a document tab first', 'err');
  if (!editable(n)) return toast(`${n} is computed by Lodestar and cannot be edited; re-run the action that makes it`, 'err');
  openEditor(n, cur.docs[n] || '');
}
async function saveDoc() {
  const n = $('#docEdit').dataset.name; const r = await api('/api/docs/' + cur.job.id, { name: n, text: $('#docEdit').value });
  if (r.error) return toast(r.error, 'err');
  cur.docs = r.docs; $('#docEdit').dataset.open = ''; showDoc(n, $('#docTabs button.on')); toast('saved ' + n, 'ok');
}
function adjustDoc(btn) {
  const n = $('#docTabs button.on')?.textContent, ins = $('#dAdj').value.trim();
  if (!n || n === 'timeline' || n === 'description') return toast('pick a document tab first', 'err');
  if (!editable(n)) return toast(`${n} is computed by Lodestar and cannot be adjusted`, 'err');
  if (!ins) return toast('type an instruction first', 'err');
  const kind = n.includes('cover') ? 'cover letter' : n.includes('resume') ? 'resume' : 'document';
  run('adjust', { text: cur.docs[n], instruction: ins, kind }, r => { openEditor(n, r.text); toast('adjusted; review, then Save document', 'ok'); }, btn);
}
function reviewDoc(btn) {  // reviews the open document, unsaved edits included; result goes to AI output, nothing is saved
  const n = $('#docTabs button.on')?.textContent;
  if (!n || !n.includes('resume')) return toast('Review critiques a resume: open the resume tab first', 'err');  // the prompt is resume-specific
  const text = $('#docEdit').style.display !== 'none' && $('#docEdit').dataset.name === n ? $('#docEdit').value : cur.docs[n];
  if (!(text || '').trim()) return toast('this document is empty', 'err');
  run('review', { text }, r => { $('#jOut').textContent = r.text; }, btn);
}
async function saveProfile() {
  const text = $('#pText').value, r = await api('/api/profile', { text });
  if (r.error) return toast('save failed: ' + r.error, 'err');
  PROFILE_LOADED = text;
  toast('profile saved (previous version kept in profile-history/)', 'ok'); loadBank();
}
function fillCoachJobs() {  // rebuilt on every refresh so jobs added later appear; keeps the selected job
  const keep = $('#cJob').value;
  $('#cJob').innerHTML = S.jobs.map(j => `<option value="${j.id}">#${j.id} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
  if (S.jobs.some(j => String(j.id) === keep)) $('#cJob').value = keep;
}
let MOCK = { session: null, secs: 0 };  // the scored session of this mock interview; seconds dictated for the next answer
function resetChat() {
  const mock = $('#cMode').value === 'mock';
  MOCK = { session: null, secs: 0 }; $('#mockSum').style.display = 'none'; $('#mockSum').textContent = '';
  $('#cJob').style.display = $('#cSpeakL').style.display = mock ? '' : 'none';
  window.speechSynthesis?.cancel();
  fillCoachJobs();
  chatHist = [];
  $('#chat').innerHTML = `<div class="msg ai">${mock ? 'Mock interview ready. Send any message to begin; the interviewer asks one question at a time. Type "done" for a scored debrief.' : 'Ask me anything about your search. I can see your profile and tracker.'}</div>`;
}
function sendChat() {
  const q = $('#cIn').value.trim(); if (!q) return; $('#cIn').value = '';
  chatHist.push({ role: 'user', content: q }); $('#chat').insertAdjacentHTML('beforeend', `<div class="msg me">${esc(q)}</div>`);
  const council = $('#cCouncil').checked, mock = $('#cMode').value === 'mock';
  const action = mock ? 'mock' : council ? 'council' : 'chat';
  const params = mock ? { id: $('#cJob').value, messages: chatHist, session: MOCK.session, seconds: MOCK.secs || undefined } : council ? { prompt: q, messages: chatHist } : { messages: chatHist };
  MOCK.secs = 0;
  run(action, params, r => {
    const a = council && !mock ? r.synthesis : r.reply; chatHist.push({ role: 'assistant', content: a });
    if (r.card) { MOCK.session = r.card.session; $('#chat').insertAdjacentHTML('beforeend', cardHtml(r.card)); mockSummary(r.card); }
    $('#chat').insertAdjacentHTML('beforeend', `<div class="msg ai">${esc(a)}</div>`); $('#chat').scrollTop = 1e9;
    if (mock && $('#cSpeak').checked && window.speechSynthesis) {  // browser text-to-speech: practise listening, then answer aloud
      const u = new SpeechSynthesisUtterance(a); u.lang = navigator.language || 'en-US'; speechSynthesis.speak(u);
    }
    if (r.path) toast('transcript and debrief saved to mock_interview.md in the job', 'ok');
  }, $('#cGo'));
}
function dictate() {  // browser speech recognition; audio goes only where the browser's own service sends it
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast('this browser has no speech recognition (try Chrome or Edge)', 'err');
  const r = new SR(); r.lang = navigator.language || 'en-US'; r.interimResults = false;
  $('#cMic').disabled = true;
  const t0 = performance.now();  // ponytail: the whole listening time, pauses included; wpm is a rough guide
  r.onresult = e => { $('#cIn').value = ($('#cIn').value + ' ' + e.results[0][0].transcript).trim(); MOCK.secs += (performance.now() - t0) / 1000; };
  r.onerror = e => toast('dictation: ' + e.error, 'err');
  r.onend = () => { $('#cMic').disabled = false; };
  r.start();
}

/* ---- mock score cards, session summary, trend (interview.score_answer / sessions) ---- */
function cardHtml(c) {
  const r = c.rubric, took = c.seconds ? c.seconds + ' s spoken' : '~' + c.est_seconds + ' s';
  const pace = { ok: 'within', short: 'under', long: 'over' }[c.pace] || '';
  return `<div class="mcard" role="note" aria-label="score card for your answer"><div><b>${esc(c.words)}</b> words · ${esc(took)} <span class="${c.pace === 'ok' ? '' : 'lo'}">(${pace} the 60-120 s target)</span>${c.wpm ? ' · ' + esc(c.wpm) + ' wpm' : ''}</div>`
    + (r ? `<div>STAR S${esc(r.situation)} T${esc(r.task)} A${esc(r.action)} R${esc(r.result)} (average ${esc(r.star)}/2) · relevance ${esc(r.relevance)}/2 · specificity ${esc(r.specificity)}/2 · numbers ${r.metrics_used ? 'yes' : 'no'}</div>`
      + (r.one_fix ? `<div><b>one fix:</b> ${esc(r.one_fix)}</div>` : '') + (r.suggested_rewrite ? `<details><summary>suggested rewrite</summary>${esc(r.suggested_rewrite)}</details>` : '')
      : `<div class="muted">no STAR rubric (${esc(c.rubric_error || 'needs an AI provider')}); the numbers above are offline</div>`)
    + (c.repeated.length ? `<div class="muted">repeated: ${esc(c.repeated.join(', '))}</div>` : '')
    + (c.jd_keywords.length ? `<div class="muted">posting keywords used: ${esc(c.jd_keywords.join(', '))}</div>` : '') + '</div>';
}
function mockSummary(c) {
  const a = c.averages, f = v => v == null ? '-' : v;
  $('#mockSum').style.display = '';
  $('#mockSum').textContent = `session #${c.session}: ${a.answers} answer(s), ${a.scored} scored · STAR average ${f(a.star)}/2 · relevance ${f(a.relevance)}/2 · specificity ${f(a.specificity)}/2`
    + (a.metrics_used != null ? ` · numbers in ${Math.round(a.metrics_used * 100)}% of answers` : '') + ` · ${f(a.words)} words on average`;
}
function renderTrend() {
  const pts = (S.mock_sessions || []).filter(s => s.averages && s.averages.star != null);
  $('#mockTrend').style.display = pts.length ? '' : 'none'; if (!pts.length) return;
  const W = 560, H = 130, P = 22, n = pts.length;
  const x = i => P + (n === 1 ? (W - 2 * P) / 2 : i * (W - 2 * P) / (n - 1)), y = v => H - P - Math.max(0, Math.min(2, Number(v) || 0)) / 2 * (H - 2 * P);
  const last = pts[n - 1].averages.star;
  $('#trendSvg').innerHTML = `<svg class="trend" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(`STAR average per mock session: ${n} session(s), latest ${last} of 2`)}">`
    + [0, 1, 2].map(v => `<line x1="${P}" x2="${W - P}" y1="${y(v)}" y2="${y(v)}" class="gl"/><text x="4" y="${y(v) + 4}">${v}</text>`).join('')
    + `<polyline points="${pts.map((s, i) => x(i).toFixed(1) + ',' + y(s.averages.star).toFixed(1)).join(' ')}" class="pl"/>`
    + pts.map((s, i) => `<circle cx="${x(i).toFixed(1)}" cy="${y(s.averages.star).toFixed(1)}" r="4"><title>${esc(`${localTs(s.ts, 16)} · #${s.job_id} ${s.company || ''} · STAR ${s.averages.star}/2 over ${s.averages.scored} answer(s)`)}</title></circle>`).join('') + '</svg>';
}

/* ---- insights, weekly goals, offers, activity log (extras.analytics, comp.compare, extras.activity_report) ---- */
let INS = null, OFF = null;  // server data stays in JS; markup carries only indexes and numbers
const pctx = v => Math.round(Number(v) * 100) + '%', num = v => Number(v || 0).toLocaleString();
const SERIES = [['applications', 'applications'], ['interviews', 'interviews'], ['offers', 'offers'], ['contacts', 'people contacted'], ['mock_sessions', 'mock sessions']];
async function loadInsights() {
  const [a, o] = await Promise.all([api('/api/analytics?weeks=' + Number($('#insRange').value || 12)), api('/api/offers')]);
  if (a.error || o.error) return toast('error: ' + (a.error || o.error), 'err');
  INS = a; OFF = o; renderInsights(); renderOffers();
  if (!$('#acFrom').value) { const t = new Date(), m = new Date(t); m.setDate(t.getDate() - (t.getDay() + 6) % 7); $('#acFrom').value = m.toLocaleDateString('en-CA'); $('#acTo').value = t.toLocaleDateString('en-CA'); }
  $('#acMin').value = S && S.prefs.activity_weekly_min ? S.prefs.activity_weekly_min : '';
}
function barSvg(label, pts) {  // pts [{x, v, t}]: small bar chart; <title> per bar plus the table under "as a table"
  const W = 260, H = 96, P = 18, n = pts.length || 1, max = Math.max(1, ...pts.map(p => p.v)), bw = (W - 2 * P) / n;
  return `<svg class="bars" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${esc(label)}"><title>${esc(label)}</title>`
    + pts.map((p, i) => { const h = (H - 2 * P) * p.v / max; return `<rect x="${(P + i * bw + 1).toFixed(1)}" y="${(H - P - h).toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${h.toFixed(1)}"><title>${esc(p.t)}</title></rect>`; }).join('')
    + `<line x1="${P}" x2="${W - P}" y1="${H - P}" y2="${H - P}" class="gl"/><text x="${P}" y="${H - 4}">${esc(pts[0] ? pts[0].x : '')}</text><text x="${W - P}" y="${H - 4}" text-anchor="end">${esc(pts.length ? pts[pts.length - 1].x : '')}</text><text x="${P}" y="12">max ${max}</text></svg>`;
}
function rateRows(groups) {  // CSS bars with the numbers beside them; under min_n only the count
  return groups.map(g => `<div class="cov-row"><span title="${esc(g.group)}">${esc(g.group)}</span>` + (g.enough
    ? `<span class="bar" role="img" aria-label="${esc(g.group)}: response ${pctx(g.response_rate)} of ${Number(g.n)}"><i style="width:${Math.round(Number(g.response_rate) * 100)}%"></i></span><span>${pctx(g.response_rate)} · interview ${pctx(g.interview_rate)} · n=${Number(g.n)}</span>`
    : `<span class="muted">not enough data yet</span><span class="muted">n=${Number(g.n)} (need ${Number(INS.min_n)})</span>`) + '</div>').join('') || '<div class="muted">no applications yet</div>';
}
function renderInsights() {
  const a = INS, goals = (S && S.prefs.weekly_goals) || {};
  $('#goalForm').innerHTML = a.goal_keys.map(k => `<label class="fld">${esc(k.replace('_', ' '))} a week<input id="g_${esc(k)}" type="number" min="0" max="1000" style="width:110px" value="${goals[k] ? Number(goals[k]) : ''}" placeholder="not set"></label>`).join('')
    + '<button class="b sm" onclick="saveGoals()">Save goals</button>';
  $('#goalBars').innerHTML = a.goals.map(g => `<div class="row"><label>${esc(g.label)} <progress value="${Math.min(Number(g.done), Number(g.target))}" max="${Number(g.target)}"></progress> ${Number(g.done)} of ${Number(g.target)} this week${g.done >= g.target ? ' ✓' : ''}</label></div>`).join('')
    || '<div class="muted">no goals set</div>';
  $('#insWeeks').innerHTML = SERIES.map(([k, label]) => {
    const total = a.weeks.reduce((s, w) => s + Number(w[k]), 0);
    return `<div><b>${esc(label)}</b> <span class="muted">${total} in ${a.weeks.length} weeks</span>${barSvg(`${label} per week, ${a.weeks.length} weeks, ${total} in total`, a.weeks.map(w => ({ x: w.week, v: Number(w[k]), t: `week of ${w.start}: ${w[k]} ${label}` })))}</div>`;
  }).join('');
  $('#insWeeksTable').innerHTML = `<table class="kw"><thead><tr><th>week</th><th>from</th>${SERIES.map(([, l]) => `<th>${esc(l)}</th>`).join('')}</tr></thead><tbody>`
    + a.weeks.map(w => `<tr><td>${esc(w.week)}</td><td>${esc(w.start)}</td>${SERIES.map(([k]) => `<td>${Number(w[k])}</td>`).join('')}</tr>`).join('') + '</tbody></table>';
  $('#insSource').innerHTML = rateRows(a.by_source);
  $('#insBand').innerHTML = rateRows(a.by_band) + '<div class="muted">bands of the match score (JD coverage or your own), applications that left "saved"</div>';
  const st = a.funnel.stages;
  $('#insFunnel').innerHTML = `<table class="kw"><thead><tr><th>stage</th><th>reached</th><th>moved on</th><th>conversion</th><th>median days to next</th></tr></thead><tbody>`
    + Object.entries(st).map(([s, d]) => `<tr><td>${esc(s)}</td><td>${Number(d.reached)}</td><td>${Number(d.advanced)}</td><td>${d.conversion == null ? '-' : pctx(d.conversion)}</td><td>${d.median_days_to_next == null ? '-' : esc(d.median_days_to_next)}</td></tr>`).join('') + '</tbody></table>'
    + (a.variants.length ? '<div class="row">' + a.variants.map(v => `<span class="pill">resume ${esc(v.variant)}: ${Number(v.applied)} sent, ${v.applied >= a.min_n ? pctx(v.interview_rate) + ' interview' : 'not enough data yet'}</span>`).join('') + '</div>' : '<div class="muted">no tailored resume sent yet</div>');
}
async function saveGoals() {
  const value = Object.fromEntries(INS.goal_keys.map(k => [k, $('#g_' + k).value || 0]));
  const r = await api('/api/prefs', { key: 'weekly_goals', value }); if (r.error) return toast('error: ' + r.error, 'err');
  toast('weekly goals saved', 'ok'); await load(); loadInsights();
}
const OF_LABEL = { base: 'base', bonus: 'bonus (target)', sign_on: 'sign-on', match: 'retirement match', equity_year1: 'equity, year 1', year1_cash: 'year-1 cash', year1_total: 'year-1 total', four_year_total: '4-year total' };
function renderOffers() {
  const o = OFF, rows = o.offers, best = (k, r) => (o.best[k] || []).includes(r.job_id);
  const cell = v => v == null ? '-' : esc(v);
  $('#offerTable').innerHTML = rows.length ? `<table class="kw offers"><thead><tr><th></th>${rows.map(r => `<th><a href="#" onclick="go('board');openJob(${Number(r.job_id)});return false">#${Number(r.job_id)} ${esc(r.company)}</a><div class="muted">${esc(r.title)} · ${esc(r.status)}</div></th>`).join('')}</tr></thead><tbody>`
    + Object.entries(OF_LABEL).map(([k, l]) => `<tr><td>${l}</td>${rows.map(r => `<td class="${best(k, r) ? 'best' : ''}">${num(r.total[k])}${best(k, r) ? ' <span class="sr">best</span>' : ''}</td>`).join('')}</tr>`).join('')
    + `<tr><td>market range</td>${rows.map(r => `<td>${r.market ? num(r.market.low) + '–' + num(r.market.high) + (r.market.delta ? ` <span class="muted">(${r.market.delta > 0 ? '+' : ''}${num(r.market.delta)})</span>` : ' <span class="muted">(within)</span>') : '<span class="muted">none recorded</span>'}</td>`).join('')}</tr>`
    + (o.floor ? `<tr class="private"><td>vs your salary floor <span class="muted">(private)</span></td>${rows.map(r => `<td>${r.vs_floor == null ? '-' : (r.vs_floor >= 0 ? '+' : '') + num(r.vs_floor)}</td>`).join('')}</tr>` : '')
    + ['remote', 'start_date', 'deadline'].map(k => `<tr><td>${k.replace('_', ' ')}</td>${rows.map(r => `<td>${cell(r.offer[k])}</td>`).join('')}</tr>`).join('')
    + `<tr><td>estimates</td>${rows.map(r => `<td class="muted">${esc(r.total.estimates.join('; ') || 'none')}</td>`).join('')}</tr></tbody></table>`
    : '<div class="empty">No live offers. Record one below (the job moves to "offer"), or move a job to "offer" on the Board.</div>';
  const live = S.jobs.filter(j => !['rejected', 'withdrawn'].includes(j.status)), keep = $('#ofJob').value;
  $('#ofJob').innerHTML = live.map(j => `<option value="${Number(j.id)}">#${Number(j.id)} ${esc(j.company)} - ${esc(j.title)} (${esc(j.status)})</option>`).join('');
  if (live.some(j => String(j.id) === keep)) $('#ofJob').value = keep; else if (rows.length) $('#ofJob').value = String(rows[0].job_id);
  fillOffer();
  const ck = $('#ctrJob').value;
  $('#ctrJob').innerHTML = rows.map(r => `<option value="${Number(r.job_id)}">#${Number(r.job_id)} ${esc(r.company)} - ${esc(r.title)}</option>`).join('');
  if (rows.some(r => String(r.job_id) === ck)) $('#ctrJob').value = ck;
  renderCite();
}
const OF_INPUT = { start_date: 'type="date"', deadline: 'type="date"', notes: 'class="grow" maxlength="2000"', bonus_pct: 'type="number" min="0" max="200" step="0.5"', retirement_match_pct: 'type="number" min="0" max="100" step="0.5"', vest_years: 'type="number" min="1" max="10"', cliff_months: 'type="number" min="0" max="60"' };
function fillOffer() {
  const id = Number($('#ofJob').value), o = (OFF.offers.find(r => r.job_id === id) || {}).offer || {};
  $('#ofForm').innerHTML = OFF.fields.map(k => k === 'remote'
    ? `<label class="fld">workplace<select id="of_remote"><option value="">-</option>${['onsite', 'hybrid', 'remote'].map(v => `<option ${o.remote === v ? 'selected' : ''}>${v}</option>`).join('')}</select></label>`
    : `<label class="fld${k === 'notes' ? ' grow' : ''}">${esc(k.replace(/_/g, ' '))}<input id="of_${esc(k)}" ${OF_INPUT[k] || 'type="number" min="0" step="1000" style="width:120px"'} value="${esc(o[k] ?? '')}"></label>`).join('');
}
async function saveOffer() {
  const id = Number($('#ofJob').value); if (!id) return toast('pick a job first', 'err');
  const body = Object.fromEntries(OFF.fields.map(k => [k, $('#of_' + k).value.trim()]));
  if (!OFF.offers.some(o => o.job_id === id) && !Object.values(body).some(v => v)) return toast('fill in at least one field', 'err');
  const r = await api(`/api/offers/${id}`, body);
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('offer saved', 'ok'); await load(); loadInsights();
}
let CITE = [];  // [job_id:field, label]; checkboxes carry only an index
function renderCite() {
  const id = Number($('#ctrJob').value), names = { base: 'base', bonus_pct: 'target bonus %', sign_on: 'sign-on', equity_value_estimate: 'equity (estimate)', year1_total: 'year-1 total' };
  CITE = OFF.offers.filter(r => r.job_id !== id).flatMap(r => OFF.cite.map(f => [f, f === 'year1_total' ? r.total.year1_total : r.offer[f]]).filter(([, v]) => v)
    .map(([f, v]) => [`${r.job_id}:${f}`, `#${r.job_id} ${r.company}: ${names[f] || f} ${num(v)}${f === 'bonus_pct' ? '%' : ''}`]));
  $('#ctrCite').innerHTML = CITE.map(([, l], i) => `<label class="muted"><input type="checkbox" id="cite${i}"> ${esc(l)}</label>`).join('')
    || '<span class="muted">no other offer with figures to cite: record a competing offer first, or write your ask below</span>';
}
function counterOptions(btn) {
  const id = Number($('#ctrJob').value); if (!id) return toast('record an offer first', 'err');
  draftOptions('counter', { id, cite: CITE.filter((c, i) => $('#cite' + i)?.checked).map(c => c[0]), ask: $('#ctrAsk').value }, 'ctrOpts', btn);
}
function draftCounter(btn) {
  const id = Number($('#ctrJob').value); if (!id) return toast('record an offer first', 'err');
  const cite = CITE.filter((c, i) => $('#cite' + i)?.checked).map(c => c[0]);
  run('counter', { id, cite, ask: $('#ctrAsk').value, template: $('#ctrTpl').checked }, r => { show('ctrOut', mailText(r)); }, btn);
}
function activity(btn, fmt) {
  run('activity', { from: $('#acFrom').value, to: $('#acTo').value, fmt }, r => {
    if (r.path) toast((fmt === 'html' ? 'printable page opened in your browser: ' : 'CSV written: ') + r.path, 'ok');
    const by = {}; r.rows.forEach(x => { const d = new Date(x.date + 'T00:00:00'); d.setDate(d.getDate() - (d.getDay() + 6) % 7); (by[d.toLocaleDateString('en-CA')] ||= []).push(x); });
    $('#acOut').innerHTML = `<div class="muted">${esc(r.note)}</div>` + r.weeks.map(w => `<h4>Week of ${esc(w.week)}: ${Number(w.count)} activit${w.count === 1 ? 'y' : 'ies'}${r.minimum ? ` · minimum ${Number(r.minimum)} <span class="pill ${w.met ? 'ok' : ''}">${w.met ? 'met' : 'not met'}</span>` : ''}</h4>`
      + ((by[w.week] || []).length ? `<table class="kw"><thead><tr><th>date</th><th>activity</th><th>employer</th><th>position</th><th>method</th><th>contact</th><th>result</th></tr></thead><tbody>`
        + by[w.week].map(x => `<tr><td>${esc(x.date)}</td><td>${esc(x.activity.replace('_', ' '))}</td><td>${esc(x.employer)}</td><td>${esc(x.position)}</td><td>${esc(x.method)}</td><td>${esc(x.contact)}</td><td>${esc(x.result)}</td></tr>`).join('') + '</tbody></table>' : '<div class="muted">nothing recorded</div>')).join('');
  }, btn);
}

/* ---- drawer keyboard: Esc closes (asking first when typed text would be lost), Tab stays inside (aria-modal) ---- */
function drawerDirty() {  // a document editor that differs from the saved file, or any typed text field in the drawer
  const ed = $('#docEdit');
  if (ed && ed.dataset.open === '1' && cur && ed.value !== (cur.docs[ed.dataset.name] || '')) return true;
  return $$('#drawer input:not([type=checkbox]):not([type=hidden]), #drawer textarea').some(e => e !== ed && e.value !== e.defaultValue);
}
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex="0"]';
document.addEventListener('keydown', e => {
  const d = $('#drawer'); if (!d.classList.contains('open')) return;
  if (e.key === 'Escape') { if (!drawerDirty() || confirm('Close and discard what you typed in this drawer?')) closeDrawer(); return; }
  if (e.key !== 'Tab') return;
  const f = $$('#drawer ' + FOCUSABLE.split(', ').join(', #drawer ')).filter(x => x.offsetParent !== null); if (!f.length) return;
  const at = document.activeElement, first = f[0], last = f[f.length - 1];
  if (!d.contains(at) || (e.shiftKey && at === first) || (!e.shiftKey && at === last)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
});
window.addEventListener('beforeunload', e => {  // a reload or closed window must not drop an unsaved profile or document
  if (($('#pText').value !== PROFILE_LOADED) || ($('#drawer').classList.contains('open') && drawerDirty())) { e.preventDefault(); e.returnValue = ''; }
});
load(); loadProfile(); loadBank(); setInterval(load, 60000);
