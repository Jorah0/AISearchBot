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
  if (tab === 'setup') { loadEmail(); loadAiHistory(); restoreLoad(); acctLoad(); }
  if (tab === 'studio') loadStudio();
  if (tab === 'search') { loadAllJobs(); spLoad(); }
  if (tab === 'careers') loadCareers();
  if (tab === 'profile') loadMaster();  // the master card follows background rebuilds
}

/* ---- background tasks ---- */
async function run(action, params, done, btn, fail) {  // fail(error): the caller also shows a refusal in place
  const had = btn && document.activeElement === btn;  // disabling a focused button drops focus to the page
  if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = 'working…'; }
  const finish = () => {
    if (!btn) return;
    btn.disabled = false; btn.textContent = btn.dataset.label;
    if (had && btn.isConnected && (!document.activeElement || document.activeElement === document.body)) btn.focus();  // keyboard users keep their place
  };
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
  const nq = (S.questions || []).filter(q => q.blocking).length, badge = $('#inboxN');  // approvals + questions for you
  badge.textContent = S.pending.length + nq; badge.classList.toggle('zero', !(S.pending.length + nq));
  renderOnboard(); renderLoop(); renderUpdate(); renderAutopilot(); $('#ver').textContent = 'Lodestar ' + S.version;
  if (!$('#fStatus').options.length) initFilters();
  renderBoard(); renderQuestions(); renderInbox(); renderSearchless(); renderMonitor(); renderAnswers(); renderStories(); renderIdeas(); renderTools(); renderSetup(); fillCoachJobs(); renderTrend();
  fitRefresh();
  if (ADV_AI !== hasAI()) aiSlots();  // the tab headers' AI toolbars: painted once, again when a provider comes or goes
}

