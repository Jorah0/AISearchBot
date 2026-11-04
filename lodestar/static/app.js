/* Lodestar dashboard. Talks only to the local /api routes; long actions are background tasks polled by run(). */
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
let S = null, cur = null, chatHist = [];
const TOPICS = ['strategy', 'resume', 'gap', 'outreach', 'stories', 'pivot', 'questions', 'negotiation', 'tools', 'custom'];

const TOKEN = window.LODESTAR_TOKEN || '', CAPTURE = window.LODESTAR_CAPTURE || '';
const safeUrl = u => /^https?:\/\//i.test(u || '') ? u : '';
const api = (p, body) => fetch(p, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', 'X-Lodestar-Token': TOKEN }, body: body ? JSON.stringify(body) : undefined }).then(r => r.json());
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const opt = (list, sel) => list.map(s => `<option ${s === sel ? 'selected' : ''}>${s}</option>`).join('');
function toast(m, kind = '') { const t = $('#toast'); t.textContent = m; t.className = kind; t.style.display = 'block'; clearTimeout(t._h); t._h = setTimeout(() => t.style.display = 'none', 4500); }
function show(id, text) { const e = $('#' + id); e.style.display = 'block'; e.textContent = typeof text === 'string' ? text : JSON.stringify(text, null, 2); }
function mailText(r) {
  if (!r.draft) return r.text || (r.gap ? JSON.stringify(r.gap, null, 2) : r.answer || ('wrote ' + (r.path || '')));
  const p = r.proposal || {};
  return `Subject: ${r.draft.subject}\n\n${r.draft.body}\n\n-> ${p.status}${p.id ? ' (inbox #' + p.id + ')' : ''}${p.reason ? ' - ' + p.reason : ''}`;
}

/* ---- navigation ---- */
$$('nav button[data-tab]').forEach(b => b.onclick = () => go(b.dataset.tab));
function go(tab) {
  $$('nav button[data-tab], main section').forEach(x => x.classList.remove('on'));
  $(`nav button[data-tab="${tab}"]`).classList.add('on'); $('#' + tab).classList.add('on');
  if (tab !== 'board') closeDrawer();
}

/* ---- background tasks ---- */
async function run(action, params, done, btn) {
  if (btn) { btn.disabled = true; btn.dataset.label = btn.textContent; btn.textContent = 'working…'; }
  const finish = () => { if (btn) { btn.disabled = false; btn.textContent = btn.dataset.label; } };
  const { task, error } = await api('/api/run/' + action, params);
  if (error) { finish(); return toast('error: ' + error, 'err'); }
  const poll = async () => {
    const t = await api('/api/tasks/' + task);
    if (t.status === 'running') return setTimeout(poll, 1200);
    finish();
    if (t.status === 'error') return toast('error: ' + t.error, 'err');
    done && done(t.result); load();
  };
  poll();
}

/* ---- state ---- */
async function load() {
  S = await api('/api/state');
  const st = S.stats, pct = x => Math.round(x * 100) + '%';
  $('#stats').innerHTML = `<span>tracked <b>${S.jobs.length}</b></span><span>applied <b>${st.applied_total}</b></span><span>response <b>${pct(st.response_rate)}</b></span><span>interview <b>${pct(st.interview_rate)}</b></span><span>providers <b>${Object.values(S.providers).filter(Boolean).length}</b></span><span>tokens today <b>${(S.usage_today.input + S.usage_today.output).toLocaleString()}</b></span>`;
  const badge = $('#inboxN'); badge.textContent = S.pending.length; badge.classList.toggle('zero', !S.pending.length);
  renderBoard(); renderInbox(); renderSearchless(); renderMonitor(); renderAnswers(); renderIdeas(); renderTools(); renderSetup();
}

function renderBoard() {
  $('#cols').innerHTML = S.statuses.map(s => {
    const jobs = S.jobs.filter(j => j.status === s);
    return `<div class="col" data-s="${s}"><h3>${s} <span>${jobs.length}</span></h3>` + jobs.map(j =>
      `<div class="card ${S.followups.includes(j.id) ? 'late' : ''} ${cur && cur.job.id === j.id ? 'sel' : ''}" onclick="openJob(${j.id})"><div class="co">${esc(j.company)}</div><div class="ti">${esc(j.title)}</div><div class="meta"><span>#${j.id}</span><span>${j.updated_at.slice(0, 10)}</span></div></div>`).join('') + '</div>';
  }).join('');
  const f = S.funnel.stages;
  $('#funnel').innerHTML = f.applied.reached ? 'funnel: ' + Object.entries(f).map(([s, d]) => `<span class="pill">${s} ${d.reached}${d.conversion != null ? ' → ' + Math.round(d.conversion * 100) + '%' : ''}${d.median_days_to_next != null ? ' · ' + d.median_days_to_next + 'd' : ''}</span>`).join('') : '';
  $('#variants').innerHTML = S.variants.length ? 'resume variants: ' + S.variants.map(v => `<span class="pill">${v.variant}: ${v.applied} sent, ${Math.round(v.interview_rate * 100)}% interview</span>`).join(' ') : '';
  if (!S.jobs.length) $('#cols').insertAdjacentHTML('afterend', '');
}

/* ---- job drawer ---- */
function closeDrawer() { $('#drawer').classList.remove('open'); cur = null; $$('.card.sel').forEach(c => c.classList.remove('sel')); }
async function openJob(id) {
  const d = await api('/api/jobs/' + id); if (d.error) return toast(d.error, 'err');
  cur = d; const j = d.job, docs = Object.keys(d.docs);
  $$('.card').forEach(c => c.classList.toggle('sel', c.getAttribute('onclick') === `openJob(${id})`));
  $('#drawer').innerHTML = `
    <div class="head"><b>${esc(j.company)}</b><span class="muted">${esc(j.title)} · #${j.id}</span>
      ${safeUrl(j.url) ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">posting ↗</a>` : ''}
      <select onchange="api('/api/jobs/${j.id}/status',{status:this.value}).then(()=>{load();openJob(${j.id})})">${opt(S.statuses, j.status)}</select>
      <button class="b ghost sm close" onclick="closeDrawer()" aria-label="Close job details">✕</button></div>
    <div class="muted">contact: ${esc(j.contact_name || '')} ${esc(j.contact_email || '(none; replies and follow-ups need one)')}</div>

    <div class="group"><h4>Documents</h4><div class="row">
      <button class="b" onclick="jobRun('gap',{},this)">Gap / ATS score</button>
      <button class="b" onclick="jobRun('tailor',{docx:true},this)">Tailor resume (+docx)</button>
      <button class="b" onclick="jobRun('cover',{docx:true},this)">Cover letter (+docx)</button>
      <button class="b ghost" onclick="jobRun('prep',{},this)">Interview prep</button>
      <button class="b ghost" onclick="jobRun('research',{},this)">Company research</button>
      <button class="b ghost" onclick="run('checklist',{id:${j.id}},r=>show('jOut',r.checklist.map(c=>(c.done?'[x] ':'[ ] ')+c.item+(c.done?'':'   -> '+c.next)).join('\\n')),this)">Checklist</button>
      <label class="muted"><input type="checkbox" id="jCouncil"> council (all providers)</label></div></div>

    <div class="group"><h4>Communicate</h4>
      <div class="row"><input id="jIntent" class="grow" placeholder="reply intent, e.g. accept interview, propose Tue/Wed afternoons"><button class="b ghost" onclick="jobRun('reply',{intent:$('#jIntent').value},this)">Draft reply</button></div>
      <div class="row"><input id="jPerson" class="grow" placeholder="outreach to: Name, title (optional)"><select id="jChannel"><option value="linkedin">LinkedIn note</option><option value="email">Email</option></select><button class="b ghost" onclick="jobRun('outreach',{person:$('#jPerson').value,channel:$('#jChannel').value},this)">Draft outreach</button></div>
      <div class="row"><button class="b ghost" onclick="jobRun('followup',{},this)">Follow-up email</button><input id="jInt" placeholder="interviewer" style="width:140px"><input id="jTnotes" class="grow" placeholder="something specific from the interview"><button class="b ghost" onclick="jobRun('thanks',{interviewer:$('#jInt').value,notes:$('#jTnotes').value},this)">Thank-you note</button></div></div>

    <div class="group"><h4>Schedule and decide</h4>
      <div class="row"><input id="jWhen" placeholder="interview: YYYY-MM-DD HH:MM" style="width:200px"><button class="b ghost" onclick="jobRun('ics',{when:$('#jWhen').value},this)">Calendar .ics</button></div>
      <div class="row"><input id="oSal" placeholder="base" style="width:90px"><input id="oBon" placeholder="bonus" style="width:90px"><input id="oEq" placeholder="equity" style="width:90px"><input id="oBen" placeholder="benefits" style="width:120px"><input id="oDl" placeholder="deadline" style="width:100px"><input id="oNotes" class="grow" placeholder="notes"><button class="b ghost" onclick="jobRun('offer',{salary:$('#oSal').value,bonus:$('#oBon').value,equity:$('#oEq').value,benefits:$('#oBen').value,deadline:$('#oDl').value,notes:$('#oNotes').value},this)">Evaluate offer</button></div></div>

    <div class="group"><h4>Admin</h4>
      <div class="row"><input id="jNote" class="grow" placeholder="add a note"><button class="b ghost sm" onclick="api('/api/jobs/${j.id}/note',{text:$('#jNote').value}).then(()=>openJob(${j.id}))">note</button></div>
      <div class="row"><input id="jJd" class="grow" placeholder="set job description: URL or pasted text"><button class="b ghost sm" onclick="api('/api/jobs/${j.id}/jd',{source:$('#jJd').value}).then(()=>openJob(${j.id}))">set JD</button></div>
      <div class="row"><button class="b ghost sm" onclick="jobRun('packet',{},this)">export packet (zip)</button><button class="b danger sm" onclick="if(confirm('Delete job #${j.id}?'))api('/api/jobs/${j.id}/delete',{}).then(()=>{closeDrawer();load()})">delete job</button></div></div>

    <div class="tabs" id="docTabs">${['timeline', 'description', ...docs].map((n, i) => `<button class="${i === 0 ? 'on' : ''}" onclick="showDoc('${n}',this)">${n}</button>`).join('')}</div>
    <pre id="docView"></pre>
    <div class="row"><button class="b ghost sm" onclick="editDoc()">Edit document</button><input id="dAdj" class="grow" placeholder="adjust this document with AI: shorter / warmer / lead with X"><button class="b ghost sm" onclick="adjustDoc(this)">Adjust</button></div>
    <textarea id="docEdit" style="display:none; min-height:260px"></textarea><button class="b sm" id="docSave" style="display:none" onclick="saveDoc()">Save document</button>
    <div class="out"><h4 class="muted">AI output</h4><pre id="jOut">(run an action above)</pre></div>`;
  $('#drawer').classList.add('open');
  showDoc('timeline', $('#docTabs button'));
  $('#drawer .close')?.focus();
}
function showDoc(n, btn) {
  $$('#docTabs button').forEach(b => b.classList.remove('on')); if (btn) btn.classList.add('on');
  $('#docView').textContent = n === 'timeline' ? cur.events.map(e => `${e.ts}  ${e.kind.padEnd(16)} ${e.detail || ''}`).join('\n')
    : n === 'description' ? (cur.job.jd || '(no job description on file; set one in Admin)') : cur.docs[n];
}
function jobRun(action, extra, btn) {
  const id = cur.job.id;
  run(action, { id, council: $('#jCouncil')?.checked, ...extra }, r => { const t = mailText(r); openJob(id).then(() => { $('#jOut').textContent = t; }); }, btn);
}

/* ---- board add ---- */
async function addJob() {
  const r = await api('/api/jobs', { company: $('#nCo').value, title: $('#nTi').value, jd: $('#nJd').value });
  if (r.error) return toast(r.error, 'err');
  $('#nCo').value = $('#nTi').value = $('#nJd').value = ''; await load(); openJob(r.id);
}

/* ---- inbox ---- */
function renderInbox() {
  $('#inboxList').innerHTML = S.pending.map(r => {
    const p = r.payload, mail = r.kind === 'send_email';
    return `<div class="item"><div class="hd"><b>#${r.id}</b><span class="pill">${r.tool}</span><span class="pill">${r.kind}</span>${esc(r.summary)}<span class="muted">${r.ts.slice(0, 16)}</span></div>
      ${mail ? `<div class="row"><input id="to${r.id}" value="${esc(p.to)}" style="width:260px"><input id="sub${r.id}" class="grow" value="${esc(p.subject)}"></div><textarea id="body${r.id}">${esc(p.body)}</textarea>${p.chosen_time ? `<div class="muted">accepts slot ${esc(p.chosen_time)}; an .ics will be written on send</div>` : ''}`
        : `<pre>${esc(JSON.stringify(p, null, 2))}</pre>`}
      <div class="row"><button class="b" onclick="decide(${r.id},'approve',${mail})">Approve${mail ? ' and send' : ''}</button><button class="b ghost" onclick="decide(${r.id},'reject',false)">Reject</button></div></div>`;
  }).join('') || '<div class="empty">Inbox empty. Automatic actions appear here when a tool is enabled but not set to auto.</div>';
  $('#decidedList').innerHTML = S.decided.map(r => `<div>#${r.id} <b>${r.status}</b> ${esc(r.summary)} <span class="muted">${esc((r.result || '').slice(0, 140))}</span></div>`).join('') || '<div class="muted">nothing decided yet</div>';
}
async function decide(id, op, mail) {
  const body = op === 'approve' && mail ? { edits: { to: $('#to' + id).value, subject: $('#sub' + id).value, body: $('#body' + id).value } } : {};
  const r = await api(`/api/approvals/${id}/${op}`, body);
  toast(r.error ? 'error: ' + r.error : op === 'approve' ? `#${id} ${r.status}: ${r.result || ''}` : `#${id} rejected`, r.error ? 'err' : 'ok'); load();
}