/* ---- board: filters, sort, view (kept in localStorage), drag and drop, table, Today ---- */
const VIEW_KEY = 'ls_board_view';
let V = { view: 'board', key: 'updated_at', dir: -1, q: '', status: '', remote: '', minSal: '', tag: '', dl: false };
try { Object.assign(V, JSON.parse(localStorage.getItem(VIEW_KEY) || '{}')); } catch (_) { /* storage blocked or corrupt: defaults */ }
const saveView = () => { try { localStorage.setItem(VIEW_KEY, JSON.stringify(V)); } catch (_) { /* storage blocked */ } };
const SORTS = { updated: ['updated_at', -1], stale: ['updated_at', 1], fit: ['fit_score', -1], match: ['match_score', -1], salary: ['salary', -1], excitement: ['excitement', -1], deadline: ['deadline', 1] };
const tagsOf = j => (j.tags || '').split(',').map(t => t.trim()).filter(Boolean);
const payOf = j => j.salary_max ?? j.salary_min ?? null;
const sortVal = (j, k) => k === 'salary' ? payOf(j) : k === 'next' ? ((S.pipeline || {})[j.id] || {}).next ?? null : k === 'status' ? S.statuses.indexOf(j.status) : j[k] ?? null;
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
  if (V.key === k) V.dir = -V.dir; else { V.key = k; V.dir = ['fit_score', 'match_score', 'excitement', 'salary', 'updated_at'].includes(k) ? -1 : 1; }
  saveView(); syncSort(); renderBoard();
}
function clearFilters() {
  Object.assign(V, { q: '', status: '', remote: '', minSal: '', tag: '', dl: false }); saveView();
  $('#fQ').value = $('#fStatus').value = $('#fRemote').value = $('#fSal').value = $('#fTag').value = ''; $('#fDl').checked = false;
  renderBoard();
}
function toggleView() { V.view = V.view === 'table' ? 'board' : 'table'; saveView(); renderBoard(); }
function card(j) {
  const chips = [fitBadge(j), stars(j), salaryText(j) && `<span>${esc(salaryText(j))}</span>`,
    where(j) && `<span>${esc(where(j))}</span>`, deadlineChip(j), pipeChip(j), staleChip(j.ghost), sponsorChip(j.sponsor), warmChip(j.warm), payChip(j.pay)].filter(Boolean).join('');
  return `<div class="card ${S.followups.includes(j.id) ? 'late' : ''} ${cur && cur.job.id === j.id ? 'sel' : ''}" data-id="${j.id}" draggable="true" tabindex="0" role="button"
    aria-label="${esc(`#${j.id} ${j.company} - ${j.title}, ${j.status}`)}" ondragstart="event.dataTransfer.setData('text/plain','${j.id}');event.dataTransfer.effectAllowed='move'"
    onclick="openJob(${j.id})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();openJob(${j.id})}">
    <div class="co">${esc(j.company)}</div><div class="ti">${esc(j.title)}</div>${chips ? `<div class="chips">${chips}</div>` : ''}
    <div class="meta"><span>#${j.id}</span><span>${esc(localTs(j.updated_at, 10))}</span></div></div>`;
}
/* ---- fit score (lodestar/fit.py): deterministic, private; the board carries score, known, stale and the top chips ---- */
const fitBand = n => n >= 80 ? 'hi' : n >= 60 ? 'mid' : n >= 40 ? 'lo' : 'bad';
function fitBadge(j) {
  if (j.fit_score == null) return '';
  const tip = [...(j.fit_chips || []), j.fit_partial ? `partial: measured ${Math.round((j.fit_known || 0) * 100)}% of the fit (open the job for what is missing)` : '',
    j.fit_stale ? 'out of date: your profile, preferences or weights changed; re-scoring' : ''].filter(Boolean).join('\n');
  return `<span class="chip fit fit-${fitBand(j.fit_score)}${j.fit_stale ? ' stale-fit' : ''}" title="${esc(tip)}">fit ${esc(j.fit_score)}${j.fit_partial ? ' · partial' : ''}${j.fit_blocked ? ' · blocked' : ''}</span>`;
}
let FIT_ASKED = null;  // stale fits are re-scored on the server (no AI, silent), then the board reloads; asked again only
function fitRefresh() {  // when the rev or the stale count moved, so a job that cannot be scored never loops
  const key = S.fit_rev + ':' + S.fit_stale;
  if (!S.fit_stale || !S.fit_rev || FIT_ASKED === key) return;
  FIT_ASKED = key; run('fit_refresh', {}, () => {});
}
const PART_NAME_FIT = { skills: 'Skills', role: 'Role', experience: 'Experience', location: 'Location', pay: 'Pay', ai: 'AI', mod: 'Modifiers' };
function fitGroup(d) {
  const f = d.fit, j = d.job;
  const btns = `<button class="b ghost sm" onclick="jobRun('job_ai',{},this)" title="one AI call judges this posting against your profile (no salary floor sent); its score joins the fit as one more part">AI fit</button>`
    + (f ? `<button class="b ghost sm" onclick="fitWhy()">Why not higher?</button>` : '');
  if (!f) return `<div class="group" id="jFit"><h4>Fit</h4><div class="muted">Not scored yet: the fit is worked out when the page refreshes, or with lodestar fit ${esc(j.id)}.</div><div class="row">${btns}</div></div>`;
  const chipsOf = p => f.chips.filter(c => c.part === p).map(c => `<span class="chip fitc${c.sign === '-' ? ' due' : ''}">${esc(c.sign + ' ' + c.text)}</span>`).join(' ');
  const rows = Object.entries(f.parts).map(([p, v]) => `<div class="cov-row fit-row"><span>${esc(PART_NAME_FIT[p] || p)} <span class="muted">(weight ${esc(v.w)})</span></span>`
    + (v.s == null ? '<span class="muted">not measured</span><span></span>' : `<span class="bar" role="img" aria-label="${esc(PART_NAME_FIT[p] || p)} ${esc(v.s)} of 100"><i style="width:${Math.max(0, Math.min(100, Number(v.s) || 0))}%"></i></span><span>${esc(v.s)}</span>`)
    + `</div><div class="chips">${chipsOf(p)}</div>`).join('');
  const mods = chipsOf('mod');
  return `<div class="group" id="jFit"><h4>Fit</h4>
    <div class="row"><b class="cov-score fit-${fitBand(f.score)}">fit ${esc(f.score)}</b>${f.partial ? '<span class="chip">partial</span>' : ''}${f.blocked ? '<span class="chip due">blocked</span>' : ''}
      ${j.fit_stale ? '<span class="chip stale">out of date</span>' : ''}<span class="muted">${esc(f.note || '')} · measured ${esc(Math.round(f.known * 100))}%</span></div>
    ${rows}${mods ? `<div class="chips"><span class="muted">modifiers:</span> ${mods}</div>` : ''}
    <div class="row">${btns}</div><div id="jFitWhy"></div>
    <div class="muted">Deterministic and private: your skills, role, years, location and pay against this posting, from your profile and Preferences. It never goes to an employer or an AI provider. Weights: Tools &gt; Preferences &gt; Fit weights.</div></div>`;
}
function fitWhy() {  // the parts sorted by the points they cost
  const f = cur && cur.fit; if (!f) return;
  const tot = Object.values(f.parts).filter(v => v.s != null).reduce((a, v) => a + v.w, 0) || 1;
  const lost = Object.entries(f.parts).map(([p, v]) => [p, v.s == null ? null : Math.round((100 - v.s) * v.w / tot * f.known)]).sort((a, b) => (b[1] ?? -1) - (a[1] ?? -1));
  $('#jFitWhy').innerHTML = '<ul>' + lost.map(([p, n]) => `<li>${esc(PART_NAME_FIT[p] || p)}: ${n == null ? 'not measured (pulls the score toward 50)' : 'costs about ' + esc(n) + ' points'}</li>`).join('')
    + f.mods.filter(m => m.d < 0).map(m => `<li>${esc(m.why)}: ${esc(m.d)} points</li>`).join('') + '</ul>';
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
let TODAY_ACT = [];  // the Today interview tips' actions; their buttons carry an index
function renderToday() {
  const t = S.today, el = $('#today');
  const item = (i, label, cls = '') => `<button class="b ghost sm ${cls}" onclick="openJob(${i.id})">${esc(label)} · #${i.id} ${esc(i.company)} - ${esc(i.title)}</button>`;
  TODAY_ACT = [];  // an interview within 48 h with readiness under 60: its top 'raise it' tip as a second button (no band here: no room for its qualifier)
  const tip = i => i.readiness && i.readiness.score < 60 && i.readiness.tip && i.readiness.action
    ? `<button class="b ghost sm tip" onclick="raiseAct(TODAY_ACT[${TODAY_ACT.push({ id: i.id, a: i.readiness.action }) - 1}].a,this,${Number(i.id)})">${esc(i.readiness.tip)}</button>` : '';
  const parts = [...t.actions.map(i => item(i, (i.overdue ? 'overdue ' + i.when : 'today') + ': ' + i.what, i.overdue ? 'due' : '')),
    ...t.deadlines.map(i => item(i, i.days === 0 ? 'deadline today' : `deadline in ${i.days}d`, 'due')),
    ...t.interviews.map(i => item(i, 'interview ' + i.when + (i.readiness ? ' · readiness ' + i.readiness.score : '')) + tip(i)), ...t.followups.map(i => item(i, 'follow up')),
    ...(t.closed || []).map(i => item(i, 'posting closed', 'due')),
    ...(t.contacts || []).map(c => `<button class="b ghost sm" onclick="openContact(${Number(c.id)})">get in touch (due ${esc(c.when)}) · ${esc(c.name)}${c.company ? ' (' + esc(c.company) + ')' : ''}</button>`)];
  const fits = (t.top_fits || []).map(f => `<div class="row"><span class="chip fit fit-${fitBand(f.fit)}">fit ${esc(f.fit)}</span><span>${esc(f.title)} @ ${esc(f.company)}${f.sources.length ? ' (' + esc(f.sources.map(srcLabel).join(', ')) + ')' : ''}</span>
    <button class="b ghost sm" onclick="trackFit(${Number(f.id)},this)">Track</button>${safeUrl(f.url) ? `<a class="b ghost sm" href="${esc(f.url)}" target="_blank" rel="noopener">Open</a>` : ''}</div>`);
  const em = (t.emails || []).map((s, i) => `<div class="row"><span class="chip ${s.priority === 1 ? 'due' : ''}">${esc(dueText(s.due))}</span><span>${esc(s.reason)} · #${Number(s.job_id)} ${esc(s.company)}${s.to ? ' → ' + esc(s.to) : ''}</span>
    <button class="b ghost sm" onclick="suggestDraft(${i},this)">Draft options</button><button class="b ghost sm" onclick="suggestDismiss(${i})">Dismiss for now</button></div>`);
  const nq = (S.questions || []).filter(q => q.blocking).length, bo = BOOSTS.t = t.boosters || [];
  el.style.display = parts.length || em.length || fits.length || bo.length || t.pending || nq ? '' : 'none';
  el.innerHTML = `<h3>Today</h3><div class="row">${parts.join('')}${t.pending ? `<button class="b sm" onclick="go('inbox')">${t.pending} waiting in the Inbox</button>` : ''}${nq ? `<button class="b sm" onclick="go('inbox')">${nq} question${nq === 1 ? '' : 's'} for you</button>` : ''}</div>`
    + (em.length ? `<h4>Suggested emails</h4>${em.join('')}` : '') + (fits.length ? `<h4>Top new fits</h4>${fits.join('')}` : '')
    + (bo.length ? `<h4>Chance boosters</h4>${bo.map((b, i) => boostRow(b, 't', i)).join('')}` : '');
}
async function trackFit(id, btn) {  // a user click: tracked directly, like the Search tab's track
  btn.disabled = true;
  const r = await api(`/api/listings/${id}/track`, {}); if (r.error) { btn.disabled = false; return toast('error: ' + r.error, 'err'); }
  toast(`tracked as #${r.id}`, 'ok'); await load(); openJob(r.id);
}
let SEL = new Set();  // table checkboxes; survives the 60 s refresh
const COLS = [['id', '#'], ['company', 'Company'], ['title', 'Title'], ['status', 'Status'], ['next', 'Next step'], ['salary', 'Salary'], ['fit_score', 'Fit'], ['match_score', 'Coverage'], ['excitement', 'Excitement'], ['deadline', 'Deadline'], ['location', 'Location'], ['updated_at', 'Last activity']];
function renderTable(jobs) {
  const shown = new Set(jobs.map(j => j.id)); SEL = new Set([...SEL].filter(id => shown.has(id)));  // bulk acts on what you see
  const sortAttr = k => V.key === k ? (V.dir > 0 ? 'ascending' : 'descending') : 'none';
  $('#jobTable').innerHTML = `<table class="jobs"><thead><tr><th><input type="checkbox" aria-label="select all shown jobs" ${jobs.length && SEL.size === jobs.length ? 'checked' : ''} onchange="selAll(this.checked)"></th>`
    + COLS.map(([k, l]) => `<th aria-sort="${sortAttr(k)}"><button class="th" onclick="sortBy('${k}')">${l}${V.key === k ? (V.dir > 0 ? ' ▲' : ' ▼') : ''}</button></th>`).join('') + '</tr></thead><tbody>'
    + jobs.map(j => `<tr class="${S.followups.includes(j.id) ? 'late' : ''}"><td><input type="checkbox" aria-label="select #${j.id}" ${SEL.has(j.id) ? 'checked' : ''} onchange="selOne(${j.id},this.checked)"></td>
      <td>${j.id}</td><td><a href="#" onclick="openJob(${j.id});return false">${esc(j.company)}</a></td><td>${esc(j.title)}</td><td>${esc(j.status)}</td><td>${pipeChip(j)}</td><td>${esc(salaryText(j))}</td>
      <td>${fitBadge(j)}</td><td>${esc(j.match_score ?? '')}</td><td>${stars(j)}</td><td>${deadlineChip(j)}</td><td>${esc(where(j))}</td><td>${esc(localTs(j.updated_at, 10))}</td></tr>`).join('')
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
function profileBadge(id) {  // the profile sections this job's resume.md drew on changed since it was made
  const ch = (S.jobs.find(x => x.id === id) || {}).profile_changed || [];
  return ch.length ? `<div class="warnbox" id="jProfileChanged">Profile changed since this resume was made (${esc(ch.join(', '))}). It was not rewritten: it may already have been sent. Tailor again to use the new profile.</div>` : '';
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
    ${aiMenu('job', j.id)}
${fitGroup(d)}
${boostGroup(d)}
${pipelineGroup(d)}
${detailsForm(j)}
${payGroup(d)}
${intelGroup(d)}
${peopleGroup(d)}
${readinessGroup(d)}
${roundsGroup(d)}

    <div class="group" id="jMatchG"><h4>Match</h4>
      <div class="row"><button class="b" onclick="jobMatch(this)">${savedCoverage(d) ? 'Recompute' : 'Compute'} JD coverage</button><button class="b ghost" onclick="jobLint(this)">Check resume</button><button class="b ghost" onclick="run('audit',{id:${j.id}},r=>{$('#jCheck').innerHTML=auditHtml(r)},this)">Audit resume.docx</button></div>
      <div class="muted">JD coverage is the share of the posting's keywords your current resume (tailored, else your profile) mentions: a guide for tailoring, not an ATS pass/fail. No AI involved.</div>
      <div id="jMatch"></div><div id="jCheck"></div></div>

    <div class="group" id="jDocs"><h4>Documents</h4>${profileBadge(j.id)}${aiBar('docs', j.id)}<div class="row">
      <button class="b" onclick="jobRun('gap',{},this)">Gap check (coverage + AI verdict)</button>
      <button class="b" onclick="jobRun('tailor',{docx:true,base:baseOpt()},this)">Tailor resume (+docx)</button>
      <button class="b" onclick="tailorBullets(this)">Tailor by bullet</button>
      <button class="b ghost" onclick="studioFor(${j.id})" title="the resume studio: a request + formatting, PDF and DOCX, checked against your facts">Build in Studio</button>
      <button class="b" onclick="jobRun('cover',{docx:true,tone:$('#jTone').value,words:$('#jWords').value},this)">Cover letter (+docx)</button>
      <button class="b ghost" onclick="draftOptions('cover',{id:${j.id},tone:$('#jTone').value,words:$('#jWords').value},'jOpts',this)" title="up to 3 letters from one AI call; Use this opens one in the editor">Cover options</button>
      <input id="jTone" placeholder="tone: confident, warm, specific" style="width:190px"><input id="jWords" type="number" min="100" max="800" placeholder="words (300)" style="width:100px">
      <button class="b ghost" onclick="jobRun('prep',{},this)">Interview prep</button>${'interview_prep.md' in d.docs ? `<button class="b ghost sm" onclick="viewJobDoc('interview_prep.md')" aria-label="View the interview prep">View</button>` : ''}
      <button class="b ghost" onclick="jobRun('research',{},this)">Company research</button>${'research.md' in d.docs ? `<button class="b ghost sm" onclick="viewJobDoc('research.md')" aria-label="View the research pack">View</button>` : ''}
      <button class="b ghost" onclick="run('checklist',{id:${j.id}},r=>show('jOut',r.checklist.map(c=>(c.done?'[x] ':c.na?'[-] ':'[ ] ')+c.item+(c.na?' (n/a yet)':c.done?'':'   -> '+c.next)).join('\\n')),this)">Checklist</button>
      <label class="muted"><input type="checkbox" id="jCouncil"> council (all providers)</label></div>
      <div class="row">${S.bases.length ? `<label class="muted">tailor from <select id="jBase"><option value="">master profile</option>${S.bases.map(b => `<option value="${esc(b.id)}">saved: ${esc(b.name)} (${esc(b.added.slice(0, 10))})</option>`).join('')}</select></label>` : ''}
        <label class="muted">style <select id="jStyle" onchange="setPref('resume_style',this.value)">${opt(S.pref_choices.resume_style, S.prefs.resume_style)}</select></label>
        <button class="b ghost" onclick="exportPdf(this)">Export PDF</button></div>
      <div id="jBullets"></div></div>

    <div class="group" id="jComm"><h4>Communicate</h4>
      <div class="row"><input id="jIntent" class="grow" placeholder="reply intent, e.g. accept interview, propose Tue/Wed afternoons"><button class="b ghost" onclick="jobRun('reply',{intent:$('#jIntent').value},this)">Draft reply</button></div>
      <div class="row"><input id="jPerson" class="grow" placeholder="outreach to: Name, title (optional)"><select id="jChannel"><option value="linkedin">LinkedIn note</option><option value="email">Email</option></select><button class="b ghost" onclick="jobRun('outreach',{person:$('#jPerson').value,channel:$('#jChannel').value},this)">Draft outreach</button></div>
      <div class="row"><button class="b ghost" onclick="jobRun('followup',{template:$('#jTpl').checked},this)">Follow-up email</button><input id="jInt" placeholder="interviewer" style="width:140px"><input id="jTnotes" class="grow" placeholder="something specific from the interview"><button class="b ghost" onclick="jobRun('thanks',{interviewer:$('#jInt').value,notes:$('#jTnotes').value,template:$('#jTpl').checked},this)">Thank-you note</button></div>
      <div class="row"><button class="b ghost" onclick="jobRun('withdraw',{template:$('#jTpl').checked},this)">Withdrawal email</button><label class="muted"><input type="checkbox" id="jTpl" ${Object.values(S.providers).some(Boolean) ? '' : 'checked disabled'}> plain template, no AI (follow-up, thank-you, withdrawal; used automatically without a provider)</label></div>
      <div class="row"><label class="muted">options for <select id="jOk"><option value="followup">follow-up</option><option value="thanks">thank-you (interviewer, notes above)</option><option value="withdraw">withdrawal</option><option value="outreach">outreach email (person above)</option><option value="checkin">offer check-in</option></select></label>
        <button class="b ghost" onclick="commOptions(this)" title="up to 3 drafts from one AI call, one recommended; the one you use waits in the Inbox for review">Options</button></div>
      <div id="jOpts"></div></div>

${activityGroup(d)}
${mailGroup(d)}

    <div class="group"><h4>Schedule and decide</h4>
      <div class="row"><input id="jWhen" placeholder="interview: YYYY-MM-DD HH:MM" style="width:200px"><input id="jMin" type="number" min="5" placeholder="minutes (60)" style="width:110px"><button class="b ghost" onclick="jobRun('ics',{when:$('#jWhen').value,minutes:$('#jMin').value||60},this)">Calendar .ics</button></div>
      <div class="row"><input id="oSal" placeholder="base" style="width:90px"><input id="oBon" placeholder="bonus" style="width:90px"><input id="oEq" placeholder="equity" style="width:90px"><input id="oBen" placeholder="benefits" style="width:120px"><input id="oDl" placeholder="deadline" style="width:100px"><input id="oNotes" class="grow" placeholder="notes"><button class="b ghost" onclick="jobRun('offer',{salary:$('#oSal').value,bonus:$('#oBon').value,equity:$('#oEq').value,benefits:$('#oBen').value,deadline:$('#oDl').value,notes:$('#oNotes').value},this)">Evaluate offer</button></div></div>

    <div class="group"><h4>Admin</h4>
      <div class="row"><input id="jNote" class="grow" placeholder="add a note"><button class="b ghost sm" onclick="jobAdmin('note',{text:$('#jNote').value})">note</button></div>
      <div class="row"><input id="jCn" placeholder="contact name" style="width:160px" value="${esc(j.contact_name || '')}"><input id="jCe" class="grow" placeholder="contact email (replies, follow-ups and thank-yous go here)" value="${esc(j.contact_email || '')}"><button class="b ghost sm" onclick="api('/api/jobs/${j.id}/contact',{name:$('#jCn').value,email:$('#jCe').value}).then(r=>{if(r.error)return toast('error: '+r.error,'err');toast('contact saved (also filed under Contacts as recruiter)','ok');openJob(${j.id})})">set contact</button></div>
      <div class="row"><input id="jJd" class="grow" placeholder="set job description: URL or pasted text"><button class="b ghost sm" onclick="jobAdmin('jd',{source:$('#jJd').value})">set JD</button></div>
      <div class="row"><button class="b ghost sm" onclick="jobRun('packet',{},this)">export packet (zip)</button><button class="b ghost sm" onclick="viewPacket()">View documents</button><button class="b danger sm" onclick="if(confirm('Delete job #${j.id}?'))api('/api/jobs/${j.id}/delete',{}).then(()=>{closeDrawer();load()})">delete job</button></div></div>

    <div class="tabs" id="docTabs">${['timeline', 'description', ...docs].map((n, i) => `<button class="${i === 0 ? 'on' : ''}" onclick="showDoc('${n}',this)">${n}</button>`).join('')}</div>
    <pre id="docView"></pre>
    <div class="row"><button class="b ghost sm" onclick="viewDoc()" title="paged preview, PDF / DOCX / TXT / MD, formatting, compare">View / format</button><button class="b ghost sm" onclick="editDoc()">Edit document</button><input id="dAdj" class="grow" placeholder="adjust this document with AI: shorter / warmer / lead with X"><button class="b ghost sm" onclick="adjustDoc(this)">Adjust</button><button class="b ghost sm" onclick="reviewDoc(this)">Review</button></div>
    <textarea id="docEdit" style="display:none; min-height:260px"></textarea><button class="b sm" id="docSave" style="display:none" onclick="saveDoc()">Save document</button>
    <div class="out"><h4 class="muted">AI output</h4><pre id="jOut">(run an action above)</pre></div>`;
  openDrawer('Job details');
  renderCoverage(savedCoverage(d));
  renderBullets(savedBullets(d), false);
  stageLine();
  if (d.pay && d.pay.next && !PAY_TRIED.has(j.id)) { PAY_TRIED.add(j.id); payRun(j.id, false); }  // one automatic BLS try per job per page load
  showDoc('timeline', $('#docTabs button'));
  if ($('#jQsrc')) await loadQsrc(j.id);
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
  return `<div class="group"><h4>Details</h4>${aiBar('job', j.id)}
    <div class="row">${inp('location', 'location', 'style="width:150px"')}${sel('remote', 'workplace', [['onsite', 'onsite'], ['hybrid', 'hybrid'], ['remote', 'remote']])}
      ${inp('salary_min', 'salary min', 'type="number" min="0" step="1000" style="width:105px"')}${inp('salary_max', 'salary max', 'type="number" min="0" step="1000" style="width:105px"')}
      ${inp('currency', 'currency', 'maxlength="3" style="width:62px"')}${sel('excitement', 'excitement', [1, 2, 3, 4, 5].map(n => [n, '★'.repeat(n)]))}
      ${inp('match_score', 'coverage %', 'type="number" min="0" max="100" style="width:72px"')}</div>
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
    toast(r.method === 'html' ? 'opened a print page: Save as PDF from there' : 'PDF written: ' + r.note, 'ok');  // the note names the engine (Edge, Chrome, Word, LibreOffice)
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
  return `<div class="group" id="jPeople"><h4>People</h4>
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
    <div class="group"><h4>Details</h4>${aiBar('contacts', c.id)}${aiMenu('contact', c.id)}
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
  const st = STRESS;
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
    <div class="muted">A round with a time reminds you like a calendar file (upcoming interviews, Today). Prep packs and mock interviews ask the questions logged here first (all practice questions: Interview readiness > Questions).</div></div>`;
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

/* ---- interview readiness and sourced practice questions (lodestar/readiness.py, interview.question_set) ---- */
// Readiness is preparation only; the chance is a band, always "not a probability". Every string from the server is
// escaped; buttons carry indexes into RD / QSRC, never text.
let RD = null, QSRC = null, QSET = null;  // the open job's readiness, its company's sources, its practice set
const cap = s => s ? s[0].toUpperCase() + s.slice(1) : '';
const SRC_NAME = { logged: 'you logged it', pasted: 'your pasted notes', company: "the company's own page", jd: 'the job description', reported: 'reported, unverified', general: 'general question' };
const PART_NAME = { answers: 'Mock answers', coverage: 'Competencies covered', stories: 'STAR stories', practised: "Company's questions practised", prep: 'Prep pack and research' };
function srcChip(e) {  // where a question came from: always a text label (never colour alone); its full label in the tooltip
  if (!e) return '';
  const u = e.source === 'company' ? safeUrl(e.url) : '';
  return `<span class="src src-${esc(e.source)}" title="${esc(e.label || SRC_NAME[e.source] || '')}">${esc(e.chip || SRC_NAME[e.source] || e.source)}${e.source === 'reported' ? ' ⓘ' : ''}</span>`
    + (u ? ` <a href="${esc(u)}" target="_blank" rel="noopener noreferrer" title="${esc(u)}" aria-label="open the company page">↗</a>` : '');
}
function mentions(hits, c, co) {  // counts with their source, never a percentage (interview.mentions)
  const h = (hits || {})[c] || {}, k = Object.keys(h); if (!k.length) return '';
  if (k.length === 1 && k[0] === 'jd') return `the job description mentions it ${Number(h.jd)} time${h.jd === 1 ? '' : 's'}`;
  const n = Object.values(h).reduce((a, b) => a + Number(b), 0);
  return `${n} mention${n === 1 ? '' : 's'} in ${co}'s material`;
}
const RAISE_BTN = { practise: 'Practise', stories: 'Open stories', prep: 'Run prep', sources: 'Refresh sources' };
function readinessGroup(d) {
  const j = d.job, r = d.readiness; RD = r; QSRC = QSET = null;
  const show = ['screening', 'interview', 'offer'].includes(j.status) || (d.rounds || []).length || (S.mock_sessions || []).some(s => s.job_id === j.id);
  if (!show) return '';
  if (!r) return `<div class="group" id="jReady"><h4>Interview readiness</h4><div class="muted">Readiness could not be worked out for this job right now (the log has the reason).</div></div>`;
  const ch = r.chance;
  const parts = Object.entries(r.parts).map(([k, p]) => `<div class="ready-row"><span>${esc(PART_NAME[k] || k)} <span class="muted">${Number(p.w)} pts</span></span>
      <meter min="0" max="100" low="40" high="60" optimum="100" value="${Number(p.s)}" aria-label="${esc(PART_NAME[k] || k)}: ${Number(p.s)} of 100"></meter><b>${Number(p.s)}</b>
      <span class="muted chips">${p.chips.map(c => `<span>${esc(c)}</span>`).join('')}</span></div>`).join('');
  const raise = r.raise.map((x, i) => `<div class="row raise"><span class="pill ok">+${Number(x.gain)}</span><span>${esc(x.text)}</span>${RAISE_BTN[x.action.do]
    ? `<button class="b ghost sm" onclick="raiseAct(RD.raise[${i}].action,this)">${RAISE_BTN[x.action.do]}</button>` : ''}</div>`).join('')
    || '<div class="muted">Nothing quick left: keep practising.</div>';
  return `<div class="group" id="jReady"><h4>Interview readiness</h4>
    <div class="row"><b class="ready-score" aria-label="Readiness (preparation): ${Number(r.score)} of 100">${Number(r.score)}/100</b><span class="muted">Readiness (preparation)</span>
      <span id="jBand">Chance estimate: <b>${esc(cap(ch.band))}</b>, not a probability${ch.capped_by_fit ? ` <span class="muted">(capped by fit ${Number(ch.fit)})</span>` : ''}</span></div>
    <div class="muted" id="jChance">${esc(ch.label)}</div>${ch.funnel ? `<div class="muted">${esc(ch.funnel)}</div>` : ''}
    <div class="ready">${parts}</div>
    <div class="muted">${esc(r.stage)} · ${ch.fit != null ? `fit ${Number(ch.fit)} · caps the chance band` : 'fit not scored yet'}</div>
    <h4>Raise it</h4>${raise}
    <div class="row"><button class="b ghost sm" onclick="explainReady(this)" title="one AI call over the five preparation parts (never your fit score); advice only, the score does not change">Explain my readiness</button>
      <button class="b ghost sm" onclick="nextPractice()" title="the top 'raise it' row; no AI">What should I practise next?</button></div>
    <pre id="jReadyOut" style="display:none"></pre>
    <h4>Question sources <span class="muted">for ${esc(j.company)}, shared by its jobs</span></h4><div id="jQsrc" class="qsrc"><div class="muted">loading…</div></div>
    <div id="jQlist"></div></div>`;
}
async function loadQsrc(id) {
  const [s, q] = await Promise.all([api(`/api/jobs/${id}/qsources`), api(`/api/jobs/${id}/questions`)]);
  if (!cur || cur.job.id !== id || !$('#jQsrc')) return;
  if (s.error || q.error) { $('#jQsrc').innerHTML = `<div class="muted">${esc(s.error || q.error)}</div>`; return; }
  QSRC = s; QSET = q; renderQsrc();
}
function renderQsrc() {
  const s = QSRC, q = QSET, b = q.by_source, co = s.company, n = (x, w) => `${Number(x)} ${w}${Number(x) === 1 ? '' : 's'}`;
  const counts = [`You logged ${Number(b.logged)}`, `You pasted ${n(s.counts.pastes, 'note')} (${n(b.pasted, 'question')})`,
    `${esc(co)} pages ${Number(s.counts.pages)} (${n(b.company, 'question')})`, `JD ${Number(b.jd)}`, b.reported ? `Reported ${Number(b.reported)}` : '', `General ${Number(b.general)}`].filter(Boolean).join(' · ');
  const st = p => p.status === 'ok' ? 'read' : p.status === 'robots' ? 'skipped: robots.txt disallows' : p.status;
  const pages = s.pages.map(p => `<div class="row">${safeUrl(p.url) ? `<a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer">${esc(p.label || p.url)} ↗</a>` : esc(p.label || p.url)}
      <span class="muted">${esc(st(p))}${p.fetched_at ? ' · ' + esc(String(p.fetched_at).slice(0, 16)) : ''}</span></div>`).join('')
    || `<div class="muted">${s.site ? (s.last_check ? `No hiring or values pages found on the site (checked ${esc(String(s.last_check).slice(0, 16))}).` : 'Pages not read yet: Refresh reads them.') : 'Add the company website to read its hiring pages.'}</div>`;
  const pastes = s.pastes.map((p, i) => `<div class="qpaste"><div class="row"><b>${esc(p.label)}</b><span class="muted">${esc(localTs(p.created_at, 10))}</span>
      ${safeUrl(p.url) ? `<a href="${esc(p.url)}" target="_blank" rel="noopener noreferrer" title="a citation: Lodestar stores it and never opens it">source ↗</a>` : ''}
      <button class="b danger sm" onclick="delQsrc(${i})" aria-label="${esc('Delete pasted notes: ' + p.label)}">Delete</button></div>
    <div class="muted">${esc(p.preview)}${String(p.preview || '').length >= 200 ? '…' : ''}</div></div>`).join('');
  const dropped = q.dropped || [];
  $('#jQsrc').innerHTML = `<div class="muted" id="jQcounts">${counts}</div><div class="muted">${esc(q.emphasis_text)}</div>
    <div class="row"><label class="fld">Company website<input id="qsSite" value="${esc(s.site ? s.site.url : '')}" placeholder="https://www.example.com" style="width:240px"></label>
      <span class="muted">${s.site ? (s.site.label === 'you' ? 'typed by you' : 'from the job URL') : 'not set: no company pages are read'}</span><button class="b ghost sm" onclick="saveSite(this)">Save website</button></div>
    ${pages}${pastes}
    <details id="qsPaste"><summary class="muted">Paste what you read</summary><div class="muted">${esc(s.notice)}</div>
      <div class="row"><label class="fld">Where from<input id="qsLabel" maxlength="120" placeholder="Glassdoor interview reviews, read 2026-11-05" style="width:260px"></label>
        <label class="fld">Link (optional, stored, never opened)<input id="qsUrl" placeholder="https://..." style="width:200px"></label></div>
      <label class="fld">Text<textarea id="qsText" maxlength="20000" style="min-height:90px" placeholder="the interview reports or notes you read"></textarea></label>
      <div class="row"><button class="b sm" onclick="addPaste(this)">Save pasted notes</button></div></details>
    <div class="row"><button class="b ghost sm" onclick="qsetRun(true,this)" title="re-read the company's public hiring and values pages (robots.txt, at most 12 requests) and build the set with one AI call">Refresh</button>
      <span class="muted" id="jQbuilt">${q.ai_at ? 'last AI build ' + esc(String(q.ai_at).slice(0, 16)) : 'not built with AI yet'}${q.stale ? ' · sources changed since the last AI build' : ''}</span></div>
    ${q.ai_error ? `<div class="warnbox">${esc(q.ai_error)}</div>` : ''}
    ${dropped.length ? `<details><summary class="muted" id="jQdropped">${n(dropped.length, 'AI question')} dropped (why)</summary><ul class="muted qs">${dropped.map(x => `<li>${esc(x.q)}: ${esc(x.why)}</li>`).join('')}</ul></details>` : ''}`;
  const groups = {};
  q.questions.forEach(e => (groups[e.competency] = groups[e.competency] || []).push(e));
  const order = Object.keys(groups).sort((a, c) => (q.emphasis[c] || 0) - (q.emphasis[a] || 0));
  $('#jQlist').innerHTML = `<details id="jQs"><summary class="muted">Questions (${q.questions.length})</summary>`
    + order.map(c => { const m = mentions(q.hits, c, co); return `<div class="qgroup"><b>${esc(c)}</b>${m ? ` <span class="muted">· ${esc(m)}</span>` : ''}
      <ul class="qs">${groups[c].map(e => `<li>${esc(e.q)} ${srcChip(e)}</li>`).join('')}</ul></div>`; }).join('') + '</details>';
}
async function qsrcOp(body, msg) {
  const id = cur.job.id, r = await api(`/api/jobs/${id}/qsources`, body);
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(msg(r), 'ok'); await openJob(id); return r;
}
function addPaste() {
  const label = $('#qsLabel').value.trim(), text = $('#qsText').value.trim(), url = $('#qsUrl').value.trim();
  if (!label || !text) return toast('fill in where it is from and the text', 'err');
  qsrcOp({ op: 'paste', label, text, url: url || undefined }, () => 'pasted notes saved; Refresh builds questions from them with AI');
}
function delQsrc(i) {
  const p = QSRC && QSRC.pastes[i]; if (!p || !confirm(`Delete the pasted notes "${p.label}"? Questions taken from them go too.`)) return;
  qsrcOp({ op: 'delete', sid: Number(p.id) }, () => 'pasted notes deleted');
}
function saveSite() { qsrcOp({ op: 'site', url: $('#qsSite').value.trim() }, r => r.site ? 'company website saved: ' + r.site : 'company website cleared'); }
function qsetRun(refresh, btn, jid) {
  const id = jid || cur.job.id;
  run('qset', { id, refresh }, r => {
    const d = (r.dropped || []).length;
    toast(r.ai_error ? r.ai_error : 'question set built' + (d ? `: ${d} AI question${d === 1 ? '' : 's'} dropped (see why under Question sources)` : ''), r.ai_error ? 'err' : 'ok');
    if (cur && cur.job.id === id) openJob(id);
  }, btn);
}
function practise(id, focus) {  // Coach > Mock interview for this job, optionally on one competency
  go('coach'); $('#cMode').value = 'mock'; resetChat(); $('#cJob').value = String(id); $('#cFocus').value = focus || ''; $('#cIn').focus();
}
async function raiseAct(a, btn, jid) {  // a 'raise it' action from the drawer or Today
  jid = jid || cur.job.id;
  if (a.do === 'practise') return practise(jid, a.focus);
  if (a.do === 'stories') return newStory(a.tag);
  if (!cur || cur.job.id !== jid) { go('board'); await openJob(jid); }
  if (a.do === 'sources') return qsetRun(false, btn, jid);
  const e = PIPE.find(x => x.name === 'prep');
  if (a.do === 'prep') return e && ['ready', 'done', 'stale', 'error'].includes(e.state) ? pipeRun({ stage: 'prep', rerun: ['done', 'stale'].includes(e.state) }, btn) : jobRun('prep', {}, btn);
  $('#jReady')?.scrollIntoView();
}
function openReady(id) { go('board'); openJob(id).then(() => $('#jReady')?.scrollIntoView()); }
function explainReady(btn) { const id = cur.job.id; run('readiness_explain', { id }, r => { if (cur && cur.job.id === id) show('jReadyOut', r.text); }, btn); }
function nextPractice() {
  const x = RD && RD.raise[0];
  show('jReadyOut', x ? `${x.text} (+${x.gain} points).` : 'Nothing quick left to raise it: keep practising with the mock interview.');
}
function renderReadyRecord(c) {  // Insights: your record as plain counts per band; never a probability
  $('#insReady').innerHTML = `<div class="row"><span class="pill">${esc(c.state)}</span>${c.shown ? `<span class="muted">${Number(c.n)} rounds with a result, ${Number(c.passes)} passed</span>` : ''}</div>
    <table class="kw"><thead><tr><th>readiness at the round</th><th>passed</th><th>rounds</th></tr></thead><tbody>`
    + Object.entries(c.table).map(([b, r]) => `<tr><td>${esc(b)} (${Number(r.lo)}-${Number(r.hi)})</td><td>${Number(r.passed)}</td><td>${Number(r.total)}</td></tr>`).join('')
    + `</tbody></table><div class="muted">${esc(c.caveat)}</div>${c.note ? `<div class="muted">${esc(c.note)}</div>` : ''}`;
}

/* ---- STAR stories: rows of the answer bank with structured fields (lodestar/interview.py) ---- */
const ST_FIELDS = ['title', 'situation', 'task', 'action', 'result', 'metrics'];
const stIn = k => $('#st' + k[0].toUpperCase() + k.slice(1));
function renderStories() {
  if (!$('#stComps').children.length) $('#stComps').innerHTML = S.competencies.map(c => `<label class="muted"><input type="checkbox" value="${esc(c)}"> ${esc(c)}</label>`).join('');
  const have = new Set(S.stories.flatMap(s => s.competencies)), none = S.competencies.filter(c => !have.has(c));
  $('#storyList').innerHTML = (S.stories.length && none.length ? `<div class="muted">no story tagged yet: ${esc(none.join(', '))}</div>` : '') + `<div class="list">`
    + (S.stories.map((s, i) => `<div><b>${esc(s.title)}</b> ${s.competencies.map(c => `<span class="pill">${esc(c)}</span>`).join('')}${s.missing.length ? `<span class="chip stale">incomplete: no ${esc(s.missing.join(', '))}</span>` : ''}
      <button class="b ghost sm" onclick="editStory(${i})">edit</button><button class="b ghost sm" onclick="deleteStory(${i})">remove</button>${aiBar('stories', s.id)}${aiMenu('stories', s.id)}
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
      ${r.kind === 'run_to' && (p.reuse || []).length ? `<div class="reuse"><b>Saved answers this fills in on the form</b> <span class="muted">(yours; reject and change them under Answers if one is wrong)</span><ul>${p.reuse.map(x => `<li>${esc(x.label)} → <b>${esc(x.answer)}</b> <span class="muted">${esc(x.source)}</span></li>`).join('')}</ul></div>` : ''}
      ${mail && r.job_id ? `<div class="row" id="att${r.id}">${attHtml(r)}</div>` : ''}
      ${mail && hasAI() ? `<div class="row"><button class="b ghost sm" onclick="draftOptions('pending',{pending_id:${r.id}},'p${r.id}',this)" title="up to 3 alternatives (one AI call); Use this changes only the subject and body">Options</button>${HOWS.map(([k, l]) => `<button class="b ghost sm" onclick="rewritePending(${r.id},'${k}',this)">${l}</button>`).join('')}<button class="b ghost sm" onclick="rewritePending(${r.id},'',this)">custom…</button></div>${optsHtml('p' + r.id)}` : ''}
      ${mail ? aiBar('inbox', r.id) : ''}
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

/* ---- site accounts (lodestar/accounts.py): one per site; the password only in the OS keyring, shown on Reveal. Site
   names, usernames, hints and errors come from pages and mail: every one goes through esc; markup carries only ids ---- */
let ACCT = { accounts: [], waiting: [], links: [], session: {}, statuses: {} }, ACCT_T = null, ACCT_CODES = [];
const ACCT_LIVE = ['opening', 'running', 'needs_you'];
async function acctLoad() {
  const r = await api('/api/accounts'); if (r.error) return toast('error: ' + r.error, 'err');
  ACCT = r;
  if ((r.waiting || []).some(w => (w.needs || []).some(n => n.reason === 'account_code'))) { const c = await api('/api/codes'); ACCT_CODES = c.codes || []; }
  acctPaint();
  clearTimeout(ACCT_T);
  if ((r.waiting || []).length || ACCT_LIVE.includes((r.session || {}).state)) ACCT_T = setTimeout(() => { if ($('#setup').classList.contains('on')) acctLoad(); }, 1500);
}
function acctWaitRow(w) {
  const n = (w.needs || [])[0] || {}, t = esc(w.target), again = `<button class="b ghost sm" onclick="acctCodes(this)">Check mail now</button>`;
  const codes = n.reason === 'account_code' ? ACCT_CODES.map(c => `<button class="b sm" onclick="acctAct('${t}','code',this,'${esc(c.id)}')">Fill code from ${esc(c.domain)}</button>`).join('') + again : '';
  const links = n.reason === 'account_link' ? (ACCT.links || []).filter(l => l.host === w.site).map(l => `<button class="b sm" onclick="acctAct('${t}','link',this,'${esc(l.id)}')">Open the link from ${esc(l.domain)}</button>`).join('') + again : '';
  return `<div class="item acctwait" data-target="${t}"><div class="row"><b>${esc(w.site)}</b>${w.job_id ? ` <span class="muted">job #${Number(w.job_id)}</span>` : ''}<span class="grow">${esc(n.hint)}</span></div>
    <div class="row">${w.mine ? codes + links : '<span class="muted">worked by another Lodestar process: do it in the window</span>'}
      ${n.reason === 'account_create' ? `<button class="b ghost sm" onclick="acctAct('${t}','own',this)">I have an account</button>` : ''}
      <button class="b sm" onclick="acctAct('${t}','continue',this)">${w.target === 'session' && n.reason === 'login' ? 'Done' : 'Continue'}</button></div></div>`;
}
function acctRow(a) {
  const id = Number(a.id), bad = ['failed', 'locked'].includes(a.status), warn = ['pending', 'needs_verification'].includes(a.status);
  const jobs = (a.jobs || []).map(j => `<button class="b ghost sm" onclick="go('board');openJob(${Number(j.id)})">#${Number(j.id)} ${esc(j.company)} - ${esc(j.title)}</button>`).join('');
  return `<div class="item acct" data-acct="${id}"><div class="row"><b>${esc(a.site)}</b><span class="pill ${bad || warn ? 'warn' : 'ok'}">${esc(a.label)}</span>
      <span>${esc(a.username)}</span><button class="b ghost sm" onclick="acctCopyUser(${id})">Copy username</button>
      <span class="muted">created ${esc(localTs(a.created_at, 10))} · last sign-in ${a.last_login ? esc(localTs(a.last_login, 16)) : 'never'}${a.created_by === 'agent' ? ' · made by the agent' : ''}</span></div>
    ${a.last_error ? `<div class="flagtxt">⚠ ${esc(a.last_error)}</div>` : ''}${jobs ? `<div class="row"><span class="muted">jobs</span>${jobs}</div>` : ''}
    <div class="row"><button class="b ghost sm" onclick="acctOp(${id},'open',this)">Open site</button><button class="b sm" onclick="acctOp(${id},'relogin',this)">Re-login</button>
      <button class="b ghost sm" onclick="acctReveal(${id},this)">Reveal</button><code id="acctShow${id}" aria-live="polite"></code>
      ${bad && a.reset_url ? `<button class="b ghost sm" onclick="acctOp(${id},'reset',this)">Reset password on the site</button>` : ''}
      <label class="muted"><input type="checkbox" ${a.auto_verify ? 'checked' : ''} onchange="acctAuto(${id},this)"> use my inbox's codes and links here without a click</label>
      <button class="b danger sm" onclick="acctRemove(${id},this)">Remove</button></div>
    <details><summary class="muted">Change password</summary><div class="row"><input id="acctNp${id}" type="password" autocomplete="new-password" placeholder="the new password" aria-label="new password for ${esc(a.site)}">
      <button class="b sm" onclick="acctPassword(${id},false,this)">Save</button><button class="b ghost sm" onclick="acctPassword(${id},true,this)">Generate a new one</button>
      <span class="muted">after you changed it on the site; a failed or locked account is tried again</span></div></details></div>`;
}
function acctPaint() {
  const q = ($('#acctQ').value || '').trim().toLowerCase();
  const list = (ACCT.accounts || []).filter(a => !q || JSON.stringify(a).toLowerCase().includes(q));
  const g = ACCT.general || {};
  $('#acctGenState').textContent = g.set ? `(set${g.username ? ', ' + g.username : ''}${g.auto_create ? ', finishes sign-ups' : ''})` : '(not set)';
  $('#acctAutoCreate').checked = !!g.auto_create;
  const s = ACCT.session || {};
  const live = !s.state ? '' : ACCT_LIVE.includes(s.state)
    ? `<div class="item"><b>Account window</b> (${esc(s.action)} on ${esc(s.site)}): ${esc(s.state)} · ${esc(s.step)} <button class="b danger sm" onclick="acctAct('session','stop',this)">Close window</button></div>`
    : `<div class="muted">Last account window, ${esc(s.site)}: ${esc(s.step)}</div>`;
  $('#acctWait').innerHTML = live + (ACCT.waiting || []).map(acctWaitRow).join('');
  $('#acctList').innerHTML = list.map(acctRow).join('')
    || `<div class="muted">${(ACCT.accounts || []).length ? 'no account matches' : 'no site accounts yet: the agent adds one when it creates it, or save a login below'}</div>`;
}
const acctFind = id => (ACCT.accounts || []).find(a => Number(a.id) === Number(id));
async function acctCall(path, body, btn) {
  if (btn) btn.disabled = true;
  try { const r = await api(path, body || {}); if (r.error) { toast('error: ' + r.error, 'err'); return null; } return r; }
  finally { if (btn) btn.disabled = false; }
}
async function acctAdd(btn) {
  const r = await acctCall('/api/accounts/add', { url: $('#acctUrl').value, username: $('#acctUser').value, password: $('#acctPw').value }, btn);
  if (!r) return; $('#acctPw').value = ''; $('#acctUser').value = ''; $('#acctUrl').value = ''; toast(`saved ${r.site}`, 'ok'); acctLoad();
}
async function acctCreate(btn) {
  const url = $('#acctUrl').value.trim(); if (!url) return toast("paste the site's sign-in page link first", 'err');
  if (!confirm(`Open ${url} in the agent's window and fill its sign-up form with your email and a new password? You tick the terms and press Create yourself.`)) return;
  if (await acctCall('/api/accounts/create', { url }, btn)) { toast("the agent's window is opening", 'ok'); acctLoad(); }
}
async function acctOp(id, op, btn) {
  const a = acctFind(id); if (!a) return;
  if (op === 'relogin' && !confirm(`Sign in to ${a.site} as ${a.username} in the agent's window?`)) return;
  if (!await acctCall(`/api/accounts/${id}/${op}`, {}, btn)) return;
  toast(op === 'relogin' ? "the agent's window is opening" : "a sign-in window opened on the agent's profile", 'ok'); acctLoad();
}
async function acctAct(target, action, btn, id) {
  if (!await acctCall('/api/accounts/act', { target, action, id: id || '' }, btn)) return;
  toast(action === 'code' ? "filling the code in the agent's window" : action === 'link' ? "opening the link in the agent's window" : 'ok', 'ok');
  setTimeout(acctLoad, 300);
}
async function acctCodes(btn) { const r = await acctCall('/api/codes/check', {}, btn); if (r) { ACCT_CODES = r.codes || []; acctLoad(); } }
async function acctCopyUser(id) {
  const a = acctFind(id); if (!a) return;
  try { await navigator.clipboard.writeText(a.username); toast('username copied', 'ok'); } catch (_) { toast(a.username, 'ok'); }
}
async function acctReveal(id, btn) {
  const out = $('#acctShow' + id);
  if (out.textContent) { out.textContent = ''; btn.textContent = 'Reveal'; return; }
  const r = await acctCall(`/api/accounts/${id}/reveal`, {}, btn); if (!r) return;
  out.textContent = r.password; btn.textContent = 'Hide';
  setTimeout(() => { if (out.isConnected) { out.textContent = ''; btn.textContent = 'Reveal'; } }, 30000);
}
async function acctPassword(id, generate, btn) {
  const inp = $('#acctNp' + id);
  if (!generate && !inp.value) return toast('type the new password, or Generate one', 'err');
  const r = await acctCall(`/api/accounts/${id}/password`, generate ? { generate: true } : { password: inp.value }, btn); if (!r) return;
  inp.value = ''; await acctLoad();
  if (r.password) { $('#acctShow' + id).textContent = r.password; toast("a new password: type it into the site's change-password form", 'ok'); }
  else toast('password changed', 'ok');
}
async function acctGeneral(btn, clear) {
  if (clear && !confirm('Clear the general login? New accounts get a generated password again; saved accounts keep theirs.')) return;
  const r = await acctCall('/api/accounts/general', clear ? { clear: true } : { username: $('#acctGenUser').value, password: $('#acctGenPw').value }, btn);
  if (!r) return; $('#acctGenPw').value = ''; toast(clear ? 'general login cleared' : 'general login saved', 'ok'); acctLoad();
}
async function acctAutoCreate(box) {
  if (box.checked && !confirm('Let the agent tick a sign-up\'s terms / privacy box and press Create for you? You agree to each site\'s terms when it does.')) { box.checked = false; return; }
  const r = await api('/api/prefs', { key: 'accounts_auto_create', value: box.checked });
  if (r.error) { box.checked = !box.checked; return toast('error: ' + r.error, 'err'); }
  acctLoad();
}
async function acctAuto(id, box) { if (!await acctCall(`/api/accounts/${id}/auto`, { on: box.checked })) box.checked = !box.checked; }
async function acctRemove(id, btn) {
  const a = acctFind(id); if (!a || !confirm(`Remove the account for ${a.site} (${a.username})? Its password leaves the OS keyring; the account on the site stays.`)) return;
  if (await acctCall(`/api/accounts/${id}/remove`, {}, btn)) { toast(`removed ${a.site}`, 'ok'); acctLoad(); }
}

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
/* ---- Listing activity: posting checks (web), alert sightings (bell), mail both ways (envelope), the job's own events
   (dot), newest first (listings.activity). Every string is page or mail text: escaped. ---- */
const ACT_ICON = { web: '🌐', alert: '🔔', mail: '✉', app: '•' };
/* ---- chance boosters (boosters.py) and job intelligence (intel.py): server data stays in JS, buttons carry an index ---- */
const BOOST_BTN = { pipeline: 'Open the pipeline', referral: 'Open People', outreach: 'Open outreach', followup: 'Open follow-up', tailor: 'Open tailoring',
  gap: 'Open gap tools', lint: 'Open resume lint', stories: 'Write a story', search: 'Open search', intel: 'Open job intelligence', contacts: 'Open Contacts', profile: 'Open profile' };
const BOOSTS = { d: [], t: [], i: [] };  // drawer, Today, Insights
function boostRow(b, src, i) {
  const j = b.job ? ` <span class="muted">· #${Number(b.job.id)} ${esc(b.job.company)} - ${esc(b.job.title)}</span>` : '';
  const btn = BOOST_BTN[(b.action || {}).do] ? `<button class="b ghost sm" onclick="boostAct('${src}',${Number(i)},this)">${BOOST_BTN[b.action.do]}</button>` : '';
  return `<div class="row boost" data-basis="${esc(b.basis)}"><span class="pill ${b.effect === 'high' ? 'ok' : ''}" title="expected effect, not a probability">${esc(b.effect)} effect</span>
    <span class="grow"><b>${esc(b.text)}</b>${j}${b.basis === 'ai' ? ' <span class="pill">AI</span>' : ''}<br><span class="muted">${esc(b.why)}${b.from ? ' · basis: ' + esc(b.from) : ''}</span></span>${btn}</div>`;
}
async function boostAct(src, i, btn) {  // into the feature that does it; nothing here costs AI or sends anything
  const b = BOOSTS[src][i]; if (!b) return;
  const a = b.action || {}, jid = b.job ? b.job.id : cur && cur.job.id;
  if (a.do === 'stories') return newStory(a.tag);
  if (a.do === 'search') { go('search'); $('#sQ').value = a.query || ''; if (a.location) $('#sLoc').value = a.location; return $('#sQ').focus(); }
  if (a.do === 'contacts' || a.do === 'profile') return go(a.do);
  if (!jid) return;
  if (!cur || cur.job.id !== jid || CT) { go('board'); await openJob(jid); }
  if (a.do === 'outreach' && a.person) { $('#jPerson').value = a.person; if (a.channel) $('#jChannel').value = a.channel; }
  const to = $({ pipeline: '#pGroup', referral: '#jPeople', outreach: '#jComm', followup: '#jComm', tailor: '#jDocs', gap: '#jMatchG', lint: '#jMatchG', intel: '#jIntel' }[a.do] || '#jBoost');
  if (to) to.scrollIntoView({ block: 'start' });
  if (a.do === 'lint') jobLint($('#jMatchG button[onclick^="jobLint"]'));
}
function boostGroup(d) {
  const v = d.boosters;
  if (!v) return '<div class="group" id="jBoost"><h4>Chance boosters</h4><div class="muted">Could not be worked out for this job right now (the log has the reason).</div></div>';
  BOOSTS.d = v.items;
  const rows = v.items.map((b, i) => boostRow(b, 'd', i)).join('') || `<div class="muted">${v.closed ? 'This job is closed.' : 'Nothing to boost right now.'}</div>`;
  return `<div class="group" id="jBoost"><h4>Chance boosters</h4>${rows}
    <div class="row">${hasAI() ? `<button class="b ghost sm" onclick="boostAi(this)" title="one AI call: up to 3 more actions specific to this job, each with the posting line, source or profile fact it rests on">More from AI</button>` : ''}${v.ai_at ? `<span class="muted">AI additions from ${esc(localTs(v.ai_at, 10))}</span>` : ''}</div>
    <div class="muted">Ranked by expected effect (high, medium, low), rules first. Never a probability: each says why, and its button opens the feature that does it.</div></div>`;
}
function boostAi(btn) { const id = cur.job.id; run('boost_ai', { id }, r => { if (cur && cur.job.id === id) { cur.boosters = r; $('#jBoost').outerHTML = boostGroup(cur); } }, btn); }
const INTEL_KIND = { company: 'Company', news: 'Recent news', hiring: 'Hiring signals', role: 'The role', pay: 'Pay context' };
function intelGroup(d) {
  const v = d.intel;
  if (!v) return '<div class="group" id="jIntel"><h4>Job intelligence</h4><div class="muted">Could not be worked out for this job right now (the log has the reason).</div></div>';
  let k = '';
  const rows = v.items.map((x, i) => (x.kind !== k ? `<h5>${esc(INTEL_KIND[k = x.kind] || x.kind)}</h5>` : '')
    + `<div class="intel-row" data-kind="${esc(x.kind)}"><span class="pill">S${i + 1}</span> ${esc(x.text)} <span class="muted">· ${safeUrl(x.url) ? `<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.source)}</a>` : esc(x.source)}, ${esc(x.date || 'undated')}</span></div>`).join('');
  const s = v.summary;
  return `<div class="group" id="jIntel"><h4>Job intelligence</h4>
    <div class="row"><button class="b ghost sm" onclick="intelRun(${v.gathered_at ? 'true' : 'false'},this)" title="reads the company's own website and the news feed it links (robots.txt first), and its Wikipedia summary; never a job board">${v.gathered_at ? 'Gather again' : 'Gather public facts'}</button>
      ${hasAI() && v.items.length ? '<button class="b ghost sm" onclick="intelAi(this)" title="one AI call over the items below only; every line cites its sources">AI summary</button>' : ''}
      <span class="muted">${v.gathered_at ? 'web facts gathered ' + esc(localTs(v.gathered_at, 10)) + (v.stale ? ' (over a week old)' : '') : 'web facts not gathered yet'}</span></div>
    ${s ? `<div class="intel-sum"><b>AI summary</b> <span class="muted">${esc(localTs(s.at, 10))} · cites S1-S${Number(s.n)}${v.summary_stale ? ' · the sources changed since: run it again' : ''}</span><pre>${esc(s.text)}</pre></div>` : ''}
    ${rows}
    ${v.skipped.length ? `<details><summary class="muted">Not read (${v.skipped.length})</summary><ul>${v.skipped.map(x => `<li>${esc(x)}</li>`).join('')}</ul></details>` : ''}
    <div class="row"><input id="inSite" class="grow" placeholder="company website, e.g. https://acme.example" aria-label="Company website" value="${esc(v.site || '')}"><button class="b ghost sm" onclick="intelSite()">Set company site</button></div>
    <div class="muted">Each item names its source and date. Only the company's own site (where its robots.txt allows), the news feed it links and Wikipedia are read, on your click, cached a week; job boards are never read. Hiring signals, role and pay context come from what Lodestar already holds.</div></div>`;
}
function intelRun(refresh, btn) { const id = cur.job.id; run('intel', { id, refresh }, r => { if (cur && cur.job.id === id) { cur.intel = r; $('#jIntel').outerHTML = intelGroup(cur); } }, btn); }
function intelAi(btn) { const id = cur.job.id; run('intel_ai', { id }, () => { if (cur && cur.job.id === id) openJob(id).then(() => $('#jIntel')?.scrollIntoView()); }, btn); }
function intelSite() { qsrcOp({ op: 'site', url: $('#inSite').value.trim() }, r => r.site ? 'company website saved: ' + r.site + ' (Gather public facts reads it)' : 'company website cleared'); }
function ago(ts) {
  const m = /^(\d{4}-\d\d-\d\d)[ T](\d\d:\d\d)/.exec(ts || ''); if (!m) return '';
  const days = Math.floor((Date.now() - new Date(`${m[1]}T${m[2]}Z`)) / 864e5);
  return days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`;
}
function postingLine(d) {
  const p = d.posting || {}, bits = [], mails = (d.mail || []).length;
  if (p.closed) bits.push(`posting removed ${ago(p.closed)}`);
  else if (p.no_fetch) bits.push(p.seen_alert ? `last seen in an alert ${ago(p.seen_alert)}` : 'not seen in alerts since you tracked it');
  else if (p.checked) bits.push(`posting open${(p.sources || []).length ? ' on ' + p.sources.join(', ') : ''} (checked ${ago(p.checked)})`);
  else bits.push('posting not checked yet');
  if (!p.no_fetch && p.seen_alert) bits.push(`seen in an alert ${ago(p.seen_alert)}`);
  if (mails) bits.push(`${mails} email${mails === 1 ? '' : 's'}`);
  return bits.map(esc).join(' · ');
}
function activityGroup(d) {
  const live = 'posting_changes.md' in (d.docs || {});
  const rows = (d.activity || []).map(a => {
    const who = a.src === 'mail' ? ` <span class="pill ${a.trusted ? 'ok' : 'warn'}">${a.trusted ? 'verified sender' : 'unverified'}</span>${a.reason ? ` <span class="muted">${esc(a.reason)}</span>` : ''}` : '';
    const dir = a.src === 'mail' ? (a.dir === 'out' ? 'sent: ' : 'received: ') : '';
    return `<div class="actrow" data-src="${esc(a.src)}"><span aria-label="${esc(a.src)}" title="${esc(a.src)}">${ACT_ICON[a.src] || '•'}</span> <span class="muted">${esc(localTs(a.at, 16))}</span> ${esc(dir)}${a.kind && a.src !== 'web' ? `<b>${esc(String(a.kind).replace(/_/g, ' '))}</b> ` : ''}${esc(a.text)}${who}</div>`;
  }).join('');
  return `<div class="group" id="jActivity"><h4>Listing activity</h4>
    <div class="row"><span class="muted" id="jPosting">${postingLine(d)}</span>${live ? `<button class="b ghost sm" onclick="useLiveJd(this)" title="replace this job's description with the posting's current one (your tailored documents stay as they are)">Use live description</button><button class="b ghost sm" onclick="viewJobDoc('posting_changes.md')">View changes</button>` : ''}</div>
    <div class="list">${rows || '<div class="muted">nothing yet: posting checks, job-alert sightings and mail for this job show here</div>'}</div></div>`;
}
async function useLiveJd(btn) {
  if (!cur || !confirm("Replace this job's description with the live posting's? Documents you already tailored are not changed.")) return;
  btn.disabled = true;
  const r = await api(`/api/jobs/${cur.job.id}/live_jd`, {}); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(r.changed ? 'description replaced by the live posting' : 'the description already matches the live posting', 'ok'); openJob(cur.job.id);
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
/* ---- market pay (paydata.py): public BLS OEWS percentiles from the cache; the drawer fetches the job you open (one try
   per job per page load), the board never fetches. Every BLS string goes through esc() ---- */
const PCT = [['p10', '10th'], ['p25', '25th'], ['p50', 'median'], ['p75', '75th'], ['p90', '90th'], ['mean', 'mean']];
const payAmt = (p, k) => num(p[k]) + (p.capped.includes(k) ? '+' : '');
const payLine = x => PCT.filter(([k]) => x.pay[k] != null).map(([k, l]) => `${l} ${payAmt(x.pay, k)}`).join(' | ');
const payChip = x => x && x.pay && x.pay.p50 != null ? `<span class="chip pay" title="${esc(`BLS ${payLine(x)}\n${x.soc.name} (${x.soc.soc}), ${x.area.name}\n\n${x.label}`)}">market median $${Math.round(x.pay.p50 / 1000)}k${x.pay.capped.includes('p50') ? '+' : ''} (BLS May ${esc(x.pay.year)}, ${esc(x.area.short)}${x.state === 'stale' ? ', retrieved ' + esc(x.pay.fetched_at) : ''})</span>` : '';
const PAY_TRIED = new Set();
const pctName = s => s === 'median' ? 'the median' : `the ${s} percentile`;
const bandText = b => /^(below|above) /.test(b) ? `${b.split(' ')[0]} ${pctName(b.split(' ')[1])}` : `between ${pctName(b.split('-')[0])} and ${pctName(b.split('-')[1])}`;
function payStrip(x, j) {  // five ticks on a line, the posting's range drawn over them; plain CSS
  const p = x.pay, ks = PCT.slice(0, 5).filter(([k]) => p[k] != null), post = x.posting_band ? [j.salary_min, j.salary_max].filter(v => v) : [];
  if (!ks.length) return '';
  const vals = [...ks.map(([k]) => p[k]), ...post], lo = Math.min(...vals) * 0.95, hi = Math.max(...vals) * 1.05, pos = v => (v - lo) / (hi - lo) * 100;
  const bar = post.length ? `<span class="post" style="left:${pos(post[0]).toFixed(1)}%;width:${Math.max(1, pos(post[post.length - 1]) - pos(post[0])).toFixed(1)}%" title="this posting: ${esc(post.map(num).join(' - '))}"></span>` : '';
  return `<div class="pstrip" role="img" aria-label="${esc('BLS percentiles: ' + payLine(x) + (post.length ? '; this posting ' + post.map(num).join(' - ') : ''))}">${bar}${ks.map(([k, l]) => `<i style="left:${pos(p[k]).toFixed(1)}%"><b>${l}</b><span>${payAmt(p, k)}</span></i>`).join('')}</div>`;
}
function payGroup(d) {
  const x = d.pay || {}, j = d.job, occ = d.occupations || {};
  if (x.state === 'off') return `<div class="group" id="jPay"><h4>Market pay (BLS)</h4><div class="row"><span class="muted grow">Off. Public U.S. wage percentiles for this job's occupation and area, from the Bureau of Labor Statistics. Turning it on sends only occupation and area codes to api.bls.gov (never your profile, your floor or this job's text); the monitor loop then fills in the other jobs, one query a cycle.</span><button class="b sm" id="jPayOn" onclick="payEnable(this)">Turn on market pay</button></div></div>`;
  if (x.state === 'error' || !x.state) return '';
  const opts = Object.entries(occ).map(([c, n]) => `<option value="${esc(c)}" ${j.soc_by === 'user' && j.soc === c ? 'selected' : ''}>${esc(n)} (${esc(c)})</option>`).join('');
  const sel = `<div class="row"><label class="muted">occupation <select id="jSoc" onchange="paySoc(${j.id},this.value)"><option value="">automatic</option>${opts}<option value="none" ${j.soc === 'none' ? 'selected' : ''}>none (hide market pay)</option></select></label>
    <button class="b ghost sm" id="jSocAi" onclick="payRun(${j.id},true,this)" ${hasAI() ? '' : 'disabled title="needs an AI provider"'}>Match occupation (AI)</button></div>`;
  if (x.state === 'hidden') return `<div class="group" id="jPay"><h4>Market pay (BLS)</h4><div class="muted">Hidden for this job (occupation: none).</div>${sel}</div>`;
  const soc = x.soc ? `${esc(x.soc.name)} (${esc(x.soc.soc)}), ${x.soc.by === 'you' ? 'set by you' : x.soc.by === 'AI' ? 'matched by AI from a fixed list' : 'matched by ' + esc(x.soc.by)}`
    : 'No occupation matched. Pick one, or Match occupation (AI).';
  const area = x.state === 'no_area' ? 'Location not recognised as a U.S. metro or state. BLS covers U.S. jobs only; for a U.S. job add the state, e.g. "Boise, ID".'
    : x.area ? `${esc(x.area.name)} (${esc(x.area_note || x.area.why)})` : '';
  let body = '';
  if (x.pay) {
    const p = x.pay, gone = PCT.filter(([k]) => p[k] == null).map(([, l]) => l), top = x.posting_band && (x.posting_band.max || x.posting_band.min);
    body = payStrip(x, j) + `<div class="muted">${esc(payLine(x))}${gone.length ? ` · not published: ${esc(gone.join(', '))}` : ''}</div>`
      + (top ? `<div>This posting's ${x.posting_band.max ? 'top end' : 'stated pay'} sits ${esc(bandText(top))}.</div>` : '')
      + `<div class="muted plabel">${esc(x.label)}</div>`;
  } else if (x.state === 'unpublished') body = `<div class="muted">BLS publishes no figure for ${esc(x.soc.name)} here (metro, state or national).</div>`;
  else if (x.state === 'missing') body = '<div class="muted">No BLS figure retrieved yet.</div>';
  return `<div class="group" id="jPay"><h4>Market pay (BLS)</h4><div class="muted">occupation: ${soc}</div>${sel}${area ? `<div class="muted">area: ${area}</div>` : ''}${body}
    ${x.next ? `<div class="row"><button class="b ghost sm" id="jPayGet" onclick="payRun(${j.id},false,this)">Fetch BLS figures</button></div>` : ''}<div id="jPayErr" class="muted" role="status"></div></div>`;
}
function payRedraw(id, pay, err) {  // only the Market pay group: anything typed elsewhere in the drawer stays
  if (!cur || cur.job.id !== id || !$('#jPay')) return;
  cur.pay = pay; $('#jPay').outerHTML = payGroup(cur);
  if (err && $('#jPayErr')) $('#jPayErr').textContent = err;
}
function payRun(id, ai, btn) {
  run('market_pay', { id, ai }, r => payRedraw(id, r.pay, r.error), btn, e => { if ($('#jPayErr')) $('#jPayErr').textContent = e; });
}
async function payEnable(btn) {
  btn.disabled = true;
  const r = await api('/api/prefs', { key: 'market_pay', value: true }); if (r.error) { btn.disabled = false; return toast('error: ' + r.error, 'err'); }
  toast('market pay on: BLS figures for the job you open; the monitor loop fills in the rest', 'ok');
  const id = cur.job.id; await load(); openJob(id);
}
async function paySoc(id, soc) {
  const r = await api(`/api/jobs/${id}/soc`, { soc }); if (r.error) return toast('error: ' + r.error, 'err');
  await load(); await openJob(id);  // the board's chip follows
  if (r.pay && r.pay.next) payRun(id, false);
}
const sponsorChip = s => s ? `<span class="chip" title="from the USCIS H-1B data you imported (${esc(s.name)}); a loose name match, not a promise">possible H-1B sponsor (${esc(s.approvals)} approvals)</span>` : '';
function listingHtml(j, i) {
  const unknown = ['salary', 'location', 'date'].filter(k => j[k + '_unknown']).map(k => `<span class="chip" title="the listing does not say; kept rather than dropped">${k} unknown</span>`).join('');
  const cov = fitBadge(j);
  const host = u => { try { return new URL(u).hostname; } catch (_) { return 'link'; } };
  const more = (j.urls || []).slice(1).filter(safeUrl).map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))} ↗</a>`).join(' ');
  const g = j.ghost && j.ghost.score >= GHOST_SHOW ? `<div class="muted">possibly stale: ${esc(j.ghost.reasons.join('; '))}</div>` : '';
  const c = (j.fit_chips || []).length ? `<div class="muted fitwhy">${esc(j.fit_chips.join(' · '))}</div>` : '';  // the fit's top reasons
  return `<div>${j.score != null ? `<span class="score">${esc(j.score)}</span>` : ''}<b>${esc(j.title)}</b> @ ${esc(j.company)} <span class="muted">${esc(j.location)} ${esc(j.salary)} &lt;${esc((j.sources || [j.source]).join(', '))}&gt;</span>
    ${safeUrl(j.url) ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">open ↗</a>` : ''} ${more} <button class="b ghost sm" onclick="saveListing(${i})">track</button>
    <div class="chips">${j.tracked ? `<span class="chip" title="already on your Board">tracked as #${esc(j.tracked)}</span>` : ''}${cov}${staleChip(j.ghost)}${sponsorChip(j.sponsor)}${warmChip(j.warm)}${unknown}${j.seniority ? `<span class="chip">${esc(j.seniority)}</span>` : ''}</div>${c}${g}${j.why ? `<div class="muted">${esc(j.why)}</div>` : ''}</div>`;
}
/* ---- search profile (web_monitor.defaults): roles and place from Preferences, else the resume; prefill only empty boxes ---- */
let SP = {};
function spPaint() {
  $('#spRoles').value = (SP.roles || []).join(', '); $('#spLoc').value = SP.location || '';
  $('#sProfFrom').textContent = SP.roles && SP.roles.length ? `(roles from ${SP.roles_from}${SP.location ? ', place from ' + SP.location_from : ''})` : '(empty: add the roles you want)';
  $('#spChips').innerHTML = (SP.roles || []).map((r, i) => `<button class="b ghost sm" onclick="spUse(${i})">${esc(r)}</button>`).join('');
  // a place you saved in Preferences fills the filter; one only read off your resume is a suggestion (no hidden filter)
  if (!$('#sLoc').value && SP.location && SP.location_from === 'Preferences') $('#sLoc').value = SP.location;
  $('#sLoc').placeholder = SP.location ? `e.g. "${SP.location}"` : 'location, e.g. "Austin, TX or remote"';
  $('#sQ').placeholder = SP.query ? `blank: ${SP.query}` : 'roles, e.g. "data engineer, analytics engineer"';
}
async function spLoad() { const r = await api('/api/search/defaults'); if (!r.error) { SP = r; spPaint(); } }
function spUse(i) { $('#sQ').value = (SP.roles || [])[i] || ''; $('#sQ').focus(); }
async function spSave(btn) {
  btn.disabled = true;
  try {
    const r = await api('/api/search/profile', { roles: $('#spRoles').value, location: $('#spLoc').value });
    if (r.error) return toast('error: ' + r.error, 'err');
    SP = r.defaults; $('#sLoc').value = ''; spPaint(); toast('saved to Preferences (private: never sent to employers)', 'ok');
  } finally { btn.disabled = false; }
}
function doSearch(btn) {
  $('#sRes').innerHTML = '<div class="muted">searching…</div>';
  run('search', { ...searchParams(), rank: $('#sRank').checked }, r => {
    RESULTS = r.results || []; const errs = r.errors || [];
    AJ_HI = new Set(r.ids || []); loadAllJobs();  // stored in All jobs below, marked "from this search"
    const none = errs.length && !RESULTS.length && errs.filter(e => !e.startsWith('AI rank')).length >= (r.boards || Infinity)
      ? 'No job board could be reached, so nothing was checked. Check your connection and try again.' : 'nothing found';
    $('#sRes').innerHTML = (!$('#sQ').value.trim() && r.query ? `<div class="muted">searched your roles: ${esc(r.query)}</div>` : '')
      + (errs.length ? `<div class="warnbox" role="alert">${errs.map(e => 'could not ' + (e.startsWith('AI rank') ? 'rank: ' + esc(e.slice(9)) : 'read ' + esc(e))).join('<br>')}</div>` : '')
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

/* ---- All jobs (listings.py): every listing any source found, merged; rows stay in AJ, markup carries only an index ---- */
let AJ = [], AJ_TOTAL = 0, AJ_HI = new Set(), AJ_T = null, AJ_OPEN = {};
const ajParams = () => ({ q: $('#ajQ').value.trim(), min_fit: $('#ajFit').value, remote: $('#ajRemote').value, min_salary: $('#ajSal').value,
  days: $('#ajDays').value, show: $('#ajShow').value, sort: $('#ajSort').value, new: $('#ajNew').checked ? '1' : '', source: [...AJ_SRC].join(',') });
const AJ_SRC = new Set();
function ajDebounce() { clearTimeout(AJ_T); AJ_T = setTimeout(() => loadAllJobs(), 300); }
async function loadAllJobs(more = false) {
  if (!$('#ajList')) return;
  const p = new URLSearchParams(Object.entries({ ...ajParams(), offset: more ? AJ.length : 0 }).filter(([, v]) => v !== '' && v != null));
  const r = await api('/api/listings?' + p);
  if (r.error) { $('#ajList').innerHTML = `<div class="warnbox" role="alert">${esc(r.error)}</div>`; return; }
  AJ = more ? AJ.concat(r.rows) : r.rows; AJ_TOTAL = r.total;
  if (!more) AJ_OPEN = {};
  $('#ajCount').textContent = `${r.total} listing(s)` + (r.stale ? ` · ${r.stale} being re-scored` : '');
  const names = Object.keys(r.sources).sort();
  $('#ajSources').innerHTML = names.map((s, i) => `<button class="chip board${AJ_SRC.has(s) ? ' on' : ''}" aria-pressed="${AJ_SRC.has(s)}" onclick="ajSrc(${i})" data-src="${esc(s)}">${esc(srcLabel(s))} ${esc(r.sources[s])}</button>`).join('');
  $('#ajSources').dataset.names = JSON.stringify(names);
  renderAllJobs();
}
function ajSrc(i) {
  const s = JSON.parse($('#ajSources').dataset.names || '[]')[i]; if (!s) return;
  AJ_SRC.has(s) ? AJ_SRC.delete(s) : AJ_SRC.add(s); loadAllJobs();
}
const srcLabel = s => ((S && S.sources && S.sources[s]) || {}).label || (s === 'capture' ? 'Browser capture'
  : /_alert$/.test(s) ? (((S && S.alert_sites) || {})[s.slice(0, -6)] || {label: s.slice(0, -6)}).label + ' alert' : s);
function boardChip(s) {  // the source's name as a link to its site: the credit Adzuna, Himalayas and We Work Remotely ask for
  const src = (S && S.sources && S.sources[s]) || {}, home = safeUrl(src.home);
  return home ? `<a class="chip src-link${s === 'adzuna' ? ' attr-adzuna' : ''}" href="${esc(home)}" target="_blank" rel="noopener" title="listed on ${esc(src.label)}">${esc(src.label)}</a>`
    : `<span class="chip">${esc(srcLabel(s))}</span>`;
}
function ajRow(x, i) {
  const host = u => { try { return new URL(u).hostname; } catch (_) { return 'link'; } };
  const links = (x.urls || []).slice(1).filter(safeUrl).map(u => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(host(u))} ↗</a>`).join(' ');
  const chips = (x.fit_chips || []).map(c => `<span class="chip">${esc(c)}</span>`).join('');
  const open = AJ_OPEN[x.id];
  return `<div class="ajrow${x.new ? ' new' : ''}${AJ_HI.has(x.id) ? ' hi' : ''}" role="listitem" data-id="${esc(x.id)}">
    <div>${fitBadge(x)} <a href="#" class="ajt" onclick="ajExpand(${i});return false" aria-expanded="${!!open}"><b>${esc(x.title)}</b></a> @ ${esc(x.company)} <span class="muted">${esc(x.location)} ${esc(x.salary)}</span>
      ${x.new ? '<span class="pill ok">new</span>' : ''}${AJ_HI.has(x.id) ? '<span class="pill">from this search</span>' : ''}${x.reposted_at ? `<span class="chip stale" title="a new link for this role on ${esc(x.reposted_at)}">reposted</span>` : ''}${x.closed_at ? `<span class="chip" title="the source says applications close then">closes ${esc(x.closed_at)}</span>` : ''}</div>
    <div class="chips">${(x.sources || []).map(boardChip).join(' ')}${sponsorChip(x.sponsor)}${warmChip(x.warm)}${chips}</div>
    <div class="row">${x.job_id ? `<button class="b ghost sm" onclick="openJob(${Number(x.job_id)})">tracked as #${esc(x.job_id)}</button>` : `<button class="b sm" onclick="ajTrack(${i},this)">Track</button>`}
      <button class="b ghost sm" onclick="ajDismiss(${i},this)">${x.dismissed ? 'Undismiss' : 'Dismiss'}</button>
      <button class="b ghost sm" onclick="ajAi(${i},this)" ${hasAI() ? '' : 'disabled title="needs an AI provider (Setup > Link an AI key)"'}>AI fit</button>
      ${safeUrl(x.url) ? `<a class="b ghost sm" href="${esc(x.url)}" target="_blank" rel="noopener">Open ↗</a>` : ''} ${links}</div>
    ${open ? ajDetail(open) : ''}</div>`;
}
function ajDetail(d) {
  const f = d.fit;
  const parts = f ? Object.entries(f.parts).map(([p, v]) => `<span class="pill">${esc(p)} ${v.s == null ? '-' : esc(v.s)} (weight ${esc(v.w)})</span>`).join('') : '';
  return `<div class="ajdetail">${f ? `<div class="muted">fit ${esc(f.score)}${f.partial ? ' · partial' : ''} · ${esc(f.note || '')}</div><div>${parts}</div>
    <div class="chips">${(f.chips || []).map(c => `<span class="chip">${esc(c.sign + ' ' + c.text)}</span>`).join('')}</div>` : '<div class="muted">not scored yet</div>'}
    <pre class="ajdesc">${esc(d.desc || '(no description: open the posting, or capture it with the extension)')}</pre></div>`;
}
function renderAllJobs() {
  $('#ajList').innerHTML = AJ.map(ajRow).join('') || `<div class="empty">No jobs yet. Run a search, save one as a watch, add companies, or set up job alerts (Setup &gt; Job sources).</div>`;
  if (AJ.length < AJ_TOTAL) $('#ajList').insertAdjacentHTML('beforeend', `<div class="row"><button class="b ghost" onclick="loadAllJobs(true)">Load ${Math.min(100, AJ_TOTAL - AJ.length)} more</button></div>`);
}
async function ajExpand(i) {
  const x = AJ[i]; if (!x) return;
  if (AJ_OPEN[x.id]) { delete AJ_OPEN[x.id]; return renderAllJobs(); }
  const r = await api('/api/listings/' + Number(x.id));
  if (r.error) return toast('error: ' + r.error, 'err');
  AJ_OPEN[x.id] = r; renderAllJobs();
}
async function ajTrack(i, btn) {
  const x = AJ[i]; if (!x) return;
  btn.disabled = true;
  const r = await api(`/api/listings/${Number(x.id)}/track`, {}); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('tracked as #' + r.id, 'ok'); await load(); loadAllJobs();
}
async function ajDismiss(i, btn) {
  const x = AJ[i]; if (!x) return;
  btn.disabled = true;
  const r = await api(`/api/listings/${Number(x.id)}/dismiss`, { on: !x.dismissed }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(x.dismissed ? 'back in the list' : 'dismissed (Which listings > dismissed shows it again)', 'ok'); loadAllJobs();
}
function ajAi(i, btn) {
  const x = AJ[i]; if (!x) return;
  run('listing_ai', { listing: x.id }, r => { toast(`AI fit: fit ${r.fit.score} now`, 'ok'); delete AJ_OPEN[x.id]; loadAllJobs(); }, btn);
}
async function ajSeen(btn) {
  btn.disabled = true;
  const r = await api('/api/listings/visit', {}); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('all marked seen', 'ok'); loadAllJobs();
}
/* ---- Setup > Job alerts: per site, the last alert mail read and its job count; the job_alerts switch ---- */
function renderAlertSites() {
  const el = $('#alertList'); if (!el) return;
  const a = S.alert_sites || {}, tool = (S.tools || []).find(t => t.tool === 'job_alerts') || {};
  el.innerHTML = Object.keys(a).map(n => `<div><b>${esc(a[n].label)}</b> <span class="muted">${a[n].last ? `last alert read ${esc(new Date(a[n].last * 1000).toLocaleString())} · ${Number(a[n].n)} job${a[n].n === 1 ? '' : 's'} in it` : 'no alert read yet'}</span></div>`).join('');
  const on = $('#alertsOn'); if (on) on.checked = !!tool.enabled;
}
async function alertsToggle(on) {
  const r = await api('/api/tools', { tool: 'job_alerts', enabled: on });
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(`job alerts ${on ? 'on' : 'off'}`, 'ok'); load();
}
/* ---- Setup > Job sources: each board's state; Adzuna and USAJOBS keys link here (verified with one small search) ---- */
let BOARDS = [];
function renderSources() {
  const src = S.sources || {}, keys = (S.connections || {}).keys || {};
  BOARDS = Object.keys(src);
  $('#srcList').innerHTML = BOARDS.map((n, i) => {
    const s = src[n], k = keys[n], home = safeUrl(s.home);
    const when = s.last ? new Date(s.last * 1000).toLocaleString() : 'not yet';
    const head = `<b>${home ? `<a href="${esc(home)}" target="_blank" rel="noopener">${esc(s.label)}</a>` : esc(s.label)}</b> <span class="pill ${s.ready ? 'ok' : 'warn'}">${s.ready ? 'ready' : 'needs keys'}</span>`
      + ` <span class="muted">${s.every_h ? `saved searches ask it at most every ${esc(s.every_h)} h${s.global ? ' (one fetch for all your searches)' : ''}` : ''}${s.global ? ' · last fetched ' + esc(when) : ''}</span>`;
    if (!k) return `<div>${head}</div>`;
    const [label, cls] = KSTAT[k.status] || KSTAT.unchecked;
    return `<div class="srckey">${head} ${k.linked ? `<span class="pill ${cls}">${esc(label)}</span> <span class="muted">${esc(k.status !== 'verified' ? k.detail : '')}</span>` : ''}
      <div class="row"><input id="srcId${i}" autocomplete="off" placeholder="${esc(k.id_label)}" aria-label="${esc(s.label + ' ' + k.id_label)}" style="width:220px">
        <input id="srcKey${i}" type="password" autocomplete="off" placeholder="key" aria-label="${esc(s.label)} key" style="width:220px">
        <button class="b sm" onclick="srcLink(${i},this)">${k.linked ? 'Replace' : 'Link'}</button>
        ${k.linked ? `<button class="b ghost sm" onclick="srcCheck(${i},this)">Re-check</button><button class="b ghost sm" onclick="srcRemove(${i})">Remove</button>` : ''}</div>
      <div class="muted">Free key: ${safeUrl(k.get) ? `<a href="${esc(k.get)}" target="_blank" rel="noopener">${esc(k.get)}</a>` : ''} · stored as ${s.keys.map(x => `<code>${esc(x.name)}</code>`).join(' + ')}${n === 'adzuna' ? ' · Adzuna listings always show an "Adzuna" link (their terms); at most 100 calls a day; pref adzuna_country picks the country site' : ''}</div></div>`;
  }).join('');
}
async function srcLink(i, btn) {
  const n = BOARDS[i]; if (!n) return;
  btn.disabled = true;
  try {
    const r = await api('/api/keys/link', { name: n, key: $('#srcKey' + i).value, id: $('#srcId' + i).value });
    if (r.error) return toast('error: ' + r.error, 'err');
    toast(`${r.label}: ${(KSTAT[r.status] || KSTAT.unchecked)[0]} - ${r.detail}`, r.status === 'failed' ? 'err' : 'ok');
  } finally { const k = $('#srcKey' + i); if (k) k.value = ''; btn.disabled = false; load(); }
}
async function srcCheck(i, btn) {
  const n = BOARDS[i]; if (!n) return;
  btn.disabled = true;
  const r = await api('/api/keys/check', { name: n }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  load();
}
async function srcRemove(i) {
  const n = BOARDS[i], s = (S.sources || {})[n]; if (!s || !confirm(`Remove the ${s.label} key from the OS keyring?`)) return;
  const r = await api('/api/keys/remove', { name: n }); toast(r.error ? 'error: ' + r.error : 'removed', r.error ? 'err' : 'ok'); load();
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
    : typeof v === 'object' && v ? `<span class="muted">${esc(Object.entries(v).map(([p, m]) => p + '=' + (m === '' || m == null ? '(default)' : m === 0 ? '0 (off)' : m)).join(', ') || (k === 'weekly_goals' ? 'none set' : k === 'fit_weights' ? 'defaults (skills=35, role=20, experience=15, location=15, pay=15, ai=25)' : 'none pinned'))}</span><input class="grow" aria-labelledby="pl${i}" placeholder="${k === 'weekly_goals' ? 'goal=number, e.g. contacts=5 (0 clears); also on the Insights tab' : k === 'fit_weights' ? 'part=number, e.g. skills=40 (0 = off; skills= drops it)' : 'provider=model to pin (empty model = default); Setup > List models shows ids'}" onchange="setPref(${ref},this.value)">${k === 'fit_weights' ? `<button class="b ghost sm" onclick="setPref(${ref},'reset')">Reset weights</button>` : ''}`
    : `<input class="grow" aria-labelledby="pl${i}" value="${esc(v)}" onchange="setPref(${ref},this.value)">`}</div>`).join('');
}
async function setPref(key, value) { const r = await api('/api/prefs', { key, value }); if (r.error) toast('error: ' + r.error, 'err'); load(); }
function renderSetup() {
  renderKeys();
  renderSources(); renderAlertSites();
  $('#vList').innerHTML = S.vault.map((v, i) => `<span class="pill">${esc(v.name + (v.user ? ' (' + v.user + ')' : ''))} <button class="b ghost sm" aria-label="remove" onclick="delVault(${i})">×</button></span>`).join(' ') || 'empty';
  const u = Object.entries(S.usage).filter(([k]) => k !== 'total');
  $('#usage').innerHTML = u.length ? 'last 30 days: ' + u.map(([k, d]) => `<span class="pill">${esc(k)}: ${d.calls} calls · ${(d.input + d.output).toLocaleString()} tokens</span>`).join(' ') : '';
  $('#pPath').textContent = S.profile_path;
  $('#pNotify').checked = !!S.prefs.desktop_notifications;
  const rates = Object.entries(S.comp).flatMap(([t, cities]) => Object.entries(cities).map(([c, [lo, hi]]) => ({ t, c, lo, hi })));
  $('#compList').innerHTML = rates.map((r, i) => `<div><b>${esc(r.t)}</b> <span class="muted">${esc(r.c === '*' ? 'any city' : r.c)}</span> ${esc(r.lo.toLocaleString())} - ${esc(r.hi.toLocaleString())} <button class="b ghost sm" onclick="compOp({op:'delete',title:RATES[${i}].t,city:RATES[${i}].c})">remove</button></div>`).join('') || '<div class="muted">none recorded: gap checks, offer evaluation and interview prep then say "none recorded"</div>';
  RATES = rates;
  renderExt();
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
/* ---- browser extension: pairing string, paired browsers, revoke (extension.py) ---- */
let EXT_TIMER = null;
function renderExt() {
  $('#extList').innerHTML = (S.extensions || []).map((e, i) => `<div><b>${esc(e.label)}</b> <span class="muted">${esc(String(e.origin).replace('chrome-extension://', '').slice(0, 8))}… · paired ${esc(String(e.paired_at).slice(0, 16).replace('T', ' '))} · last used ${esc(String(e.last_used).slice(0, 16).replace('T', ' '))}</span> <button class="b ghost sm" onclick="extRevoke(${i})">Revoke</button></div>`).join('') || '<div class="muted">no browser paired</div>';
  if (document.activeElement !== $('#extBm')) $('#extBm').value = S.prefs.bookmarklets || 'auto';
  $('#bmLinks').style.display = S.bookmarklets_on ? '' : 'none';
  $('#bmState').textContent = S.bookmarklets_on ? 'Drag these to your bookmarks bar. The UI must be running.'
    : 'Off: a browser extension is paired (or you turned them off). Turn them on under Browser extension > Bookmarklets.';
}
async function extPair(btn) {
  btn.disabled = true;
  const r = await api('/api/extension/code', {}).finally(() => btn.disabled = false);
  if (r.error) return toast('error: ' + r.error, 'err');
  const until = Date.now() + r.expires_in * 1000, known = new Set((S.extensions || []).map(e => e.id));
  $('#extCode').textContent = `${r.port}-${r.code}`;
  clearInterval(EXT_TIMER);
  let n = 0;
  const tick = async () => {
    const left = Math.round((until - Date.now()) / 1000);
    if (left <= 0) { clearInterval(EXT_TIMER); $('#extCode').textContent = ''; $('#extLeft').textContent = 'the code expired: press Pair a browser again'; return; }
    $('#extLeft').textContent = `type this in the extension's popup (${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')} left)`;
    if (n++ % 2) return;  // every 2 s: has a browser paired with this (single-use) code?
    const p = await api('/api/extension/paired').catch(() => ({}));
    const fresh = (p.extensions || []).find(e => !known.has(e.id));
    if (!fresh || !EXT_TIMER) return;
    clearInterval(EXT_TIMER); EXT_TIMER = null;
    S.extensions = p.extensions; $('#extCode').textContent = ''; $('#extLeft').textContent = `paired: ${fresh.label}`;
    renderExt(); load();  // bookmarklets_on may have changed with it
  };
  tick(); EXT_TIMER = setInterval(tick, 1000);
}
async function extRevoke(i) {
  const e = (S.extensions || [])[i]; if (!e || !confirm(`Revoke ${e.label}? That browser can no longer capture or fill until you pair it again.`)) return;
  const r = await api('/api/extension/revoke', { id: e.id }); toast(r.error || (r.ok ? 'revoked ' + e.label : 'already revoked'), r.error ? 'err' : 'ok'); load();
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
  KEYS = Object.keys(c.keys).filter(n => c.keys[n].kind !== 'jobs');  // job-data keys link under Setup > Job sources
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
      + ` <button class="b ghost sm" ${env ? 'disabled title="set in .env or the environment: remove it there"' : ''} onclick="keyRemove(${i})">Remove</button></div>`;
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
  const n = KEYS[i], k = (S.connections?.keys || {})[n];
  if (!k || !confirm(n === 'ollama' ? 'Unlink Ollama? Lodestar stops using it (its saved model is cleared).' : `Remove the ${k.label} key from the OS keyring?`)) return;
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
let PROFILE_LOADED = '', PROFILE_BASE = '';  // last text loaded from / saved to disk; its hash (the server's stale check)
async function loadProfile() { const r = await api('/api/profile'); $('#pText').value = PROFILE_LOADED = r.text; PROFILE_BASE = r.base || ''; }
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
  $('#bMore').innerHTML = BANK_KINDS.filter(k => (b[k] || []).length).map(k => `<div class="row"><b style="width:90px">${esc((v.titles || {})[k] || 'Other')}</b><div class="grow">`
    + b[k].map((e, i) => `<span class="pill">${esc(v.labels[k][i])} <button class="b ghost sm" aria-label="remove" onclick="bankRemoveAt('${k}',${i})">×</button></span>`).join(' ') + '</div></div>').join('');
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
const BANK_KINDS = ['experience', 'education', 'projects', 'awards', 'publications', 'volunteering', 'patents', 'speaking', 'links', 'interests', 'other'];
function bankRemoveAt(kind, i) { const label = BANK.labels[kind][i]; bankOp({ op: 'remove_at', kind, index: i, label }, 'removed ' + label); }
function importToBank(inputId, linkedin, btn) {
  const f = $('#' + inputId).files[0]; if (!f) return toast('choose a file first', 'err');
  const rd = new FileReader();
  rd.onload = () => run('profile_import', { name: f.name, data: rd.result.split(',')[1], linkedin, review: true, ai: $('#pNoAi').checked ? false : undefined }, r => {
    const p = r.pending, todo = p.items.filter(i => i.status !== 'duplicate').length;
    toast(`read ${f.name} (${p.used_ai ? 'AI' : 'offline'} extraction): ${todo} item(s) to review below; nothing saved to your profile yet`, 'ok');
    loadReviews();
    if (!linkedin) { $('#pImport').value = p.text; $('#pImport').style.display = ''; $('#pImportActions').style.display = ''; }
  }, btn);
  rd.readAsDataURL(f);
}
function rebuildMaster(btn) {
  const dirty = $('#pText').value !== PROFILE_LOADED;
  if (!confirm('Replace profile.md with a version built from the bank? The saved file is snapshotted to profile-history/ first.' +
    (dirty ? '\n\nThe editor has UNSAVED changes; they are not in any snapshot and will be lost. Save first to keep them.' : ''))) return;
  run('profile_rebuild', {}, r => { loadProfile(); renderBank(r); toast('master rebuilt from the bank', 'ok'); }, btn);
}
/* ---- import review: every fact read from a file waits here until accepted (profile.stage_import / apply_import) ---- */
let REVIEWS = [];
async function loadReviews() { const r = await api('/api/profile/imports'); if (!r.error) { REVIEWS = r.imports; renderReviews(); } }
function itemLabel(it) {
  const v = it.incoming;
  if (v === null || typeof v !== 'object') return (it.field ? it.field + ': ' : '') + String(v ?? '');
  const a = ['title', 'role', 'name', 'degree', 'heading', 'label'].map(f => v[f]).find(Boolean) || '';
  const b = ['company', 'organization', 'school', 'issuer', 'venue', 'event', 'url'].map(f => v[f]).find(Boolean) || '';
  const d = [v.start, v.end].filter(Boolean).join(' - ') || v.date || '';
  return [a, b].filter(Boolean).join(' - ') + (d ? ` (${d})` : '') + ((v.bullets || []).length ? ` · ${v.bullets.length} bullet(s)` : '');
}
const STATUS_PILL = { new: 'ok', changed: 'ok', conflict: 'warn', duplicate: '' };
function reviewHtml(p, n) {
  const rows = p.items.map(it => {
    const box = it.status === 'duplicate' ? '' : it.status === 'conflict' ? '' : `<input type="checkbox" id="rv${n}_${esc(it.id)}" ${it.default ? 'checked' : ''} aria-label="accept ${esc(itemLabel(it))}">`;
    const pick = it.status !== 'conflict' ? '' : `<select id="rt${n}_${esc(it.id)}" aria-label="conflict choice"><option value="mine">keep mine</option><option value="incoming">use incoming</option>${it.fuzzy ? '<option value="both">add separately</option>' : ''}</select>`;
    const fields = Object.entries(it.fields || {}).map(([f, [mine, inc]]) => `<div class="muted">${esc(f)}: yours <b>${esc(mine)}</b> · incoming <b>${esc(inc)}</b></div>`).join('')
      + (it.status === 'conflict' && it.existing && !Object.keys(it.fields || {}).length ? `<div class="muted">yours: ${esc(typeof it.existing === 'object' ? itemLabel({ incoming: it.existing }) : it.existing)}</div>` : '');
    const adds = Object.entries(it.adds || {}).map(([f, x]) => `<div class="muted">adds ${esc(f)}: ${esc(Array.isArray(x) ? x.join('; ') : x)}</div>`).join('');
    return `<tr class="${it.flags.length ? 'flag' : ''}"><td>${box}${pick}</td><td><span class="pill ${STATUS_PILL[it.status] || ''}">${esc(it.status)}</span></td><td class="muted">${esc(it.kind)}</td>
      <td>${esc(itemLabel(it))}${fields}${adds}${it.quote ? `<div class="muted">“${esc(it.quote)}”</div>` : ''}${it.flags.map(f => `<div class="flagtxt">${esc(f)}</div>`).join('')}</td></tr>`;
  }).join('');
  const dropped = (p.dropped || []).length ? `<div class="warnbox">Not stored: ${esc(p.dropped.map(d => d.label + (d.line ? ` (line ${d.line})` : '')).join(', '))}. Lodestar never puts personal details like these in a resume. If an application form asks for work authorization, save it in the answer bank.</div>` : '';
  const unread = (p.unread || []).length ? `<details><summary class="muted">${p.unread.length} line(s) were not read into the profile</summary><pre>${esc(p.unread.join('\n'))}</pre></details>` : '';
  const notes = (p.notes || []).map(x => `<div class="muted">${esc(x)}</div>`).join('');
  return `<div class="panel review" id="review${n}"><h3>Review import: ${esc(p.file)}</h3><div class="muted">${esc(p.created.replace('T', ' '))} · ${p.used_ai ? 'AI' : 'offline'} extraction · flagged rows start unchecked; a conflict keeps yours unless you choose otherwise</div>
    ${dropped}<table class="kw bul"><thead><tr><th>accept</th><th>status</th><th>kind</th><th>fact</th></tr></thead><tbody>${rows}</tbody></table>${unread}${notes}
    <div class="row"><label class="muted"><input type="checkbox" id="rvMaster${n}" checked> also add to my master profile (profile.md)</label></div>
    <div class="row"><button class="b sm" onclick="reviewApply(${n},'new',this)">Accept all new</button><button class="b ghost sm" onclick="reviewApply(${n},'sel',this)">Apply selected</button><button class="b ghost sm" onclick="reviewDiscard(${n},this)">Discard</button></div></div>`;
}
function renderReviews() { $('#pReview').innerHTML = REVIEWS.map(reviewHtml).join(''); }
async function reviewApply(n, mode, btn) {
  const p = REVIEWS[n], take = {}, conflicts = [];
  p.items.filter(it => it.status === 'conflict').forEach(it => { const v = $(`#rt${n}_${it.id}`)?.value || 'mine'; take[it.id] = v; if (v !== 'mine') conflicts.push(it.id); });
  const picked = mode === 'new' ? p.items.filter(it => it.default).map(it => it.id) : p.items.filter(it => $(`#rv${n}_${it.id}`)?.checked).map(it => it.id);
  btn.disabled = true;
  const r = await api(`/api/profile/imports/${encodeURIComponent(p.id)}/apply`, { accept: [...picked, ...conflicts], take, to_master: $('#rvMaster' + n).checked });
  btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  renderBank(r);
  const got = Object.entries(r.added).map(([k, c]) => c + ' ' + k).join(', ') || 'nothing new';
  toast(`applied: ${got}; ${r.updated} updated${r.master_changed ? '; profile.md updated' : ''}` + (r.notes.length ? ' | ' + r.notes.join(' | ') : ''), 'ok');
  if (r.master_changed) {  // never clobber text typed into the editor but not saved yet
    if ($('#pText').value === PROFILE_LOADED) loadProfile();
    else toast('profile.md got the imported lines; your unsaved editor text was kept: copy it, Reload the page, then redo your edit', 'err');
  }
  loadReviews(); loadMaster();
}
async function reviewDiscard(n, btn) {
  btn.disabled = true; const r = await api(`/api/profile/imports/${encodeURIComponent(REVIEWS[n].id)}/discard`, {}); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('import discarded: your profile is unchanged', 'ok'); loadReviews();
}
/* ---- master resume (studio.py): built from the saved profile, offline ---- */
async function loadMaster() { const r = await api('/api/studio'); if (!r.error) renderMaster(r.master); }
function renderMaster(m) {
  const f = m.files || {}, when = m.built ? m.built.replace('T', ' ').slice(0, 16) : '';
  clearTimeout(MASTER_POLL); MASTER_POLL = m.pending ? setTimeout(loadMaster, 4000) : null;  // a rebuild is due: follow it
  $('#mStatus').innerHTML = (when ? `Updated from your profile at ${esc(when)}` + (m.engine ? ` · ${esc(m.engine)}` : '') + (m.pages ? ` · ${m.pages} page(s)` : '') : m.pending ? 'Building from your profile shortly…' : 'Not built yet: Update now builds it')
    + (m.stale && when ? ' <span class="chip stale">profile changed: updates shortly, or Update now</span>' : '');
  $('#mDiff').innerHTML = (m.diff || []).length ? `<div class="muted">last change: ${esc(m.diff.join(' · '))}</div>` : '';
  $('#mWarn').innerHTML = (m.last_error ? `<div class="warnbox">${esc(m.last_error)}</div>` : '') + (m.warnings || []).map(w => `<div class="warnbox">${esc(w)}</div>`).join('');
  $('#mPdf').disabled = !f.pdf && !f.html; $('#mPdf').textContent = f.pdf || !f.html ? 'Open PDF' : 'Open print page'; $('#mDocx').disabled = !f.docx;
  MASTER = m;
}
let MASTER = null, MASTER_POLL = null;
async function openMaster(ext) {
  const e = ext === 'pdf' && MASTER && !(MASTER.files || {}).pdf ? 'html' : ext, r = await api('/api/master/open', { ext: e });
  toast(r.error ? 'error: ' + r.error : 'opened ' + r.path, r.error ? 'err' : 'ok');
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
  const text = $('#pText').value, r = await api('/api/profile', { text, base: PROFILE_BASE });
  if (r.error) return toast('save failed: ' + r.error, 'err');
  PROFILE_LOADED = text; PROFILE_BASE = r.base || '';
  toast('profile saved (previous version kept in profile-history/)', 'ok'); loadBank(); loadMaster();
}
function fillCoachJobs() {  // rebuilt on every refresh so jobs added later appear; keeps the selected job
  const keep = $('#cJob').value;
  $('#cJob').innerHTML = S.jobs.map(j => `<option value="${j.id}">#${j.id} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
  if (S.jobs.some(j => String(j.id) === keep)) $('#cJob').value = keep;
  if ($('#cFocus').options.length < 2) $('#cFocus').insertAdjacentHTML('beforeend', (S.qcomp || []).map(c => `<option value="${esc(c)}">focus: ${esc(c)}</option>`).join(''));
}
// the scored session; seconds dictated for the next answer; keys of the questions asked (the server picks the next one);
// the last question (its key goes with the answer, looked up server-side); competencies answered; the last readiness
const newMock = () => ({ session: null, secs: 0, asked: [], last: null, comps: new Set(), ready: null });
let MOCK = newMock();
function resetChat() {
  const mock = $('#cMode').value === 'mock';
  MOCK = newMock(); $('#mockSum').style.display = $('#mockReady').style.display = 'none'; $('#mockSum').textContent = '';
  $('#cJob').style.display = $('#cFocus').style.display = $('#cSpeakL').style.display = mock ? '' : 'none';
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
  const params = mock ? { id: $('#cJob').value, messages: chatHist, session: MOCK.session, seconds: MOCK.secs || undefined,
    asked: MOCK.asked.slice(-100), focus: $('#cFocus').value || undefined, qkey: MOCK.last ? MOCK.last.key : undefined } : council ? { prompt: q, messages: chatHist } : { messages: chatHist };
  MOCK.secs = 0;
  run(action, params, r => {
    const a = council && !mock ? r.synthesis : r.reply; chatHist.push({ role: 'assistant', content: a });
    if (r.card) {
      MOCK.session = r.card.session; if (r.card.competency) MOCK.comps.add(r.card.competency);
      $('#chat').insertAdjacentHTML('beforeend', cardHtml(r.card)); mockSummary(r.card, r.readiness); mockReady(r.readiness);
    }
    if (r.question) { MOCK.asked.push(r.question.key); MOCK.last = r.question; }  // the server's pick, with where it came from
    $('#chat').insertAdjacentHTML('beforeend', `<div class="msg ai">${esc(a)}</div>` + (r.question ? `<div class="msg-src">question source: ${srcChip(r.question)}</div>` : ''));
    $('#chat').scrollTop = 1e9;
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
    + (c.jd_keywords.length ? `<div class="muted">posting keywords used: ${esc(c.jd_keywords.join(', '))}</div>` : '')
    + (c.source ? `<div class="muted">question: ${esc(SRC_NAME[c.source] || c.source)}${c.competency ? ' · ' + esc(c.competency) : ''}</div>` : '') + '</div>';
}
function mockSummary(c, rd) {
  const a = c.averages, f = v => v == null ? '-' : v;
  $('#mockSum').style.display = '';
  $('#mockSum').textContent = `session #${c.session}: ${a.answers} answer(s), ${a.scored} scored · STAR average ${f(a.star)}/2 · relevance ${f(a.relevance)}/2 · specificity ${f(a.specificity)}/2`
    + (a.metrics_used != null ? ` · numbers in ${Math.round(a.metrics_used * 100)}% of answers` : '') + ` · ${f(a.words)} words on average`
    + (MOCK.comps.size ? ` · practised: ${[...MOCK.comps].join(', ')}` : '') + (rd && rd.practised ? ' · ' + rd.practised : '');
}
function mockReady(x) {  // readiness after a scored answer: preparation only, the band is never a probability
  const el = $('#mockReady'), id = Number($('#cJob').value), j = S.jobs.find(v => v.id === id) || {};
  if (!x) { el.style.display = 'none'; return; }
  const prev = MOCK.ready; MOCK.ready = x.score; el.style.display = '';
  el.innerHTML = `Readiness for #${id} ${esc(j.company)}: ${prev != null && prev !== x.score ? Number(prev) + ' -> ' : ''}${Number(x.score)} · chance estimate ${esc(cap(x.chance))} (not a probability)
    <a href="#" onclick="openReady(${id});return false">see why</a>`;
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
  const [a, o, c, b] = await Promise.all([api('/api/analytics?weeks=' + Number($('#insRange').value || 12)), api('/api/offers'), api('/api/readiness/calibration'), api('/api/boosters')]);
  if (a.error || o.error) return toast('error: ' + (a.error || o.error), 'err');
  INS = a; OFF = o; renderInsights(); renderOffers();
  BOOSTS.i = b.boosters || [];
  $('#insBoost').innerHTML = b.error ? esc(b.error) : BOOSTS.i.map((x, i) => boostRow(x, 'i', i)).join('') || '<div class="muted">Nothing to boost right now: open jobs with a description get boosters here.</div>';
  if (c.error) $('#insReady').textContent = c.error; else renderReadyRecord(c);
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
  $('#insBand').innerHTML = rateRows(a.by_band) + '<div class="muted">bands of the fit score each job had when it left "saved" (else its fit now), applications only</div>';
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
    + (rows.some(r => r.paydata && r.paydata.pay) ? `<tr><td>BLS market (median / 75th)</td>${rows.map(r => { const x = r.paydata || {}, p = x.pay;
      return `<td>${p && p.p50 != null ? `<span title="${esc(x.label)}">${payAmt(p, 'p50')} / ${p.p75 != null ? payAmt(p, 'p75') : '-'}</span>${x.base_band ? ` <span class="muted">· base at ${esc(x.base_band)}</span>` : ''}` : '<span class="muted">none cached</span>'}</td>`; }).join('')}</tr>` : '')
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
  const me = OFF.offers.find(r => r.job_id === id), x = me && me.paydata, p = x && x.pay;  // public BLS figures of this job
  if (p) CITE.push(...[['market_median', 'p50', 'median'], ['market_p75', 'p75', '75th percentile']]
    .filter(([, k]) => p[k] != null && !(me.offer.base >= p[k]))  // at or below their base it would argue for less
    .map(([f, k, w]) => [`${id}:${f}`, `public BLS ${w} for this job: ${payAmt(p, k)} (May ${p.year}, ${x.area.short})`]));
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
  run('counter', { id, cite, ask: $('#ctrAsk').value, template: $('#ctrTpl').checked }, r => {
    show('ctrOut', mailText(r)); CTR = { id, cite, text: (r.draft || {}).body || '' }; $('#ctrView').style.display = CTR.text ? '' : 'none';
  }, btn);
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

/* ---- pipeline (pipeline.py): the drawer's stage strip, Run next step / Run to, the questions queue, Autopilot, run log.
   Stage names and question texts stay in JS (PIPE, QM); markup carries only indexes and numeric ids ---- */
const ST_ICON = { done: '✓', ready: '▶', waiting: '?', stale: '↻', blocked: '⛔', error: '!', running: '⟳', todo: '○', later: '·', skipped: '–' };
const stWord = e => e.state === 'waiting' ? (e.on === 'employer' ? 'waiting on the employer' : 'waiting on you') : e.state;
const stIcon = e => e.state === 'waiting' && e.on === 'employer' ? '…' : ST_ICON[e.state] || '·';
const stg = n => (S.pipeline_stages || []).find(s => s.name === n) || {};
const stLabel = n => stg(n).label || n;
let PIPE = [], PSEL = null, PJOB = null, QM = {};  // the open job's steps; the step whose line is shown (by name) and its job; question id -> question
function pipelineGroup(d) {
  PIPE = d.pipeline || []; if (PJOB !== d.job.id) { PSEL = null; PJOB = d.job.id; } if (!PIPE.length) return '';
  const j = d.job, nx = PIPE.find(e => e.state === 'ready'), qs = d.questions || [];
  const you = PIPE.filter(e => e.state === 'waiting' && e.on === 'you'), emp = PIPE.filter(e => e.state === 'waiting' && e.on === 'employer');
  const reason = nx ? '' : you.length ? 'waiting on you: ' + you[0].why : emp.length ? 'waiting on the employer: ' + emp[0].why : 'nothing is ready to run';
  const fit = PIPE.find(e => e.name === 'score'), gated = fit && (fit.output || {}).verdict === 'skip';
  const asked = e => qs.filter(q => (q.jobs || []).some(w => w.job_id === j.id && w.stage === e.name)).length;
  const tos = PIPE.filter(e => stg(e.name).run && !stg(e.name).manual && !['later', 'skipped'].includes(e.state));
  const dflt = [...tos].reverse().find(e => e.state !== 'done') || tos[tos.length - 1];
  const done = PIPE.filter(e => e.state === 'done').length, total = PIPE.filter(e => !['later', 'skipped'].includes(e.state)).length;
  return `<div class="group" id="pGroup"><h4>Pipeline <span class="muted">${done} of ${total} steps done</span></h4>
    ${gated ? `<div class="row"><span class="pill warn">fit: skip</span><span class="muted">${esc(fit.output.why || '')}: Autopilot leaves this job alone</span><button class="b ghost sm" onclick="continueAnyway(this)">Continue anyway</button></div>` : ''}
    <div class="strip" role="group" aria-label="Pipeline steps">${PIPE.map((e, i) => { const n = e.state === 'waiting' && e.on === 'you' ? asked(e) : 0;
      return `<button class="stage s-${esc(e.state)}${e.state === 'waiting' && e.on === 'employer' ? ' emp' : ''}${PSEL === e.name ? ' on' : ''}" aria-pressed="${PSEL === e.name}" aria-label="${esc(`${e.label}: ${stWord(e)}${e.why ? ' (' + e.why + ')' : ''}`)}" title="${esc(stWord(e) + (e.why ? ': ' + e.why : ''))}" onclick="pickStage(${i})">${stIcon(e)} ${esc(e.label)}${n ? ' ' + n : ''}</button>`; }).join('')}</div>
    <div id="pLine"></div>
    <div class="row"><button class="b" id="pNext" ${nx ? '' : 'disabled'} onclick="pipeRun({},this)">Run next step${nx ? ' (' + esc(nx.label) + ')' : ''}</button>${reason ? `<span class="muted" id="pWhy">${esc(reason)}</span>` : ''}</div>
    ${tos.length ? `<div class="row"><label class="muted">Run to <select id="pTo">${tos.map(e => `<option value="${esc(e.name)}" ${e === dflt ? 'selected' : ''}>${esc(e.label)}</option>`).join('')}</select></label><button class="b ghost sm" onclick="pipeRun({to:$('#pTo').value,rerun:$('#pStale').checked},this)">Go</button><label class="muted"><input type="checkbox" id="pStale"> include stale steps (re-run them)</label></div>` : ''}
    ${qs.length ? `<h4>Questions for you</h4>${qs.map(q => questionCard(q, 'd')).join('')}` : ''}
    <details><summary class="muted">Form questions (${Number(((PIPE.find(e => e.name === 'answers') || {}).output || {}).form?.length || 0)})</summary>
      <textarea id="pForm" rows="3" style="min-height:60px" aria-label="Form questions, one per line" placeholder="paste the application form's questions, one per line"></textarea>
      <div class="row"><button class="b ghost sm" onclick="addFormQs(this)">Add form questions</button><span class="muted">the Form answers step drafts what it can and asks you the rest (never eligibility or EEO)</span></div></details>
    <details><summary class="muted">Run log (${(d.runs || []).length})</summary><div class="scroll">${runLogHtml(d.runs)}</div></details></div>`;
}
function pickStage(i) { const e = PIPE[i]; PSEL = e && PSEL !== e.name ? e.name : null; $$('#pGroup .stage').forEach((b, k) => { const on = PIPE[k].name === PSEL; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); }); stageLine(); }
function stageLine() {
  const el = $('#pLine'); if (!el) return;
  const i = PIPE.findIndex(e => e.name === PSEL), e = PIPE[i]; if (!e) { el.innerHTML = ''; return; }
  const st = stg(e.name), j = cur.job, o = e.output || {}, btns = [];
  if (st.run && ['ready', 'error', 'done', 'stale'].includes(e.state)) btns.push(`<button class="b sm" onclick="pipeRun({stage:PIPE[${i}].name,rerun:${['done', 'stale'].includes(e.state)}},this)">${e.state === 'error' ? 'Retry' : e.state === 'ready' ? 'Run' : 'Re-run'}</button>`);
  if (!['done', 'skipped', 'running', 'later'].includes(e.state) && e.name !== 'close') btns.push(`<button class="b ghost sm" onclick="skipStage(${i},true)">Skip</button>`);
  if (e.state === 'skipped' && e.why === 'skipped by you') btns.push(`<button class="b ghost sm" onclick="skipStage(${i},false)">Unskip</button>`);
  if (e.name === 'apply' && j.status === 'saved') {
    if (safeUrl(j.url)) btns.push(`<a class="b ghost sm" href="${esc(j.url)}" target="_blank" rel="noopener">Open posting ↗</a>`);
    btns.push(`<button class="b ghost sm" onclick="openJobFolder(${j.id},'')">Show folder</button>`);
    if ('form_answers.md' in cur.docs) btns.push(`<button class="b ghost sm" onclick="docTab('form_answers.md')">form_answers.md</button>`);
    btns.push(`<button class="b sm" onclick="moveJob(${j.id},'applied')">Mark applied</button>`);
  }
  const files = o.file && o.file in cur.docs && e.name !== 'apply' ? `<button class="b ghost sm" onclick="docTab(PIPE[${i}].output.file)">${esc(o.file)}</button>` : '';
  const from = Object.entries(e.inputs || {}).filter(([, v]) => v).map(([k, v]) => `${stLabel(k)} ${String(v).slice(0, 6)}`).join(', ');
  el.innerHTML = `<div class="stline"><div><b>${stIcon(e)} ${esc(e.label)}</b>: ${esc(stWord(e))}${e.why ? ' · ' + esc(e.why) : ''}</div>
    ${o.verdict ? `<div class="muted">fit: ${esc(o.verdict)}${o.why ? ' (' + esc(o.why) + ')' : ''}</div>` : ''}
    ${e.rev ? `<div class="muted">rev ${Number(e.rev)} · ${esc(e.origin || '')}${e.updated_at ? ' · ' + esc(localTs(e.updated_at, 16)) : ''}${from ? ' · built from ' + esc(from) : ''}</div>` : ''}
    ${e.state === 'error' && e.error ? `<div class="row"><span class="pill warn">${esc(e.error)}</span></div>` : ''}
    <div class="row">${files}${btns.join('')}</div></div>`;
}
function docTab(n) { const b = $$('#docTabs button').find(x => x.textContent === n); showDoc(n, b); $('#docView').scrollIntoView({ block: 'nearest' }); }
const runsText = runs => runs.length ? runs.map(x => `${stLabel(x.stage)}: ${x.outcome}${x.outcome === 'error' || x.outcome === 'skipped' ? ' (' + x.detail + ')' : ''}`).join('; ')
  : 'nothing ran: the first step on the way is waiting, blocked, manual or stale (tick "include stale steps" to re-run those)';
function pipeRun(body, btn) {
  const id = cur.job.id;
  run('pipeline_run', { id, ...body }, r => { toast(runsText(r.runs), r.runs.some(x => x.outcome === 'error') || !r.runs.length ? 'err' : 'ok'); if (cur && cur.job.id === id) openJob(id); }, btn);
}
function continueAnyway(btn) { if (confirm('The fit check said skip. Run the next step for this job anyway? Autopilot still leaves it alone; this click is the override.')) pipeRun({}, btn); }
async function skipStage(i, on) {
  const e = PIPE[i], id = cur.job.id; if (!e) return;
  const r = await api(`/api/pipeline/${id}/skip`, { stage: e.name, on }); if (r.error) return toast('error: ' + r.error, 'err');
  toast(`${e.label} ${on ? 'skipped for this job' : 'back in the pipeline'}`, 'ok'); await load(); openJob(id);
}
async function addFormQs(btn) {
  const id = cur.job.id, lines = $('#pForm').value; if (!lines.trim()) return toast('paste the questions first, one per line', 'err');
  btn.disabled = true; const r = await api(`/api/pipeline/${id}/questions`, { lines }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(`${Number(r.added)} new form question(s); run the Form answers step to answer them`, 'ok'); $('#pForm').value = ''; await load(); openJob(id);
}
function runLogHtml(rows, job) {
  return rows && rows.length ? `<table class="log"><tr><th>when</th>${job ? '<th>job</th>' : ''}<th>step</th><th>by</th><th>outcome</th><th>AI calls</th><th>detail</th></tr>${rows.map(r => `<tr><td>${esc(localTs(r.ts, 16))}</td>${job ? `<td><a href="#" onclick="openJob(${Number(r.job_id)});return false">#${Number(r.job_id)}</a></td>` : ''}<td>${esc(stLabel(r.stage))}</td><td>${esc(r.origin)}</td><td>${esc(r.outcome)}</td><td>${Number(r.ai)}</td><td>${esc(r.detail)}</td></tr>`).join('')}</table>`
    : '<div class="muted">no runs yet</div>';
}
async function pipeLog(btn) { const r = await api('/api/pipeline/log?limit=50'); if (r.error) return toast('error: ' + r.error, 'err'); $('#apLog').innerHTML = `<div class="scroll">${runLogHtml(r.runs, true)}</div>`; }

/* questions: the same card in the Inbox (prefix i) and the drawer (prefix d) */
function questionCard(q, pre) {
  const id = Number(q.id), k = q.kind, never = k === 'eligibility' || k === 'eeo', f = `${pre}q${id}`, ctx = q.context || {};
  QM[id] = q;
  const input = q.options ? `<select id="${f}a" aria-label="answer">${q.options.map(o => `<option value="${esc(o)}">${esc(o)}</option>`).join('')}</select>`
    : k === 'number' ? `<input id="${f}a" type="number" aria-label="answer" style="width:160px">`
    : k === 'date' ? `<input id="${f}a" type="date" aria-label="answer">`
    : `<textarea id="${f}a" aria-label="answer" rows="3" maxlength="4000" style="min-height:60px"></textarea>`;
  return `<div class="item q" data-q="${id}"><div class="hd"><b>${esc(q.text)}</b>${(q.jobs || []).map(w => `<span class="pill">#${Number(w.job_id)} ${esc(w.company)} - ${esc(stLabel(w.stage))}</span>`).join('')}
      ${never ? `<span class="pill warn">You answer this one; Lodestar never drafts ${k === 'eeo' ? 'EEO' : 'eligibility'} answers</span>` : ''}${q.blocking ? '' : '<span class="pill">optional</span>'}</div>
    ${ctx.why ? `<div class="muted">why: ${esc(ctx.why)}</div>` : ''}${q.waiting > 1 ? `<div class="muted">${Number(q.waiting)} jobs are waiting</div>` : ''}
    <div class="row">${input}</div>
    ${(q.suggestions || []).length ? `<div class="row"><span class="muted">from your answers:</span>${q.suggestions.map((s, n) => `<button class="b ghost sm" title="${esc(s.question)}" onclick="useSugg('${pre}',${id},${n})">Use this: ${esc(String(s.answer).slice(0, 60))}</button>`).join('')}</div>` : ''}
    <div class="row"><select id="${f}s" aria-label="use this answer for" ${q.apply_to === 'bank' ? '' : 'disabled'}><option value="reusable" ${q.scope_default === 'reusable' ? 'selected' : ''}>every job</option><option value="job" ${q.scope_default === 'job' ? 'selected' : ''}>only this job${q.job_id ? ' (#' + Number(q.job_id) + ')' : ''}</option></select>
      <label class="muted"><input type="checkbox" id="${f}p" ${k === 'private' ? 'checked' : ''}> private (this job only, never in the answer bank)</label>
      <button class="b sm" onclick="answerQ('${pre}',${id},this)">Save answer</button><button class="b ghost sm" onclick="dismissQ(${id},this)">I'll fill it in myself</button></div></div>`;
}
function useSugg(pre, id, n) { const s = ((QM[id] || {}).suggestions || [])[n], a = $(`#${pre}q${id}a`); if (s && a) { a.value = s.answer; a.focus(); } }
async function afterQ(r, msg) {
  if (r.error) return toast('error: ' + r.error, 'err');
  const n = (r.resumed || []).length; toast(msg + (n ? `; ${n} waiting step(s) can go on` : ''), 'ok'); await load(); if (cur) openJob(cur.job.id);
}
async function answerQ(pre, id, btn) {
  const f = `#${pre}q${id}`, text = $(f + 'a').value.trim(); if (!text) return toast('type an answer first', 'err');
  btn.disabled = true; const r = await api(`/api/questions/${id}/answer`, { text, scope: $(f + 's').value, private: $(f + 'p').checked }); btn.disabled = false;
  afterQ(r, 'answer saved');
}
async function dismissQ(id, btn) { btn.disabled = true; const r = await api(`/api/questions/${id}/dismiss`, {}); btn.disabled = false; afterQ(r, 'left for you to fill in'); }
function keepVals(root) {  // the 60 s refresh re-renders: typed answers, picks and the caret survive it
  const vals = {}; root.querySelectorAll('input[id], textarea[id], select[id]').forEach(e => {
    const d = e.tagName === 'SELECT' ? ([...e.options].find(o => o.defaultSelected) || e.options[0] || {}).value : e.type === 'checkbox' ? e.defaultChecked : e.defaultValue;
    const v = e.type === 'checkbox' ? e.checked : e.value; if (v !== d) vals[e.id] = v; });
  const f = root.contains(document.activeElement) ? document.activeElement : null, at = f && [f.id, f.selectionStart, f.selectionEnd];
  return () => {
    for (const [k, v] of Object.entries(vals)) { const e = document.getElementById(k); if (e) e[e.type === 'checkbox' ? 'checked' : 'value'] = v; }
    const b = at && at[0] && document.getElementById(at[0]); if (b) { b.focus(); try { b.setSelectionRange(at[1], at[2]); } catch (_) { /* not a text field */ } }
  };
}
function renderQuestions() {
  const root = $('#questions'), back = keepVals(root), qs = S.questions || [];
  root.innerHTML = qs.length ? `<h3>Questions for you (${qs.length})</h3><p class="sub">Facts a pipeline step needs and cannot know. Answer once: "every job" saves it to your answer bank, "only this job" keeps it with this application. Eligibility and EEO answers are always yours.</p>${qs.map(q => questionCard(q, 'i')).join('')}` : '';
  back();
}

/* board chip, table column, bulk runs */
function pipeChip(j) {
  const p = (S.pipeline || {})[j.id]; if (!p) return '';
  if (p.you) return `<span class="chip pq" title="waiting on you">? ${Number(p.you)}</span>`;
  if (p.errors) return '<span class="chip pe" title="a step failed: open the job to retry">! error</span>';
  if (p.stale) return '<span class="chip" title="an earlier step changed since">↻ stale</span>';
  return p.next ? `<span class="chip" title="the next pipeline step">next: ${esc(stLabel(p.next))}</span>` : '';
}
function bulkPipe(useTo, btn) {
  const ids = [...SEL], to = useTo ? $('#bulkTo').value : '', names = (S.pipeline_stages || []).map(s => s.name);
  if (ids.length > 25) return toast('at most 25 jobs at a time', 'err');
  const n = ids.reduce((sum, id) => { const nx = ((S.pipeline || {})[id] || {}).next, a = names.indexOf(nx); if (a < 0) return sum;
    return sum + S.pipeline_stages.slice(a, (to ? names.indexOf(to) : a) + 1).filter(s => s.run && !s.manual).reduce((x, s) => x + s.ai, 0); }, 0);
  if (!confirm(`${to ? 'Run to ' + stLabel(to) : 'Run the next step'} for ${ids.length} job(s)? About ${n} AI call${n === 1 ? '' : 's'}.`)) return;
  run('pipeline_bulk', { ids, to: to || undefined }, r => {
    const bad = r.jobs.filter(x => x.error || (x.runs || []).some(y => y.outcome === 'error')), ran = r.jobs.filter(x => (x.runs || []).length);
    const idle = r.jobs.filter(x => !x.error && !(x.runs || []).length).length;  // nothing ready: not an error
    SEL.clear(); toast(`ran steps for ${ran.length} of ${r.jobs.length} job(s)` + (idle ? `; ${idle} had nothing ready` : '')
      + (bad.length ? ': ' + bad.map(x => `#${Number(x.id)}: ${String(x.error || 'a step failed').replace(/^#\d+:?\s*/, '')}`).join('; ') : ''), bad.length ? 'err' : 'ok');
  }, btn);
}

/* Autopilot: the top-bar pill and the Setup card (master switch, budgets, per-step switches, last cycle, run log) */
function renderAutopilot() {
  const p = S.prefs, a = S.autopilot || {}, pill = $('#apPill');
  pill.textContent = p.autopilot ? `Autopilot: on · ${Number(a.spent)} of ${Number(p.autopilot_ai_per_day)} AI calls today` : 'Autopilot: off';
  pill.classList.toggle('on', !!p.autopilot);
  $('#apOn').checked = !!p.autopilot;
  [['#apCycle', 'autopilot_ai_per_cycle'], ['#apDay', 'autopilot_ai_per_day'], ['#apJobs', 'autopilot_jobs_per_cycle']].forEach(([s, k]) => { if (document.activeElement !== $(s)) $(s).value = p[k]; });
  const rows = (S.pipeline_stages || []).filter(s => s.tool && s.run).map(s => { const i = S.tools.findIndex(t => t.tool === s.tool), t = S.tools[i]; return t ? `<tr><td><b>${esc(s.label)}</b> <span class="muted">(${esc(t.tool)}, about ${Number(s.ai)} AI call${s.ai === 1 ? '' : 's'})</span><div class="muted">${esc(t.description)}</div></td>
    <td><input type="checkbox" aria-label="${esc(s.label)} enabled" ${t.enabled ? 'checked' : ''} onchange="api('/api/tools',{tool:S.tools[${i}].tool,enabled:this.checked}).then(load)"></td>
    <td><input type="checkbox" aria-label="${esc(s.label)} auto" ${t.auto ? 'checked' : ''} onchange="api('/api/tools',{tool:S.tools[${i}].tool,auto:this.checked}).then(load)"></td></tr>` : ''; }).join('');
  $('#apStages').innerHTML = `<table><tr><th>Step</th><th>enabled</th><th>auto</th></tr>${rows}</table>`;
  const l = a.last || {};
  $('#apLast').textContent = l.at ? `last cycle ${l.at}: ran ${Number(l.ran)}, proposed ${Number(l.proposed)}${l.note ? ' · ' + l.note : ''}` : 'no Autopilot cycle in this process yet (the monitor loop runs one every cycle)';
  if (!$('#bulkTo').options.length) $('#bulkTo').innerHTML = (S.pipeline_stages || []).filter(s => s.run && !s.manual).map(s => `<option value="${esc(s.name)}">${esc(s.label)}</option>`).join('');
}

/* ---- drawer keyboard: Esc closes (asking first when typed text would be lost), Tab stays inside (aria-modal) ---- */
function drawerDirty() {  // a document editor that differs from the saved file, or any typed text field in the drawer
  const ed = $('#docEdit');
  if (ed && ed.dataset.open === '1' && cur && ed.value !== (cur.docs[ed.dataset.name] || '')) return true;
  return $$('#drawer input:not([type=checkbox]):not([type=hidden]), #drawer textarea').some(e => e !== ed && e.value !== e.defaultValue);
}
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex="0"]';
document.addEventListener('keydown', e => {
  if (!$('#viewer').hidden) return vwKey(e);  // the viewer sits above the drawer: its keys first
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
/* ---- resume studio (studio.py): request + requirements -> a version (PDF / DOCX / MD / TXT), preview, history ---- */
let STU = null, SV = null, SROWS = null, SDIRTY = false;  // GET /api/studio; the version on show; [[section, on]] in order; you changed them
const LOOK = [['pages', 'pages', ['', '1', '2', '0']], ['template', 'template'], ['font', 'font'], ['size', 'size (pt)', 'num', 9.5, 12, 0.5],
  ['accent', 'accent'], ['margins', 'margins (in)', 'num', 0.4, 1.25, 0.05], ['line_spacing', 'line spacing', 'num', 1, 1.5, 0.05],
  ['paper', 'paper'], ['date_format', 'dates'], ['contact_layout', 'contact line'], ['heading_case', 'headings'], ['density', 'density'],
  ['bullets_per_role', 'bullets per role', 'num', 0, 10, 1], ['since', 'leave out roles ended before', 'num', 1950, 2100, 1]];
async function loadStudio() { const r = await api('/api/studio'); if (r.error) return toast('error: ' + r.error, 'err'); STU = r; renderStudio(); }
function studioFor(id) { go('studio'); const pick = () => { if (STU) $('#sJob').value = String(id); $('#sJd').style.display = 'none'; $('#sReq').focus(); }; STU ? pick() : loadStudio().then(pick); }
function renderStudio() {
  const c = STU.choices, d = STU.defaults || {};
  if (!$('#sLook').children.length) {  // built once: your picks survive a refresh
    $('#sLook').innerHTML = LOOK.map(([k, label, kind, lo, hi, step]) => {
      if (kind === 'num') return `<label class="muted">${label} <input id="sL_${k}" type="number" min="${lo}" max="${hi}" step="${step}" style="width:80px" placeholder="${esc(d[k] ?? '')}"></label>`;
      const opts = Array.isArray(kind) ? kind.slice(1) : c[k] || [];
      const extra = k === 'accent' ? '<option value="custom">custom…</option>' : '';
      return `<label class="muted">${label} <select id="sL_${k}" ${k === 'accent' ? 'onchange="$(\'#sL_accentC\').style.display=this.value===\'custom\'?\'\':\'none\'"' : ''}><option value="">default${d[k] !== undefined && k !== 'pages' ? ' (' + esc(d[k]) + ')' : ''}</option>${opts.map(o => `<option value="${esc(o)}">${esc(o === '0' ? 'no limit' : o)}</option>`).join('')}${extra}</select></label>`
        + (k === 'accent' ? '<input type="color" id="sL_accentC" aria-label="Custom accent colour" value="#1f3a5f" style="display:none">' : '');
    }).join('');
    $('#sFormats').innerHTML = c.formats.filter(f => f !== 'html').map(f => `<label class="muted"><input type="checkbox" class="sFmt" value="${f}" ${(d.formats || []).includes(f) ? 'checked' : ''}> ${f}</label>`).join(' ');
  }
  if (!SROWS) { const on = new Set(d.sections || c.sections); SROWS = [...(d.sections || c.sections), ...c.sections.filter(k => !on.has(k))].map(k => [k, on.has(k)]); renderSections(); }
  const sel = $('#sJob').value;
  $('#sJob').innerHTML = '<option value="">no job</option>' + (S ? S.jobs : []).filter(j => !['rejected', 'withdrawn', 'accepted'].includes(j.status))
    .map(j => `<option value="${j.id}">${esc(j.company)} - ${esc(j.title)} (#${j.id})</option>`).join('');
  $('#sJob').value = sel;
  $('#sDrop').innerHTML = STU.catalogue.length ? STU.catalogue.map(e => `<label class="muted"><input type="checkbox" class="sDrop" value="${esc(e.id)}"> <b>${esc(e.id)}</b> ${esc(e.label)}${e.on_file ? ' <span class="chip">on file</span>' : ''}</label>`).join('<br>')
    : `<span class="muted">${esc(STU.catalogue_error || 'no entries yet')}</span>`;
  $('#sHint').textContent = STU.ai ? (STU.engine ? `PDF by ${STU.engine}` : 'no PDF engine: you get the page to print, plus .docx') : 'no AI provider: Build without AI uses your profile as written (Setup > Link an AI key to describe changes in words)';
  $('#sBuild').disabled = !STU.ai;
  $('#sHist').innerHTML = STU.versions.length ? STU.versions.map((v, i) => `<div class="row"><b>${esc(v.created.replace('T', ' ').slice(0, 16))}</b>
    <span class="muted">${v.job_id ? 'job #' + v.job_id : 'general'} · ${v.pages ? v.pages + ' page(s)' : 'pages unknown'} · ${v.used_ai ? 'AI' : 'offline'}${v.parent ? ' · refined' : ''}</span>
    <span class="grow">${esc((v.request || '(no request)').slice(0, 90))}</span>${v.profile_changed ? '<span class="chip stale">profile changed since</span>' : ''}
    <button class="b ghost sm" onclick="openVersion(${i})">Open</button><button class="b ghost sm danger" onclick="deleteVersion(${i})">Delete</button></div>`).join('')
    : '<div class="muted">no versions yet: Build makes the first</div>';
}
function renderSections() {
  $('#sSections').innerHTML = SROWS.map(([k, on], i) => `<div class="row"><label class="muted"><input type="checkbox" class="sSec" value="${k}" ${on ? 'checked' : ''} onchange="SROWS[${i}][1]=this.checked;SDIRTY=true"> ${k}</label>
    <button class="b ghost sm" aria-label="move ${k} up" onclick="moveSection(${i},-1)" ${i ? '' : 'disabled'}>↑</button><button class="b ghost sm" aria-label="move ${k} down" onclick="moveSection(${i},1)" ${i < SROWS.length - 1 ? '' : 'disabled'}>↓</button></div>`).join('');
}
function moveSection(i, dir) {
  const j = i + dir; if (j < 0 || j >= SROWS.length) return;
  [SROWS[i], SROWS[j]] = [SROWS[j], SROWS[i]]; SDIRTY = true; renderSections();
  $$('#sSections .row')[j].querySelector(`button[aria-label$="${dir < 0 ? 'up' : 'down'}"]:not([disabled])`)?.focus();
}
function studioReq() {  // only what you set: blank fields leave the choice to the request, your saved look and the template
  const req = {};
  LOOK.forEach(([k]) => { const v = $('#sL_' + k).value; if (v !== '') req[k] = k === 'accent' && v === 'custom' ? $('#sL_accentC').value : v; });
  if (SDIRTY) req.sections = SROWS.filter(r => r[1]).map(r => r[0]);
  const fm = $$('.sFmt').filter(x => x.checked).map(x => x.value), dflt = (STU.defaults || {}).formats || [];
  if (fm.join() !== dflt.join()) req.formats = fm.length ? fm : ['docx'];
  const drop = $$('.sDrop').filter(x => x.checked).map(x => x.value); if (drop.length) req.drop = drop;
  if ($('#sOnFile').checked) req.include_on_file = true;
  return req;
}
function studioBuild(ai, btn) {
  const id = $('#sJob').value, body = { request: ai ? $('#sReq').value : '', req: studioReq(), ai };
  if (id) body.id = Number(id); else if ($('#sJd').value.trim()) body.jd = $('#sJd').value;
  if (!ai && $('#sReq').value.trim()) toast('Build without AI ignores the request: it uses your profile as written', '');
  run('studio_build', body, v => { showVersion(v); loadStudio(); toast(`version built: ${v.pages ? v.pages + ' page(s)' : 'page count unknown'}`, 'ok'); }, btn);
}
async function openVersion(i) { const v = await api('/api/studio/' + encodeURIComponent(STU.versions[i].vid)); if (v.error) return toast('error: ' + v.error, 'err'); showVersion(v); }
async function deleteVersion(i) {
  const v = STU.versions[i]; if (!confirm(`Delete the version of ${v.created.slice(0, 16)}? Its files go too.`)) return;
  const r = await api(`/api/studio/${encodeURIComponent(v.vid)}/delete`, {}); if (r.error) return toast('error: ' + r.error, 'err');
  if (SV && SV.vid === v.vid) { SV = null; $('#sResult').style.display = 'none'; }
  toast('version deleted', 'ok'); loadStudio();
}
async function showVersion(v) {
  if (!v.html) v = await api('/api/studio/' + encodeURIComponent(v.vid));  // a build result carries no page text
  if (v.error) return toast('error: ' + v.error, 'err');
  SV = v;
  const f = v.files || {}, jobs = (S ? S.jobs : []).filter(j => !['rejected', 'withdrawn', 'accepted'].includes(j.status));
  const warn = [...(v.notes || []).map(x => ['note', x]), ...(v.events || []).map(x => ['check', x]), ...(v.warnings || []).map(x => ['warning', x])];
  $('#sResult').style.display = '';
  $('#sResult').innerHTML = `<h3>Version ${esc(v.vid)}</h3>
    <div class="muted">${v.pages ? v.pages + ' page(s)' : 'page count unknown'}${v.style && v.style.pages ? ' (limit ' + v.style.pages + ')' : ''} · ${v.engine ? 'PDF by ' + esc(v.engine) : 'no PDF engine'} · ${v.used_ai ? 'AI plan' : 'offline'}${v.coverage ? ' · JD coverage ' + esc(v.coverage.score) + '%' : ''}${v.parent ? ' · refined from ' + esc(v.parent) : ''}</div>
    <div class="row">${['pdf', 'docx', 'txt', 'md', 'html'].filter(x => f[x]).map(x => `<button class="b ghost sm" onclick="studioOpen('${x}')">Open ${x === 'html' ? 'page' : x.toUpperCase()}</button>`).join('')}
      <button class="b ghost sm" onclick="api('/api/open_folder',{which:'studio'}).then(r=>r.error&&toast('error: '+r.error,'err'))">Show folder</button>
      <button class="b ghost sm" onclick="studioLook(this)">Make this my default look</button><button class="b ghost sm" onclick="openViewer({type:'studio',vid:SV.vid})">View / format</button></div>
    <div class="row"><label class="muted">use for <select id="sUseJob">${jobs.map(j => `<option value="${j.id}" ${j.id === v.job_id ? 'selected' : ''}>${esc(j.company)} - ${esc(j.title)} (#${j.id})</option>`).join('')}</select></label><button class="b sm" onclick="studioUse(this)" ${jobs.length ? '' : 'disabled'}>Use for this job</button><span class="muted">replaces its resume.md / .docx / .pdf (the old ones go to history/)</span></div>
    ${v.coverage && v.coverage.missing.length ? `<div class="muted">not covered: ${esc(v.coverage.missing.join(', '))}</div>` : ''}
    <div id="sWarn">${warn.map(([k, x]) => `<div class="${k === 'warning' ? 'warnbox' : 'muted'}">${esc(k)}: ${esc(x)}</div>`).join('')}</div>
    <details><summary class="muted">ATS checks (${(v.lint || []).length + Object.values(v.audit || {}).flat().length})</summary>${issuesHtml({ issues: [...(v.lint || []), ...Object.values(v.audit || {}).flat()] })}</details>
    <iframe id="sFrame" sandbox="" title="Resume preview" style="width:100%;height:640px;border:1px solid var(--line);border-radius:8px;background:#fff"></iframe>
    <div class="row"><input id="sRefine" class="grow" placeholder="refine this version: shorter / warmer summary / lead with the Kafka migration" ${STU && STU.ai ? '' : 'disabled title="needs an AI provider"'}><button class="b ghost" onclick="studioRefine(this)" ${STU && STU.ai ? '' : 'disabled'}>Refine</button></div>`;
  $('#sFrame').srcdoc = v.html || '';  // sandbox without scripts: the page cannot reach the token
}
async function studioOpen(ext) { const r = await api(`/api/studio/${encodeURIComponent(SV.vid)}/open`, { file: SV.files[ext] }); toast(r.error ? 'error: ' + r.error : 'opened ' + r.path, r.error ? 'err' : 'ok'); }
async function studioUse(btn) {
  const jid = Number($('#sUseJob').value); btn.disabled = true;
  const r = await api(`/api/studio/${encodeURIComponent(SV.vid)}/use`, { job_id: jid }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(`job #${jid} now uses this version` + (r.coverage && r.coverage.after ? ` (JD coverage ${r.coverage.before}% -> ${r.coverage.after}%)` : ''), 'ok'); load();
}
async function studioLook(btn) {
  btn.disabled = true; const r = await api(`/api/studio/${encodeURIComponent(SV.vid)}/default_look`, {}); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('saved as your default look', 'ok'); $('#sLook').innerHTML = ''; SROWS = null; SDIRTY = false; loadStudio();
}
function studioRefine(btn) {
  const t = $('#sRefine').value.trim(); if (!t) return toast('say what to change first', 'err');
  run('studio_build', { request: t, parent: SV.vid, req: studioReq() }, v => { showVersion(v); loadStudio(); toast('refined version built', 'ok'); }, btn);
}
/* ---- document viewer (viewer.py): every generated document as paged sheets (Letter / A4, your margins, page breaks
   as printed), the PDF headless Edge prints, a Word-layout preview, the exact TXT / MD, compare, the formatting panel
   (live, saved per document; Save as my default look; Reset to template) and section edits. The page sits in a frame
   sandboxed without scripts; this page lays its blocks out into sheets and handles clicks on its headings ---- */
let VW = null;  // {ref, opts, text (edited, else null), parts, tab, cmp, data (last /api/view), t (debounce), pdf, rows, ready}
const VW_DOCS = ['resume.md', 'cover_letter.md', 'form_answers.md', 'interview_prep.md', 'research.md', 'offer.md', 'mock_interview.md'];
const VW_LETTER = ['letter', 'counter'];
const VW_LOOK = [['template', 'template'], ['font', 'font'], ['size', 'base size (pt)', 0.5], ['heading_size', 'heading size (x base)', 0.05],
  ['accent', 'accent'], ['margins', 'margins (in)', 0.05], ['line_spacing', 'line spacing', 0.05], ['para_spacing', 'paragraph spacing (pt)', 1],
  ['paper', 'page size'], ['pages', 'page limit (0: none)'], ['density', 'density'], ['date_format', 'dates'], ['bullet', 'bullets'], ['contact_layout', 'contact line'], ['heading_case', 'headings']];
async function openViewer(ref) {
  if (VW && VW.text !== null && !confirm('Drop your unsaved text edits in the viewer?')) return;
  VW = { ref, opts: null, text: null, parts: [], tab: 'preview', cmp: null, data: null, t: null, pdf: null, rows: [], ready: false, focus: VW ? VW.focus : document.activeElement };
  $('#vwFmt').innerHTML = $('#vwEdit').innerHTML = $('#vwText').textContent = $('#vwDiff').textContent = '';
  $('#vwFrame2').hidden = true;
  if (!(await vwLoad(false))) { VW = null; return; }
  $('#vwDl').innerHTML = VW.data.formats.map(f => `<button class="b ghost sm" onclick="vwDownload('${f}',this)" aria-label="Download ${f.toUpperCase()}">${f.toUpperCase()}</button>`).join('');
  $('#viewer').hidden = false; document.body.classList.add('vwopen');
  vwTab('preview'); vwSide('fmt'); $('#vwClose').focus();
}
function closeViewer() {
  if (!VW) return;
  if (VW.text !== null && VW.data.save && !confirm('Close the viewer and drop your unsaved text edits?')) return;
  if (VW.pdf) URL.revokeObjectURL(VW.pdf);
  clearTimeout(VW.t);
  const back = VW.focus; VW = null;
  $('#viewer').hidden = true; document.body.classList.remove('vwopen'); $('#vwFrame').srcdoc = ''; $('#vwFrame2').srcdoc = ''; $('#vwPdf').removeAttribute('src');
  if (back && back.isConnected) back.focus();
}
async function vwLoad(save) {
  const body = { ref: VW.ref, save };
  if (VW.opts) body.opts = VW.opts;
  if (VW.text !== null) body.text = VW.text;
  if (VW.cmp) body.compare = VW.cmp;
  const me = VW, r = await api('/api/view', body);
  if (VW !== me) return false;
  if (r.error) { toast('error: ' + r.error, 'err'); return false; }
  const first = !VW.data;
  VW.data = r; VW.opts = JSON.parse(JSON.stringify(r.opts || {})); VW.ready = false;
  $('#vwTitle').textContent = r.title;
  const ds = $('#vwDoc'); ds.hidden = !r.docs.length;
  ds.innerHTML = r.docs.map(d => `<option value="${esc(d.name)}" ${VW.ref.name === d.name ? 'selected' : ''}>${esc(d.name)}</option>`).join('');
  if (first) $('#vwCmp').innerHTML = '<option value="">nothing</option>' + r.compare.map((c, i) => `<option value="${i}">${esc(c.label)}</option>`).join('');
  if (first) vwBuildFmt();
  if (VW.text === null) vwBuildEdit();
  vwGuards(r.guards);
  $('#vwFrame').srcdoc = r.html;  // its load event lays it out into sheets
  $('#vwFrame2').hidden = !r.other; $('#vwDiff').textContent = r.other ? `${r.other.title} (right) -> this document: ${r.diff.join(' · ')}` : '';
  if (r.other) $('#vwFrame2').srcdoc = r.other.html;
  if (VW.tab === 'pdf') vwPdfLoad(); else if (VW.tab === 'txt' || VW.tab === 'md') vwTextShow();
  return true;
}
function vwSoon(save, rebuild) {  // the live preview: one request after you stop changing things for a moment
  clearTimeout(VW.t);
  VW.t = setTimeout(async () => { if (!VW) return; VW.t = null; await vwLoad(save); if (rebuild && VW) vwBuildFmt(); }, 300);
}
function vwPaginate(fr, look, limit) {  // the page's blocks into Letter / A4 sheets; returns the page count
  const d = fr.contentDocument; if (!d || !d.body || !d.body.children.length) return 0;
  const W = look.paper === 'a4' ? 8.27 : 8.5, H = look.paper === 'a4' ? 11.69 : 11, m = look.margins;
  const css = d.createElement('style');
  css.textContent = `@media screen{html{background:#e7e9ee}body{max-width:none;margin:0;padding:12px 0}
    .sheet{position:relative;width:${W}in;height:${H}in;padding:${m}in;box-sizing:border-box;background:#fff;margin:0 auto 4px;box-shadow:0 1px 4px rgba(0,0,0,.3)}
    .sheet>.pg{height:100%;overflow:hidden}.pgno{text-align:center;font:11px Arial,sans-serif;color:#555;margin:0 0 14px}
    .sheet.over{outline:3px solid #c0392b}.pgno.over{color:#c0392b;font-weight:bold}h1,h2{cursor:pointer}a{pointer-events:none}}
    @media print{.pgno{display:none}.sheet{width:auto;height:auto;padding:0;margin:0;box-shadow:none;outline:0;break-after:page}
    .sheet:last-of-type{break-after:auto}.sheet>.pg{height:auto;overflow:visible}body{zoom:1!important}}`;
  d.head.appendChild(css);
  const nodes = [...d.body.children]; d.body.textContent = '';
  let pg = null, carried = 0;
  const sheet = () => { const s = d.createElement('div'); s.className = 'sheet'; pg = d.createElement('div'); pg.className = 'pg'; s.appendChild(pg); d.body.appendChild(s); carried = 0; };
  const fits = () => pg.scrollHeight <= pg.clientHeight + 1;
  const place = el => {
    pg.appendChild(el); if (fits()) return;
    if (el.tagName === 'UL' && el.children.length > 1) {  // a list breaks between its bullets
      const rest = d.createElement('ul');
      while (!fits() && el.children.length > 1) rest.prepend(el.lastElementChild);
      if (fits()) { sheet(); place(rest); return; }
      el.append(...rest.children);
    }
    if (pg.children.length - carried <= 1) return;  // alone on its sheet: larger than a page, so it is cut off
    el.remove();
    const carry = [];  // a heading never ends a sheet: it moves on with what follows it
    while (pg.children.length > 1 && /^H[1-3]$/.test(pg.lastElementChild.tagName)) carry.unshift(pg.removeChild(pg.lastElementChild));
    sheet(); carry.forEach(c => pg.appendChild(c)); carried = carry.length; place(el);
  };
  sheet(); nodes.forEach(place);
  const sheets = [...d.querySelectorAll('.sheet')], n = sheets.length;
  sheets.forEach((s, i) => {
    const over = limit && i >= limit, no = d.createElement('div');
    no.className = 'pgno' + (over ? ' over' : ''); no.textContent = `Page ${i + 1} of ${n}` + (over ? ` · over the ${limit}-page limit` : '');
    s.classList.toggle('over', !!over); s.after(no);
  });
  return n;
}
function vwFrameLoaded(second) {
  const fr = $(second ? '#vwFrame2' : '#vwFrame');
  if (!VW || !VW.data || (second && !VW.data.other)) return;
  const n = vwPaginate(fr, second ? VW.data.other.look : VW.data.look, second ? 0 : VW.data.limit);
  if (!second) {
    VW.pages = n;
    fr.contentDocument?.querySelectorAll('h1, h2').forEach(h => h.addEventListener('click', () => vwJump(h.tagName === 'H1' ? '' : h.textContent)));
    vwPagesText(); VW.ready = true;
  }
  vwZoomAll();
}
$('#vwFrame').addEventListener('load', () => vwFrameLoaded(false));
$('#vwFrame2').addEventListener('load', () => vwFrameLoaded(true));
window.addEventListener('resize', () => { if (VW && VW.data) vwZoomAll(); });
function vwPagesText() {
  const n = VW.pages || 0, lim = VW.data.limit, over = lim && n > lim;
  $('#vwPages').innerHTML = `${n} page${n === 1 ? '' : 's'}` + (over ? ` <span class="pill warn" id="vwOver">over the ${lim}-page limit</span>` : '')
    + (VW.pdfPages ? ` · PDF: ${VW.pdfPages} page${VW.pdfPages === 1 ? '' : 's'}` : '');
}
function vwZoomAll() {
  const v = $('#vwZoom').value;
  [['#vwFrame', VW.data.look], ['#vwFrame2', VW.data.other && VW.data.other.look]].forEach(([s, look]) => {
    const fr = $(s), d = fr.contentDocument; if (fr.hidden || !look || !d || !d.body) return;
    const W = (look.paper === 'a4' ? 8.27 : 8.5) * 96, H = (look.paper === 'a4' ? 11.69 : 11) * 96, fw = (fr.clientWidth - 28) / W;
    const z = v === 'width' ? fw : v === 'page' ? Math.min(fw, (fr.clientHeight - 48) / H) : 1;
    d.body.style.zoom = Math.max(0.15, Math.min(z, 3)).toFixed(3);
  });
}
function vwTab(t) {
  VW.tab = t;
  $$('#vwTabs button').forEach(b => { const on = b.dataset.t === t; b.classList.toggle('on', on); b.setAttribute('aria-pressed', String(on)); });
  const paged = t === 'preview' || t === 'docx', paper = VW.data.look.paper === 'a4' ? 'A4' : 'Letter';
  $('.vwpanes').hidden = !paged; $('#vwPdf').hidden = t !== 'pdf'; $('#vwText').hidden = paged || t === 'pdf';
  $('#vwLabel').textContent = { preview: `Paged as printed: ${paper} sheets with your margins. Click a heading to edit that section.`,
    docx: 'Word layout preview; Word may differ slightly. Download DOCX for the file itself.', pdf: 'Printing the PDF…',
    txt: 'The exact text of the TXT download (what an ATS text box gets).', md: 'The exact markdown of the MD download.' }[t];
  if (t === 'pdf') vwPdfLoad(); else if (!paged) vwTextShow(); else vwZoomAll();
}
function vwTextShow() { $('#vwText').textContent = VW.tab === 'md' ? VW.data.md : VW.data.txt; }
function vwSide(w) {
  $('#vwFmt').hidden = w !== 'fmt'; $('#vwEdit').hidden = w !== 'edit';
  $('#vwFmtTab').classList.toggle('on', w === 'fmt'); $('#vwEditTab').classList.toggle('on', w === 'edit');
  $('#vwFmtTab').setAttribute('aria-pressed', String(w === 'fmt')); $('#vwEditTab').setAttribute('aria-pressed', String(w === 'edit'));
}
async function vwFile(fmt, sure) {  // one format's bytes: {blob, name, pages}; null after an error (shown) or a declined confirm
  const body = { ref: VW.ref, fmt, opts: VW.opts, confirm: !!sure };
  if (VW.text !== null) body.text = VW.text;
  const r = await fetch('/api/view/file', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lodestar-Token': TOKEN }, body: JSON.stringify(body) });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    if (r.status === 409 && j.confirm) return confirm(j.error + '\n\nExport anyway?') ? vwFile(fmt, true) : null;
    toast('error: ' + (j.error || 'HTTP ' + r.status), 'err'); return null;
  }
  const name = (/filename="([^"]+)"/.exec(r.headers.get('Content-Disposition') || '') || [])[1] || 'document.' + fmt;
  return { blob: await r.blob(), name, pages: Number(r.headers.get('X-Pages')) || null };
}
async function vwDownload(fmt, btn) {
  btn.disabled = true;
  try {
    const f = await vwFile(fmt); if (!f) return;
    const a = document.createElement('a'); a.href = URL.createObjectURL(f.blob); a.download = f.name;
    document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    toast('downloaded ' + f.name, 'ok');
  } finally { btn.disabled = false; }
}
async function vwPdfLoad() {
  const me = VW, seq = VW.seq = (VW.seq || 0) + 1;
  $('#vwLabel').textContent = 'Printing the PDF…';
  const f = await vwFile('pdf', true);
  if (VW !== me || seq !== VW.seq) return;
  if (!f) { $('#vwLabel').textContent = 'No PDF (see the message): the Preview tab shows the same page.'; return; }
  if (VW.pdf) URL.revokeObjectURL(VW.pdf);
  VW.pdf = URL.createObjectURL(f.blob); VW.pdfPages = f.pages; $('#vwPdf').src = VW.pdf; vwPagesText();
  $('#vwLabel').textContent = `The PDF as printed${VW.data.engine ? ' by ' + VW.data.engine : ''}: ${f.name}${f.pages ? ', ' + f.pages + ' page' + (f.pages === 1 ? '' : 's') : ''}`;
}
function vwPrint() { $('#vwFrame').contentWindow.print(); }  // the sheets, with the page's own @page size and margins
async function vwOpen(btn, sure) {  // an export to exports/: the fact guard asks first (409 confirm), like a download
  const body = { ref: VW.ref, fmt: VW.tab === 'pdf' ? 'pdf' : VW.tab === 'docx' ? 'docx' : 'html', opts: VW.opts, confirm: !!sure };
  if (VW.text !== null) body.text = VW.text;
  btn.disabled = true; const r = await api('/api/view/open', body); btn.disabled = false;
  if (r.confirm) return confirm(r.error + '\n\nExport anyway?') ? vwOpen(btn, true) : null;
  toast(r.error ? 'error: ' + r.error : 'opened ' + r.path, r.error ? 'err' : 'ok');
}
function vwCompare(i) { VW.cmp = i === '' ? null : VW.data.compare[Number(i)].ref; vwLoad(false); }
function vwPickDoc(name) { openViewer({ type: 'job', id: VW.ref.id, name }); }
function vwGuards(g) {
  $('#vwGuards').innerHTML = (g.blocked ? `<div class="warnbox">${esc(g.blocked)}</div>` : '')
    + (g.facts || []).map(x => `<div class="warnbox">not in your profile: ${esc(x)}</div>`).join('') + (g.personal || []).map(x => `<div class="warnbox">${esc(x)}</div>`).join('');
}
function vwBuildFmt() {
  const d = VW.data, c = d.choices, L = d.look;
  const sel = (k, label) => `<label class="fld">${label}<select id="vw_${k}" onchange="vwSet('${k}',this.value)">${c[k].map(x => `<option value="${esc(x)}" ${String(L[k]) === String(x) ? 'selected' : ''}>${esc(x)}</option>`).join('')}</select></label>`;
  const num = (k, label, step) => `<label class="fld">${label}<input id="vw_${k}" type="number" min="${c.ranges[k][0]}" max="${c.ranges[k][1]}" step="${step}" value="${esc(L[k] ?? '')}" ${k === 'para_spacing' ? 'placeholder="from density"' : ''} oninput="vwNum(this,'${k}')"></label>`;
  const named = Object.entries(c.accent).find(([, hex]) => hex.toUpperCase() === String(L.accent).toUpperCase());
  const accent = `<label class="fld">accent<span class="row"><select id="vw_accent" onchange="vwAccent()">${Object.keys(c.accent).filter(k => k !== 'grey').map(k => `<option ${named && named[0] === k ? 'selected' : ''}>${k}</option>`).join('')}<option value="custom" ${named ? '' : 'selected'}>custom</option></select><input type="color" id="vw_accentC" aria-label="Custom accent colour" value="${esc(String(L.accent).toLowerCase())}" oninput="$('#vw_accent').value='custom';vwAccent()"></span></label>`;
  const lt = VW.opts.letter || {};
  $('#vwFmt').innerHTML = VW_LOOK.map(([k, label, step]) => k === 'accent' ? accent : step ? num(k, label, step) : sel(k, label)).join('')
    + (d.sections.length ? '<h4>Sections <span class="muted">(drag, or the arrows; untick to hide)</span></h4><div class="vwrows" id="vwRows"></div>' : '')
    + (VW_LETTER.includes(d.kind) ? `<h4>Letter</h4><label class="muted"><input type="checkbox" id="vwLDate" ${lt.date === false ? '' : 'checked'} onchange="vwLetter()"> date line</label>
      <label class="fld">recipient block (blank: as written)<textarea id="vwLRec" rows="3" oninput="vwLetter()">${esc(lt.recipient || '')}</textarea></label>
      <label class="fld">signature (blank: as written)<textarea id="vwLSig" rows="2" oninput="vwLetter()">${esc(lt.signature || '')}</textarea></label>` : '')
    + `<div class="row"><button class="b sm" onclick="vwSaveLook(this)">Save as my default look</button><button class="b ghost sm" onclick="vwReset()">Reset to template</button></div>
      <div class="muted">Changes apply to this document and are kept for it. The default look is where every document starts (studio versions, the master resume, letters, notes).</div>`;
  vwRowsRender();
}
function vwSet(k, v) {
  if (k === 'template') VW.opts.look = { template: v };  // a template resets this document's other look choices
  else { VW.opts.look = VW.opts.look || {}; if (v === '' || v == null) delete VW.opts.look[k]; else VW.opts.look[k] = v; }
  vwSoon(true, k === 'template');
}
function vwNum(el, k) {  // half-typed numbers wait; a value in range goes live
  if (el.value === '' && k === 'para_spacing') return vwSet(k, '');
  const v = el.validity; if (el.value === '' || v.badInput || v.rangeUnderflow || v.rangeOverflow) return;
  vwSet(k, Number(el.value));
}
function vwAccent() { const s = $('#vw_accent').value; vwSet('accent', s === 'custom' ? $('#vw_accentC').value : s); }
function vwLetter() { VW.opts.letter = { date: $('#vwLDate').checked, recipient: $('#vwLRec').value, signature: $('#vwLSig').value }; vwSoon(true); }
function vwRowsRender() {
  const el = $('#vwRows'); if (!el) return;
  const all = VW.data.sections, hide = new Set(VW.opts.hide || []), order = (VW.opts.order || []).filter(t => all.includes(t));
  VW.rows = [...order, ...all.filter(t => !order.includes(t))];
  el.innerHTML = VW.rows.map((t, i) => `<div class="row" draggable="true" data-i="${i}"><span class="grip" aria-hidden="true">⠿</span><label class="muted grow"><input type="checkbox" ${hide.has(t) ? '' : 'checked'} onchange="vwShowSec(${i},this.checked)"> ${esc(t)}</label>
    <button class="b ghost sm" aria-label="move ${esc(t)} up" onclick="vwMove(${i},-1)" ${i ? '' : 'disabled'}>↑</button><button class="b ghost sm" aria-label="move ${esc(t)} down" onclick="vwMove(${i},1)" ${i < VW.rows.length - 1 ? '' : 'disabled'}>↓</button></div>`).join('');
  $$('#vwRows .row').forEach(r => {
    r.addEventListener('dragstart', e => { e.dataTransfer.setData('text/plain', r.dataset.i); r.classList.add('drag'); });
    r.addEventListener('dragend', () => r.classList.remove('drag'));
    r.addEventListener('dragover', e => e.preventDefault());
    r.addEventListener('drop', e => { e.preventDefault(); vwDrop(Number(e.dataTransfer.getData('text/plain')), Number(r.dataset.i)); });
  });
}
function vwDrop(from, to) {
  if (from === to || !(from >= 0) || !(to >= 0)) return;
  const rows = [...VW.rows], [x] = rows.splice(from, 1); rows.splice(to, 0, x);
  VW.opts.order = rows; vwRowsRender(); vwSoon(true);
}
function vwMove(i, dir) {
  const j = i + dir; if (j < 0 || j >= VW.rows.length) return;
  vwDrop(i, j); $$('#vwRows .row')[j]?.querySelector(`button[aria-label$="${dir < 0 ? 'up' : 'down'}"]:not([disabled])`)?.focus();
}
function vwShowSec(i, on) { const h = new Set(VW.opts.hide || []); if (on) h.delete(VW.rows[i]); else h.add(VW.rows[i]); VW.opts.hide = [...h]; vwSoon(true); }
async function vwSaveLook(btn) {
  const L = VW.data.look, value = Object.fromEntries(VW_LOOK.map(([k]) => [k, L[k]]).filter(([k, v]) => k !== 'pages' && v !== undefined && v !== null && v !== ''));
  btn.disabled = true; const r = await api('/api/prefs', { key: 'resume_look', value }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  VW.opts.look = {}; await vwLoad(true); if (VW) vwBuildFmt();
  toast('saved as your default look: every document starts from it', 'ok');
}
async function vwReset() {
  VW.opts = { look: { template: VW.data.look.template } };
  await vwLoad(true); if (VW) vwBuildFmt();
  toast('back to the ' + VW.data.look.template + ' template for this document', 'ok');
}
function vwParts(md) {  // the text cut before each '## ' heading: one editor per section (a letter is one part)
  const out = [[]];
  md.split('\n').forEach(ln => { if (/^##\s/.test(ln) && out[out.length - 1].some(x => x.trim())) out.push([]); out[out.length - 1].push(ln); });
  return out.map(p => p.join('\n'));
}
function vwBuildEdit() {
  const d = VW.data, parts = VW.parts = vwParts(d.md);
  $('#vwEdit').innerHTML = `<div class="muted">${d.save ? 'Save document keeps your edits (the old version goes to history/).' : 'Edits change what you preview and export here; the document itself is not changed.'} Every export re-runs the salary-floor guard${d.kind === 'resume' ? ' and checks changed lines against your profile' : ''}.</div>`
    + parts.map((p, i) => { const m = /^##\s+(.*)/.exec(p), t = m ? m[1].trim() : VW_LETTER.includes(d.kind) ? 'Letter' : i ? 'Text' : 'Header';
      return `<div class="vwsec" data-title="${esc(i ? t : '')}"><label class="fld">${esc(t)}<textarea data-i="${i}" rows="${Math.min(14, p.split('\n').length + 1)}" oninput="vwEditPart(${i},this.value)">${esc(p)}</textarea></label></div>`; }).join('')
    + `<div class="row">${d.save ? '<button class="b sm" onclick="vwSaveText(this)">Save document</button>' : ''}<button class="b ghost sm" onclick="vwDiscard()">Discard edits</button></div>`;
}
function vwEditPart(i, v) { VW.parts[i] = v; VW.text = VW.parts.join('\n'); vwSoon(false); }
function vwJump(title) {  // a click on a heading in the page: its section's editor
  vwSide('edit');
  const box = $$('#vwEdit .vwsec').find(s => s.dataset.title.trim().toLowerCase() === title.trim().toLowerCase()) || $('#vwEdit .vwsec');
  const ta = box && box.querySelector('textarea'); if (ta) { ta.scrollIntoView({ block: 'nearest' }); ta.focus(); }
}
async function vwSaveText(btn, sure) {  // the fact guard asks first (409 confirm), like an export
  btn.disabled = true; const r = await api('/api/view/save', { ref: VW.ref, text: VW.text ?? VW.data.md, confirm: !!sure }); btn.disabled = false;
  if (r.confirm) return confirm(r.error + '\n\nSave anyway? Mail and the application packet will use this text.') ? vwSaveText(btn, true) : null;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast('saved ' + VW.ref.name + (r.facts.length ? ' (you confirmed ' + r.facts.length + ' line(s) your profile does not support)' : ''), r.facts.length ? '' : 'ok');
  VW.text = null; await vwLoad(false);
  if (cur && VW && cur.job.id === VW.ref.id) openJob(cur.job.id);
}
function vwDiscard() { VW.text = null; vwLoad(false); }
function vwKey(e) {  // Esc closes, Tab stays inside (aria-modal)
  if (e.key === 'Escape') { e.preventDefault(); closeViewer(); return; }
  if (e.key !== 'Tab') return;
  const f = $$('#viewer ' + FOCUSABLE.split(', ').join(', #viewer ') + ', #viewer iframe').filter(x => x.offsetParent !== null); if (!f.length) return;
  const at = document.activeElement, first = f[0], last = f[f.length - 1];
  if (!$('#viewer').contains(at) || (e.shiftKey && at === first) || (!e.shiftKey && at === last)) { e.preventDefault(); (e.shiftKey ? last : first).focus(); }
}
/* entry points: the drawer's documents, the master card, Insights offers (offer notes, the counter draft), the studio */
function viewDoc() {
  const n = $('#docTabs button.on')?.textContent;
  if (!VW_DOCS.includes(n)) return toast('pick a document tab first (resume.md, cover_letter.md, ...)', 'err');
  openViewer({ type: 'job', id: cur.job.id, name: n });
}
function viewJobDoc(name) {
  if (!(name in cur.docs)) return toast(`no ${name} yet for this job`, 'err');
  openViewer({ type: 'job', id: cur.job.id, name });
}
function viewPacket() {
  const n = VW_DOCS.find(x => x in cur.docs); if (!n) return toast('no documents yet: tailor a resume or write a cover letter first', 'err');
  openViewer({ type: 'job', id: cur.job.id, name: n });
}
function viewOfferNote() { const id = Number($('#ctrJob').value); if (!id) return toast('record an offer first', 'err'); openViewer({ type: 'job', id, name: 'offer.md' }); }
let CTR = null;  // the last counter-offer draft (its job and cited figures: the only figures it may name)
function viewCounter() { if (CTR) openViewer({ type: 'text', kind: 'counter', job: CTR.id, cite: CTR.cite, text: CTR.text, title: 'Counter-offer draft' }); }

/* ---- AI advisor toolbar (advisor.py): Recommend / Apply suggestions / Full AI / Undo AI changes on every tab and card ---- */
// advisor.SCOPES with auto=False / write=None; test_pass19_toolbar keeps these in step with the server
const ADV_NOAUTO = ['searches', 'today', 'insights'], ADV_ADVICE = ['today', 'insights'];
const ADV_NAME = { profile: 'profile.md', bank: 'profile bank', job: 'job details', docs: 'job documents', answers: 'answer bank', stories: 'STAR stories',
  contacts: 'contacts', searches: 'saved searches and watchlist', today: 'today', insights: 'insights', inbox: 'Inbox drafts' };
const ADV = {};  // key (scope_target) -> {scope, target, recs, sel (ticked ids), batch (last one written here), msg, err}; markup carries only the key
let ADV_AI = null, HIST = [];
const NO_AI = 'This needs an AI provider: link an AI key in Setup, or click "Local only (Ollama)" there (local Ollama models count). Nothing was changed.';
function aiBar(scope, target = null) {
  const t = target == null || target === '' ? null : Number(target), k = scope + '_' + (t ?? 0), advice = ADV_ADVICE.includes(scope);
  ADV[k] ||= { scope, target: t, recs: null, sel: new Set(), batch: null, msg: '', err: false };
  const q = `'${k}',this`, need = S && hasAI() ? '' : ' title="needs an AI provider (Setup)"';
  return `<div class="aibar" role="group" aria-label="AI for ${esc(ADV_NAME[scope] || scope)}" data-adv="${k}"><span class="ailbl" aria-hidden="true">✦ AI</span>`
    + `<button class="b ghost sm" onclick="advRecommend(${q})"${need}>Recommend</button>`
    + (advice ? '' : `<button class="b ghost sm" onclick="advApply(${q})">Apply suggestions</button>`)
    + (ADV_NOAUTO.includes(scope) ? '' : `<button class="b ghost sm" onclick="advAuto(${q})"${need}>Full AI</button>`)
    + (advice ? '' : `<button class="b ghost sm" onclick="advUndo(${q})">Undo AI changes</button>`)
    + `</div><div class="advpanel" data-advp="${k}">${advPanel(k)}</div>`;
}
function aiSlots() {  // the tab headers: toolbars and AI help menus
  ADV_AI = hasAI(); $$('[data-adv-slot]').forEach(el => { el.innerHTML = aiBar(el.dataset.advSlot); });
  $$('[data-ai-menu]').forEach(el => { el.innerHTML = aiMenu(el.dataset.aiMenu); });
}
function advDiff(was, now) {  // line diff (LCS) of current -> proposed: removed lines <del>, added <ins>; every line escaped
  const A = String(was ?? '').split('\n'), B = String(now ?? '').split('\n');
  if (A.length * B.length > 160000) return `<del>${esc(was)}</del>\n<ins>${esc(now)}</ins>`;  // ponytail: O(n*m) table, capped
  const L = Array.from({ length: A.length + 1 }, () => new Uint16Array(B.length + 1));
  for (let i = A.length - 1; i >= 0; i--) for (let j = B.length - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out = []; let i = 0, j = 0;
  while (i < A.length || j < B.length) {
    if (i < A.length && j < B.length && A[i] === B[j]) { out.push(`<span>  ${esc(A[i])}</span>`); i++; j++; }
    else if (i < A.length && (j >= B.length || L[i + 1][j] >= L[i][j + 1])) { out.push(`<del>- ${esc(A[i])}</del>`); i++; }
    else { out.push(`<ins>+ ${esc(B[j])}</ins>`); j++; }
  }
  return out.join('\n');
}
function advCard(k, r, i) {
  const open = r.status === 'pending' || r.status === 'approved', pick = open && r.appliable, risk = { high: 'due', medium: 'stale' }[r.risk] || '';
  return `<div class="advcard${r.flags.length ? ' flag' : ''}" data-rec="${Number(r.id)}"><div class="hd">`
    + (pick ? `<label><input type="checkbox" ${ADV[k].sel.has(r.id) ? 'checked' : ''} onchange="advPick('${k}',${i},this.checked)"> <b>${esc(r.label)}</b></label>` : `<b>${esc(r.label)}</b>`)
    + ` <span class="chip">impact ${esc(r.impact)}</span> <span class="chip ${risk}">risk ${esc(r.risk)}</span>`
    + (r.appliable ? '' : ' <span class="chip">advice only</span>')
    + (open ? '' : ` <span class="pill ${r.status === 'applied' ? 'ok' : 'warn'}">${esc(r.status)}</span>${r.note ? ` <span class="muted">${esc(r.note)}</span>` : ''}`) + '</div>'
    + (r.appliable ? `<div class="muted">current → proposed</div><pre class="advdiff">${advDiff(r.current, r.proposed)}</pre>` : `<div class="advtext">${esc(r.proposed)}</div>`)
    + (r.reason ? `<div class="muted">why: ${esc(r.reason)}</div>` : '')
    + (r.flags.length ? `<div class="flagtxt">⚠ ${r.flags.map(f => esc(f)).join('<br>⚠ ')}<br>Apply refuses this one.</div>` : '') + '</div>';
}
function advPanel(k) {
  const a = ADV[k]; if (!a) return '';
  return (a.msg ? `<div class="advmsg${a.err ? ' bad' : ''}" role="status">${esc(a.msg)}</div>` : '') + (a.recs || []).map((r, i) => advCard(k, r, i)).join('')
    + ((a.recs || []).length ? `<div class="row"><button class="b ghost sm" onclick="advClose('${k}')">Close suggestions</button></div>` : '');
}
function advPaint(k) { $$(`[data-advp="${k}"]`).forEach(el => { el.innerHTML = advPanel(k); }); }
function advSay(k, msg, err = false) { ADV[k].msg = msg; ADV[k].err = err; advPaint(k); }
function advPick(k, i, on) { const r = (ADV[k].recs || [])[i]; if (r) { if (on) ADV[k].sel.add(r.id); else ADV[k].sel.delete(r.id); } }
function advClose(k) { Object.assign(ADV[k], { recs: null, sel: new Set(), msg: '', err: false }); advPaint(k); }
function advNeedAI(k) { if (hasAI()) return false; advSay(k, NO_AI, true); return true; }
function advRecommend(k, btn) {
  const a = ADV[k]; if (advNeedAI(k)) return;
  run('advise', { scope: a.scope, target: a.target }, r => advShow(k, r.recommendations), btn, e => advSay(k, e, true));
}
function advShow(k, recs) {  // Recommend's cards (also an appliable AI helper's: Fill STAR from my notes)
  const a = ADV[k]; a.recs = recs; a.sel = new Set(recs.filter(x => x.appliable && !x.flags.length).map(x => x.id));
  const n = recs.length;
  advSay(k, !n ? 'The AI recommends no changes here.' : ADV_ADVICE.includes(a.scope) || !recs.some(x => x.appliable)
    ? `${n} suggestion(s), advice only: nothing here is changed for you.`
    : `${n} suggestion(s). Tick the ones you want, then Apply suggestions. Nothing has changed yet.`);
}
function advDone(k, r, verb) {  // apply / auto result: each card shows what happened to it
  const a = ADV[k], why = Object.fromEntries((r.skipped || []).map(s => [s.id, s.why]));
  (a.recs || []).forEach(x => {
    if (r.applied.includes(x.id)) Object.assign(x, { status: 'applied', note: '' });
    else if (x.id in why) Object.assign(x, { status: /^(changed|gone)/.test(why[x.id]) ? 'stale' : 'not applied', note: why[x.id] });
  });
  a.sel = new Set([...a.sel].filter(id => !r.applied.includes(id) && !(id in why)));
  if (r.batch) a.batch = r.batch;
  const sk = (r.skipped || []).length;
  advSay(k, `${verb} ${r.applied.length} change(s)` + (r.batch ? ` (batch #${r.batch}; Undo AI changes puts them back)` : '') + (sk ? `; ${sk} skipped: ${r.skipped.map(s => s.why).join('; ')}` : '') + '.', !r.applied.length && !!sk);
  advRefresh(a.scope, a.target);
}
async function advApply(k, btn) {
  const a = ADV[k], ids = [...a.sel];
  if (!ids.length) return advSay(k, a.recs ? 'Tick at least one suggestion first.' : 'Click Recommend first: Apply suggestions writes the suggestions you tick.', true);
  btn.disabled = true; const r = await api('/api/advise/apply', { ids }); btn.disabled = false;
  if (r.error) return advSay(k, r.error, true);
  advDone(k, r, 'Applied');
}
const FULL_AI_KEY = 'ls_full_ai_ok';
function advAuto(k, btn) {
  const a = ADV[k]; if (advNeedAI(k)) return;
  let ok = false; try { ok = localStorage.getItem(FULL_AI_KEY) === '1'; } catch (_) { /* storage blocked: ask every time */ }
  if (!ok) {
    if (!confirm(`Full AI for ${ADV_NAME[a.scope]}: one AI call, then every suggestion that passes the checks is written for you (no invented facts or salary floor in employer text, nothing you changed since).\n\nIt never sends mail, submits anything, changes a job's status, adds jobs, or touches settings, automation or the vault.\n\nEvery change is logged: Undo AI changes (here, or Setup > Data) puts it back. Continue?`)) return;
    try { localStorage.setItem(FULL_AI_KEY, '1'); } catch (_) { /* storage blocked */ }
  }
  run('advise_auto', { scope: a.scope, target: a.target }, r => { a.recs = r.recommendations; a.sel = new Set(); advDone(k, r, 'Full AI made'); }, btn, e => advSay(k, e, true));
}
async function advUndo(k, btn) {
  const a = ADV[k]; btn.disabled = true;
  try {
    let b = a.batch;
    if (!b) {  // the newest batch that still holds a change of this toolbar's scope and target
      const h = await api('/api/advise/history?limit=50');
      b = ((h.batches || []).find(x => x.changes.some(c => !c.undone_at && c.scope === a.scope && (c.target ?? null) === a.target)) || {}).batch;
    }
    if (!b) return advSay(k, 'No AI changes to undo here.', true);
    const r = await api('/api/advise/undo', { batch: b });
    if (r.error) return advSay(k, r.error, true);
    a.batch = null; a.recs = null; a.sel = new Set();
    advSay(k, `Undid ${r.undone} change(s) of batch #${r.batch}` + (r.skipped.length ? `; kept ${r.skipped.length}: ${r.skipped.map(s => s.field + ' (' + s.why + ')').join('; ')}` : '') + '.', !r.undone);
    advRefresh(a.scope, a.target);
  } finally { btn.disabled = false; }
}
function advRefresh(scope, target) {  // the component the change touched shows it (answers, stories, watches, Inbox: load())
  load();
  if (scope === 'profile') {
    if ($('#pText').value === PROFILE_LOADED) loadProfile();
    else toast('profile.md changed: your unsaved text in the editor is kept, but Save is refused until the editor matches the file. Copy your text out and reload, or click Undo AI changes and Save works again', 'err');
  }
  if (scope === 'profile' || scope === 'bank') { loadBank(); loadMaster(); }
  if ((scope === 'job' || scope === 'docs') && cur && cur.job.id === target) {  // a re-render would drop typed, unsaved text
    if (drawerDirty()) toast('The AI change is saved. The drawer keeps your unsaved text: save it, then reopen the job to see the change', 'err');
    else openJob(target);
  }
  if (scope === 'contacts') { loadContacts(); if (CT && (target == null || CT.contact.id === target)) openContact(CT.contact.id); }
  if ($('#setup').classList.contains('on')) loadAiHistory();
}
async function loadAiHistory() {  // Setup > Data: recent AI change batches, each with its diffs and an Undo
  const r = await api('/api/advise/history?limit=30'); if (r.error) return toast('error: ' + r.error, 'err');
  HIST = r.batches;
  $('#aiHist').innerHTML = HIST.map((b, i) => `<details class="aihist" data-batch="${Number(b.batch)}"><summary>#${Number(b.batch)} · ${b.mode === 'auto' ? 'Full AI' : 'Apply suggestions'} · ${esc(localTs(b.ts, 16))} · ${b.changes.length} change(s) · ${esc([...new Set(b.changes.map(c => ADV_NAME[c.scope] || c.scope))].join(', '))}${b.undone ? ' <span class="pill">undone</span>' : ''}</summary>`
    + b.changes.map(c => `<div><b>${esc(c.label || c.field)}</b>${c.undone_at ? ' <span class="muted">undone</span>' : ''}<pre class="advdiff">${advDiff(c.before, c.after)}</pre></div>`).join('')
    + (b.undone ? '' : `<button class="b ghost sm" onclick="histUndo(${i},this)">Undo this batch</button>`) + '</details>').join('')
    || '<div class="muted">No AI changes yet. Apply suggestions and Full AI log every change here, and each batch can be undone.</div>';
}
async function histUndo(i, btn) {
  const b = HIST[i]; if (!b) return; btn.disabled = true;
  const r = await api('/api/advise/undo', { batch: b.batch }); btn.disabled = false;
  if (r.error) return toast('error: ' + r.error, 'err');
  toast(`undid ${r.undone} change(s) of batch #${r.batch}` + (r.skipped.length ? `; kept ${r.skipped.length} you changed since` : ''), r.undone ? 'ok' : 'err');
  new Set(b.changes.map(c => c.scope + '|' + (c.target ?? ''))).forEach(s => { const [sc, t] = s.split('|'); advRefresh(sc, t === '' ? null : Number(t)); });
  loadAiHistory();
}

/* ---- AI help menus (advisor.HELPERS): a few more AI helpers per component, folded under "✦ AI help". One AI call each;
   the answer is a card you read (nothing changes). Fill STAR from my notes gives the story's toolbar suggestion cards,
   which only Apply suggestions writes. ---- */
const AIM_NAME = { board: 'the board', job: 'this job', contacts: 'contacts', contact: 'this contact', stories: 'this story',
  insights: 'insights', search: 'search', monitor: 'monitor', setup: 'settings' };
const AIH = {};  // key (where_target) -> {where, target, title, text, msg, err}; markup carries the key and the helper name only
function aiMenu(where, target = null) {
  const hs = Object.entries((S && S.ai_helpers) || {}).filter(([, h]) => h.where === where); if (!hs.length) return '';
  const t = target == null || target === '' ? null : Number(target), k = where + '_' + (t ?? 0);
  AIH[k] ||= { where, target: t, title: '', text: '', msg: '', err: false };
  const need = hasAI() ? '' : ' title="needs an AI provider (Setup)"';
  const topic = where === 'setup' ? `<select class="aitopic" aria-label="Setting to explain">${(S.ai_topics || []).map(([v, l]) => `<option value="${esc(v)}">${esc(l)}</option>`).join('')}</select>` : '';
  return `<details class="aimenu" data-aim="${k}"><summary>✦ AI help</summary><div class="row" role="group" aria-label="AI help for ${esc(AIM_NAME[where] || where)}">${topic}`
    + hs.map(([n, h]) => `<button class="b ghost sm" data-h="${esc(n)}" onclick="aiHelp('${k}',this)"${need}>${esc(h.label)}</button>`).join('')
    + `</div></details><div class="aihelp" data-aimp="${k}">${aiHelpCard(k)}</div>`;
}
function aiHelpCard(k) {
  const a = AIH[k]; if (!a) return '';
  return (a.msg ? `<div class="advmsg${a.err ? ' bad' : ''}" role="status">${esc(a.msg)}</div>` : '')
    + (a.text ? `<div class="advcard aiout"><div class="hd"><b>${esc(a.title)}</b> <span class="chip">AI help: nothing was changed</span></div><div class="advtext">${esc(a.text)}</div>`
      + `<div class="row"><button class="b ghost sm" onclick="aiHelpClose('${k}')">Close</button></div></div>` : '');
}
function aiHelpPaint(k) { $$(`[data-aimp="${k}"]`).forEach(el => { el.innerHTML = aiHelpCard(k); }); }
function aiHelpSay(k, msg, err = false) { Object.assign(AIH[k], { msg, err }); aiHelpPaint(k); }
function aiHelpClose(k) { Object.assign(AIH[k], { title: '', text: '', msg: '', err: false }); aiHelpPaint(k); }
function aiHelp(k, btn) {
  const a = AIH[k], helper = btn.dataset.h;
  if (!hasAI()) return aiHelpSay(k, NO_AI, true);
  const target = a.where === 'setup' ? btn.closest('.aimenu').querySelector('.aitopic').value : a.target;
  run('ai_help', { helper, target }, r => {
    if (!r.recommendations) { Object.assign(a, { title: r.title, text: r.text, msg: '', err: false }); return aiHelpPaint(k); }
    const ak = r.scope + '_' + (r.target ?? 0);  // the card's own AI toolbar shows them: tick, then Apply suggestions
    ADV[ak] ||= { scope: r.scope, target: r.target, recs: null, sel: new Set(), batch: null, msg: '', err: false };
    advShow(ak, r.recommendations);
    aiHelpSay(k, r.recommendations.length ? 'Suggestions are in the AI panel above: tick the ones you want, then Apply suggestions.' : 'The AI suggests no changes.');
  }, btn, e => aiHelpSay(k, e, true));
}
/* ---- restore from backup (extras.restore): Setup > Data picks a zip from the backups folder; the server re-checks everything ---- */
async function restoreLoad() {
  const r = await api('/api/backups'); if (r.error) return toast('error: ' + r.error, 'err');
  const sel = $('#rsPick'), keep = sel.value;
  sel.innerHTML = r.backups.map(b => `<option value="${esc(b.name)}">${esc(b.name)} · ${esc(b.when)} · ${esc((b.size / 1e6).toFixed(1))} MB</option>`).join('')
    || '<option value="">no backups yet: Backup now makes one</option>';
  if (r.backups.some(b => b.name === keep)) sel.value = keep;
}
function restoreRun(btn) {
  const name = $('#rsPick').value; if (!name) return toast('no backup to restore: Backup now makes one', 'err');
  if (!confirm(`Restore ${name}?\n\nYour data folder (profile, tracker, settings, answers, documents) goes back to that backup, and files made since are removed. A safety backup of what is there now is taken first (before-restore-….zip in backups).\n\nKeyring secrets (AI keys, mail sign-in) and paired browsers are not in backups: they stay as they are.`)) return;
  $('#rsOut').textContent = 'Restoring…';
  run('restore', { name }, r => {
    const c = r.counts || {};
    $('#rsOut').innerHTML = `<div id="rsDone"><b>Restored ${Number(r.restored)} file(s) from ${esc(r.from)}</b>: ${Number(c.jobs)} jobs, ${Number(c.contacts)} contacts, ${Number(c.answers)} answers, ${Number(c.events)} events; removed ${Number(r.removed)} file(s) made since.`
      + `<div class="muted">Safety backup of what was there: ${esc(r.safety_backup)}</div>`
      + (r.skipped && r.skipped.length ? `<div class="muted">Not restored (never part of a backup): ${esc(r.skipped.join(', '))}</div>` : '')
      + `<div class="muted">${esc(r.note)}</div></div>`;
    toast('backup restored', 'ok'); restoreLoad(); loadProfile(); loadBank(); loadMaster();
  }, btn, e => { $('#rsOut').innerHTML = `<div class="flagtxt" id="rsErr">${esc(e)}</div>`; });
}

/* ---- command palette: Ctrl+K / Cmd+K. A dialog with a combobox over a listbox (aria-activedescendant): type to filter
   (fuzzy: the letters in order), arrows move, Enter runs, Esc closes and gives focus back. Every label is escaped. ---- */
let PAL = null;  // {items, shown, at, back}: the palette while it is open
const PAL_KIND = { action: 'Action', tab: 'Tab', job: 'Job', contact: 'Contact', doc: 'Document', setting: 'Setting' };
function palTab(tab) { go(tab); $(`nav button[data-tab="${tab}"]`).focus(); }
function palFocus(el) { if (!el) return; el.scrollIntoView({ block: 'center' }); el.focus(); }
function palRecommend() {  // the first AI toolbar on the open tab, as if you clicked its Recommend
  const b = $$('main section.on [data-adv-slot] .aibar button').find(x => x.textContent === 'Recommend');
  if (!b) return toast('This tab has no AI recommendations (Board, Inbox, Contacts, Search, Monitor, Answers, Insights and Profile do)', 'err');
  palFocus(b); b.click();
}
function palToday() {
  palTab('board'); const t = $('#today');
  if (t.style.display === 'none') return toast('Nothing is due today', 'ok');
  t.tabIndex = -1; palFocus(t);
}
function palBase() {
  const label = b => [...b.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim();
  const items = [
    { kind: 'action', label: 'Add job', run: () => { palTab('board'); $('#nCo').focus(); } },
    { kind: 'action', label: 'Check email', run: () => { palFocus($('#topEmail')); $('#topEmail').click(); } },  // focus stays on what ran
    { kind: 'action', label: 'Run watches', run: () => { palFocus($('#topWatches')); $('#topWatches').click(); } },
    { kind: 'action', label: 'Recommend on this tab', run: palRecommend },
    { kind: 'action', label: 'Open Today', run: palToday },
    ...$$('nav button[data-tab]').map(b => ({ kind: 'tab', label: 'Go to ' + label(b), run: () => palTab(b.dataset.tab) })),
    ...(S.jobs || []).map(j => ({ kind: 'job', label: `#${j.id} ${j.company} - ${j.title}`, hint: j.status, run: () => { palTab('board'); openJob(j.id); } })),
    ...$$('#setup .panel > h3').map(h => ({ kind: 'setting', label: h.textContent, hint: 'Setup', run: () => { go('setup'); palFocus(h.parentElement.querySelector(FOCUSABLE)); } })),
  ];
  Object.keys(S.prefs || {}).forEach((k, i) => items.push({ kind: 'setting', label: ((S.pref_help || {})[k] || [k])[0], hint: 'Tools > Preferences',
    run: () => { go('tools'); palFocus($(`#prefs [aria-labelledby="pl${i}"]`)); } }));
  return items;
}
function palScore(q, s) {  // the query's letters in order; runs and word starts score higher; -1 = no match
  s = s.toLowerCase(); let from = 0, prev = -2, score = 0;
  for (const ch of q) {
    const j = s.indexOf(ch, from); if (j < 0) return -1;
    score += (j === prev + 1 ? 3 : 1) + (j === 0 || /[\s#\-(>·]/.test(s[j - 1]) ? 2 : 0); prev = j; from = j + 1;
  }
  return score - s.length / 1000;
}
function palRender() {
  const q = $('#palQ').value.trim().toLowerCase().replace(/\s+/g, ' ');
  PAL.shown = (q ? PAL.items.map(it => [palScore(q, it.label), it]).filter(x => x[0] >= 0).sort((a, b) => b[0] - a[0]).map(x => x[1])
    : PAL.items.filter(it => it.kind === 'action' || it.kind === 'tab')).slice(0, 50);
  $('#palList').innerHTML = PAL.shown.map((it, i) => `<li role="option" id="palO${i}" aria-selected="false" onmousedown="event.preventDefault()" onclick="palRun(${i})">`
    + `<span class="palk">${esc(PAL_KIND[it.kind])}</span>${esc(it.label)}${it.hint ? ` <span class="muted">${esc(it.hint)}</span>` : ''}</li>`).join('');
  $('#palN').textContent = PAL.shown.length ? `${PAL.shown.length} result${PAL.shown.length === 1 ? '' : 's'}` : 'No matches';
  palAt(PAL.shown.length ? Math.min(Math.max(PAL.at, 0), PAL.shown.length - 1) : -1);
}
function palAt(i) {
  PAL.at = i;
  $$('#palList [role=option]').forEach((o, k) => { o.setAttribute('aria-selected', String(k === i)); o.classList.toggle('on', k === i); });
  if (i < 0) return $('#palQ').removeAttribute('aria-activedescendant');
  $('#palQ').setAttribute('aria-activedescendant', 'palO' + i); $('#palO' + i).scrollIntoView({ block: 'nearest' });
}
function palAdd(list) { if (PAL) { PAL.items.push(...list); palRender(); } }
function palOpen() {
  if (PAL || !S || !$('#viewer').hidden) return;  // the document viewer is a full-screen dialog of its own
  PAL = { items: palBase(), shown: [], at: 0, back: document.activeElement };
  $('#palQ').value = ''; $('#palette').hidden = false; palRender(); $('#palQ').focus();
  api('/api/contacts').then(r => palAdd((r.contacts || []).map(c => ({ kind: 'contact', label: c.name + (c.company ? ` (${c.company})` : ''),
    run: () => { palTab('contacts'); openContact(c.id); } }))));
  api('/api/docs').then(r => palAdd((r.docs || []).map(d => ({ kind: 'doc', label: d.label, run: () => openViewer(d.ref) }))));
}
function palClose(back = true) {
  if (!PAL) return; const b = PAL.back; PAL = null; $('#palette').hidden = true;
  if (back && b && b.isConnected) b.focus();
}
function palRun(i) { const it = PAL && PAL.shown[i]; if (!it) return; palClose(false); it.run(); }
$('#palQ').addEventListener('input', () => { if (PAL) { PAL.at = 0; palRender(); } });
$('#palette').addEventListener('click', e => { if (e.target.id === 'palette') palClose(); });  // a click beside the box
document.addEventListener('keydown', e => {  // capture phase: before the drawer's and the viewer's own keys
  if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === 'k') {
    e.preventDefault(); e.stopPropagation(); return PAL ? palClose() : palOpen();
  }
  if (!PAL) return;
  e.stopPropagation();  // nothing under the palette reacts while it is open
  const n = PAL.shown.length;
  if (e.key === 'Escape') { e.preventDefault(); palClose(); }
  else if (e.key === 'ArrowDown' && n) { e.preventDefault(); palAt((PAL.at + 1) % n); }
  else if (e.key === 'ArrowUp' && n) { e.preventDefault(); palAt((PAL.at - 1 + n) % n); }
  else if (e.key === 'Enter') { e.preventDefault(); palRun(PAL.at); }
  else if (e.key === 'Tab') e.preventDefault();  // the search box is the dialog's only stop
}, true);
load(); loadProfile(); loadBank(); loadReviews(); loadMaster(); setInterval(load, 60000);

/* ---- Careers (pass 23, careers.py): suggestions by career class, career tracks, track search with coverage ---- */
let CAREERS = null;
async function loadCareers() {
  const r = await api('/api/careers'); CAREERS = r;
  if (!$('#trackTiers').childElementCount)
    $('#trackTiers').innerHTML = Object.entries(r.tiers).filter(([t]) => t !== '6')
      .map(([t, label]) => `<label class="muted"><input type="checkbox" value="${esc(t)}"> ${esc(t)} ${esc(label)}</label>`).join(' ');
  $('#trackList').innerHTML = (r.tracks || []).map(t => `<div class="track-row row">
      <b>${esc(t.label)}</b> <span class="muted">${esc(t.intent.replace('_', ' '))}${t.enabled ? '' : ' (off)'}</span>
      <span class="chips">${t.tiers.map(x => `<span class="chip">${esc(r.tiers[x])}</span>`).join('')}</span>
      <span class="muted grow">searches: ${esc((t.search_titles || t.titles).join(', '))}${t.location ? ' · ' + esc(t.location) : ''}</span>
      <button class="b sm" onclick="trackSearch(${Number(t.id)}, this)">Search live openings</button>
      <button class="b sm ghost" onclick="trackRemove(${Number(t.id)}, this)">Remove</button></div>`).join('')
    || '<p class="muted">No tracks yet. Add any field you want to work in, even one your resume does not show.</p>';
  const err = r.error ? `<div class="warnbox">${esc(r.error)}</div>` : '';
  const sug = r.suggestions || [];
  const bands = Object.entries(r.classes).map(([k, label]) => {
    const g = sug.filter(x => x.cls === k);
    return g.length ? `<div class="panel band"><h3>${esc(label)}</h3>${g.map(x => careerCard(x, sug.indexOf(x))).join('')}</div>` : '';
  }).join('');
  $('#careerSug').innerHTML = err + (r.note ? `<p class="muted">${esc(r.note)}</p>` : '') + bands;
  $('#careerCredit').textContent = (r.meta && r.meta.credit) || '';
}
function careerCard(x, i) {  // i: the suggestion's index, so no page text ever lands inside an onclick
  const list = (head, items) => items && items.length ? `<div><span class="muted">${head}:</span> ${items.map(esc).join('; ')}</div>` : '';
  return `<div class="career-card"><div class="row"><b>${esc(x.title)}</b>
      <span class="chip">${esc(x.tier_label)}</span><span class="chip">${esc(x.cls_label)}</span>
      <span class="muted grow">${esc(x.code)} · ${esc(x.source)}</span>
      <button class="b sm ghost" onclick="careerSearchCode(${Number(i)}, this)">Search live openings</button></div>
    ${x.regulated ? `<div class="warnbox">Licensing: ${esc(x.regulated)}. Lodestar cannot confirm eligibility.</div>` : ''}
    ${list('Why it fits', x.why)}${list('What is missing', x.missing)}${list('What does not transfer', x.not_transfer)}${list('To close the gap', x.close_gap)}</div>`;
}
async function trackAdd(btn) {
  const tiers = $$('#trackTiers input:checked').map(i => Number(i.value));
  const body = { label: $('#trackLabel').value, intent: $('#trackIntent').value, titles: $('#trackTitles').value,
                 location: $('#trackLoc').value, tiers: tiers.length ? tiers : null };
  btn.disabled = true; const r = await api('/api/careers/tracks', body); btn.disabled = false;
  $('#trackErr').textContent = r.error || '';
  if (r.error) return;
  ['#trackLabel', '#trackTitles', '#trackLoc'].forEach(s => $(s).value = ''); $$('#trackTiers input').forEach(i => i.checked = false);
  toast('career track added', 'ok'); loadCareers();
}
async function trackRemove(id, btn) {
  btn.disabled = true; const r = await api(`/api/careers/tracks/${Number(id)}/delete`, {});
  if (r.error) { btn.disabled = false; return toast('error: ' + r.error, 'err'); }
  loadCareers();
}
async function careerSearchCode(i, btn) {  // a suggestion's own search: a resume-led track for that occupation
  const o = (CAREERS.suggestions || [])[i]; if (!o) return;
  const r = await api('/api/careers/tracks', { label: o.title, intent: 'resume_led', codes: [o.code], tiers: [1] });
  if (r.error) return toast('error: ' + r.error, 'err');
  await loadCareers(); trackSearch(r.id, btn);
}
function trackSearch(id, btn) {
  run('careers_search', { track: Number(id) }, renderCareerRes, btn, e => { $('#careerRes').innerHTML = `<div class="warnbox">${esc(e)}</div>`; });
}
function renderCareerRes(r) {
  const c = r.coverage;
  const cov = `<div class="coverage muted">${c.checked ? '' : '<b>Nothing was checked: no job board answered.</b> '}Boards asked: ${esc(c.asked.join(', ') || 'none')} (${c.asked.length} of ${c.total})`
    + (c.failed.length ? ` · could not read: ${esc(c.failed.join('; '))}` : '') + (c.not_ready.length ? ` · need a key: ${esc(c.not_ready.join(', '))}` : '')
    + `. ${esc(c.note)}</div>`;
  const rows = r.results.map(x => `<li class="row"><b>${esc(x.title)}</b> <span>${esc(x.company)}</span> <span class="muted grow">${esc(x.location || '')}</span>
      ${x.url ? `<a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">open</a>` : ''}
      ${x.tracked ? '<span class="muted">on your Board</span>' : x.id ? `<button class="b sm" onclick="trackFit(${Number(x.id)}, this)">Track</button>` : ''}</li>`).join('');
  $('#careerRes').innerHTML = `<div class="panel"><h3>${esc(r.track.label)}: live openings</h3><p class="muted">searched: ${esc(r.titles.join(', '))}</p>`
    + (rows ? `<ul class="career-results">${rows}</ul>` : `<p class="muted">${c.checked ? 'No openings found on the boards asked.' : ''}</p>`) + cov + '</div>';
}