/* ---- search ---- */
function renderSearchless() { /* search results are rendered on demand */ }
function doSearch(btn) {
  $('#sRes').innerHTML = '<div class="muted">searching…</div>';
  run('search', { query: $('#sQ').value, keywords: $('#sK').value, rank: $('#sRank').checked }, r => {
    $('#sRes').innerHTML = `<div class="list">` + ((r.results || []).map(j => `<div>${j.score != null ? `<span class="score">${j.score}</span>` : ''}<b>${esc(j.title)}</b> @ ${esc(j.company)} <span class="muted">${esc(j.location)} ${esc(j.salary)} &lt;${j.source}&gt;</span>
      ${safeUrl(j.url) ? `<a href="${esc(j.url)}" target="_blank" rel="noopener">open ↗</a>` : ''} <button class="b ghost sm" onclick='saveListing(${JSON.stringify(j).replace(/'/g, "&#39;")})'>track</button>${j.why ? `<div class="muted">${esc(j.why)}</div>` : ''}</div>`).join('') || '<div class="empty">nothing found</div>') + '</div>';
  }, btn);
}
async function saveListing(j) { const r = await api('/api/jobs', { company: j.company, title: j.title, url: j.url, jd: j.desc, notes: 'found via ' + j.source }); toast('tracked as #' + r.id, 'ok'); load(); }

/* ---- monitor ---- */
function renderMonitor() {
  $('#wList').innerHTML = `<div class="list">` + (S.watches.map(w => `<div>${esc(w.url)} <span class="muted">kw=${esc(w.keywords || '-')} · last ${esc(w.last_seen || 'never')}</span> <button class="b ghost sm" onclick="api('/api/watches/${w.id}',{}).then(load)">remove</button></div>`).join('') || '<div class="empty">No watches yet. Add a careers page URL or a saved search.</div>') + '</div>';
  $('#alerts').textContent = S.alerts.join('\n') || '(no alerts yet)';
}
async function addWatch() { await api('/api/watches', { url: $('#wUrl').value, keywords: $('#wKw').value, search: $('#wSearch').checked }); $('#wUrl').value = ''; load(); }

/* ---- answers ---- */
function renderAnswers() {
  $('#bank').innerHTML = `<div class="list">` + (S.answers.map(a => `<div><b>${esc(a.question)}</b> <button class="b ghost sm" onclick="api('/api/answers/${a.id}',{}).then(load)">remove</button><div class="muted" style="white-space:pre-wrap">${esc(a.answer)}</div></div>`).join('') || '<div class="empty">No saved answers yet. Draft one above; it is saved through the Inbox unless the answers tool is auto.</div>') + '</div>';
  $('#aJob').innerHTML = S.jobs.map(j => `<option value="${j.id}">#${j.id} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
}
function askAnswer(btn) { run('answer', { id: $('#aJob').value, question: $('#aQ').value }, r => show('aOut', r.answer + '\n\n[reused: ' + (r.reused.join(' | ') || 'none') + ']  [save -> ' + r.proposal.status + ']'), btn); }

/* ---- ideas ---- */
function renderIdeas() {
  if (!$('#iTopic').options.length) $('#iTopic').innerHTML = opt(TOPICS);
  $('#iJob').innerHTML = '<option value="">(no job focus)</option>' + S.jobs.map(j => `<option value="${j.id}">#${j.id} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
  $('#ideaList').innerHTML = S.ideas.map(i => `<div class="panel"><div class="row" style="margin-top:0"><b>${esc(i.title)}</b><span class="pill">${i.topic}</span><span class="pill">score ${i.score}</span><span class="muted">impact ${i.impact ?? '?'} · effort ${i.effort ?? '?'} · fit ${i.fit ?? '?'} · ${esc(i.time || '')}</span>
      <select onchange="api('/api/ideas/${i.id}/status',{status:this.value}).then(load)">${opt(S.idea_statuses, i.status)}</select><button class="b ghost sm" onclick="api('/api/ideas/${i.id}/delete',{}).then(load)">remove</button></div>
      <div>${esc(i.idea || '')}</div><div class="muted">why: ${esc(i.why_it_works || '')}</div>
      <ol class="muted">${(i.plan || []).map(s => `<li>${esc(s)}</li>`).join('')}</ol><div class="muted">metric: ${esc(i.metric || '')}</div>
      <div class="row"><input id="rf${i.id}" class="grow" placeholder="feedback: make it cheaper / focus on X / too vague"><button class="b ghost sm" onclick="run('refine',{idea_id:${i.id},feedback:$('#rf${i.id}').value},r=>toast('refined: '+r.idea.title,'ok'),this)">Refine</button></div></div>`).join('')
    || '<div class="empty">No ideas yet. Pick a topic and craft.</div>';
}
function craft(btn) {
  run('craft', { topic: $('#iTopic').value, id: $('#iJob').value || undefined, role: $('#iRole').value, extra: $('#iExtra').value, single: $('#iSingle').checked }, r => toast(r.ideas.length + ' idea(s) saved', 'ok'), btn);
}

/* ---- tools and setup ---- */
function renderTools() {
  $('#toolTable').innerHTML = `<table><tr><th>Tool</th><th>enabled</th><th>auto</th></tr>${S.tools.map(t => `<tr><td><b>${t.tool}</b><div class="muted">${esc(t.description)}</div></td>
    <td><input type="checkbox" ${t.enabled ? 'checked' : ''} onchange="api('/api/tools',{tool:'${t.tool}',enabled:this.checked}).then(load)"></td>
    <td><input type="checkbox" ${t.auto ? 'checked' : ''} onchange="api('/api/tools',{tool:'${t.tool}',auto:this.checked}).then(load)"></td></tr>`).join('')}</table>`;
  $('#prefs').innerHTML = Object.entries(S.prefs).map(([k, v]) => `<div class="row"><span style="width:200px">${k}</span>${typeof v === 'boolean' ? `<input type="checkbox" ${v ? 'checked' : ''} onchange="api('/api/prefs',{key:'${k}',value:this.checked}).then(load)">` : `<input class="grow" value="${esc(v)}" onchange="api('/api/prefs',{key:'${k}',value:this.value}).then(load)">`}</div>`).join('');
}
function renderSetup() {
  $('#prov').innerHTML = Object.entries(S.providers).map(([n, ok]) => `<span class="pill ${ok ? 'ok' : ''}">${n}${ok ? ' ✓' : ''}</span>`).join('');
  $('#vList').textContent = S.vault.map(v => v.name + (v.user ? ' (' + v.user + ')' : '')).join(' · ') || 'empty';
  $('#pPath').textContent = S.profile_path;
  const o = location.origin;
  $('#bm').href = `javascript:(()=>{const t=document.title,u=location.href,d=(document.querySelector('main')||document.body).innerText.slice(0,12000);fetch('${o}/api/capture?t=${CAPTURE}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:t,url:u,desc:d})}).then(r=>r.json()).then(r=>alert(r.error?('Lodestar: '+r.error):('Lodestar tracked #'+r.id+': '+r.company+' - '+r.title))).catch(e=>alert('Lodestar UI not running? '+e))})();`;
  $('#af').href = `javascript:(()=>{fetch('${o}/api/autofill?t=${CAPTURE}').then(r=>r.json()).then(d=>{const map={first_name:/first.?name|given|fname|legalname.*first/i,last_name:/last.?name|surname|family|lname|legalname.*last/i,name:/^(full.?)?name$|your.?name|^name$|cards\\[.*\\]\\[name\\]/i,email:/e-?mail/i,phone:/phone|mobile|tel/i,linkedin:/linkedin/i,github:/github/i,website:/website|portfolio|^url|personal.?site/i,location:/city|location|address|where.*located/i};const ats={first_name:['#first_name','input[name=\"first_name\"]','[data-automation-id=\"legalNameSection_firstName\"]','#first-name','input[name=\"_systemfield_first_name\"]'],last_name:['#last_name','input[name=\"last_name\"]','[data-automation-id=\"legalNameSection_lastName\"]','#last-name','input[name=\"_systemfield_last_name\"]'],name:['input[name=\"name\"]','input[name=\"_systemfield_name\"]','#full_name'],email:['#email','input[name=\"email\"]','input[name=\"_systemfield_email\"]','[data-automation-id=\"email\"]','input[type=\"email\"]'],phone:['#phone','input[name=\"phone\"]','[data-automation-id=\"phone-number\"]','#phone-number','input[type=\"tel\"]'],linkedin:['input[name=\"urls[LinkedIn]\"]','#linkedin','input[name*=\"linkedin\" i]'],github:['input[name=\"urls[GitHub]\"]','input[name*=\"github\" i]'],website:['input[name=\"urls[Portfolio]\"]','input[name*=\"website\" i]','input[name*=\"portfolio\" i]'],location:['input[name=\"job_application[location]\"]','#location','input[name*=\"location\" i]']};let n=0;for(const k in ats){if(!d[k])continue;for(const sel of ats[k]){const el=document.querySelector(sel);if(el&&!el.value&&!el.dataset.ls){el.value=d[k];el.dataset.ls='1';el.dispatchEvent(new Event('input',{bubbles:true}));n++;break}}}document.querySelectorAll('input,textarea').forEach(el=>{if(el.type==='hidden'||el.type==='password'||el.value||el.dataset.ls)return;const lab=(el.labels&&el.labels[0]?el.labels[0].innerText:'')+' '+(el.name||'')+' '+(el.id||'')+' '+(el.placeholder||'')+' '+(el.getAttribute('aria-label')||'')+' '+(el.getAttribute('data-automation-id')||'')+' '+(el.getAttribute('autocomplete')||'')+' '+(el.getAttribute('data-qa')||'');for(const k in map){if(map[k].test(lab)&&d[k]){el.value=d[k];el.dispatchEvent(new Event('input',{bubbles:true}));n++;break}}});alert('Lodestar filled '+n+' field(s). Review everything, then submit yourself.')}).catch(e=>alert('Lodestar UI not running? '+e))})();`;
}
async function setVault() { const r = await api('/api/vault', { name: $('#vName').value, user: $('#vUser').value, value: $('#vVal').value }); toast(r.error || 'stored', r.error ? 'err' : 'ok'); $('#vVal').value = ''; load(); }

/* ---- profile and coach ---- */
async function loadProfile() { $('#pText').value = (await api('/api/profile')).text; }
function adjustProfile(btn) {
  const ins = $('#pAdj').value.trim(); if (!ins) return toast('type an instruction first', 'err');
  run('adjust', { text: $('#pText').value, instruction: ins, kind: 'master profile' }, r => { $('#pText').value = r.text; toast('adjusted; review, then Save', 'ok'); }, btn);
}
function importResume(btn) {
  const f = $('#pFile').files[0]; if (!f) return toast('choose a file first', 'err');
  const rd = new FileReader();
  rd.onload = async () => {
    btn.disabled = true;
    const r = await api('/api/upload', { name: f.name, data: rd.result.split(',')[1] });
    btn.disabled = false;
    if (r.error) return toast('import failed: ' + r.error, 'err');
    $('#pImport').value = r.text; $('#pImport').style.display = ''; $('#pImportActions').style.display = '';
    toast('imported ' + f.name + ' (' + r.text.length + ' chars)', 'ok');
  };
  rd.readAsDataURL(f);
}
function editDoc() {
  const n = $('#docTabs button.on')?.textContent; if (!n || n === 'timeline' || n === 'description') return toast('pick a document tab first', 'err');
  $('#docEdit').value = cur.docs[n] || ''; $('#docEdit').style.display = ''; $('#docSave').style.display = ''; $('#docEdit').dataset.name = n;
}
async function saveDoc() {
  const n = $('#docEdit').dataset.name; const r = await api('/api/docs/' + cur.job.id, { name: n, text: $('#docEdit').value });
  if (r.error) return toast(r.error, 'err');
  cur.docs = r.docs; $('#docEdit').style.display = 'none'; $('#docSave').style.display = 'none'; showDoc(n, $('#docTabs button.on')); toast('saved ' + n, 'ok');
}
function adjustDoc(btn) {
  const n = $('#docTabs button.on')?.textContent, ins = $('#dAdj').value.trim();
  if (!n || n === 'timeline' || n === 'description') return toast('pick a document tab first', 'err');
  if (!ins) return toast('type an instruction first', 'err');
  const kind = n.includes('cover') ? 'cover letter' : n.includes('resume') ? 'resume' : 'document';
  run('adjust', { text: cur.docs[n], instruction: ins, kind }, r => { $('#docEdit').value = r.text; $('#docEdit').style.display = ''; $('#docSave').style.display = ''; $('#docEdit').dataset.name = n; toast('adjusted; review, then Save document', 'ok'); }, btn);
}
async function saveProfile() { await api('/api/profile', { text: $('#pText').value }); toast('profile saved', 'ok'); }
function resetChat() {
  const mock = $('#cMode').value === 'mock';
  $('#cJob').style.display = mock ? '' : 'none';
  if (mock && !$('#cJob').options.length) $('#cJob').innerHTML = S.jobs.map(j => `<option value="${j.id}">#${j.id} ${esc(j.company)} - ${esc(j.title)}</option>`).join('');
  chatHist = [];
  $('#chat').innerHTML = `<div class="msg ai">${mock ? 'Mock interview ready. Send any message to begin; the interviewer asks one question at a time. Type "done" for a scored debrief.' : 'Ask me anything about your search. I can see your profile and tracker.'}</div>`;
}
function sendChat() {
  const q = $('#cIn').value.trim(); if (!q) return; $('#cIn').value = '';
  chatHist.push({ role: 'user', content: q }); $('#chat').insertAdjacentHTML('beforeend', `<div class="msg me">${esc(q)}</div>`);
  const council = $('#cCouncil').checked, mock = $('#cMode').value === 'mock';
  const action = mock ? 'mock' : council ? 'council' : 'chat';
  const params = mock ? { id: $('#cJob').value, messages: chatHist } : council ? { prompt: q } : { messages: chatHist };
  run(action, params, r => {
    const a = council && !mock ? r.synthesis : r.reply; chatHist.push({ role: 'assistant', content: a });
    $('#chat').insertAdjacentHTML('beforeend', `<div class="msg ai">${esc(a)}</div>`); $('#chat').scrollTop = 1e9;
  }, $('#cGo'));
}
function dictate() {  // browser speech recognition; audio goes only where the browser's own service sends it
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return toast('this browser has no speech recognition (try Chrome or Edge)', 'err');
  const r = new SR(); r.lang = navigator.language || 'en-US'; r.interimResults = false;
  $('#cMic').disabled = true;
  r.onresult = e => { $('#cIn').value = ($('#cIn').value + ' ' + e.results[0][0].transcript).trim(); };
  r.onerror = e => toast('dictation: ' + e.error, 'err');
  r.onend = () => { $('#cMic').disabled = false; };
  r.start();
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });
load(); loadProfile(); setInterval(load, 60000);
