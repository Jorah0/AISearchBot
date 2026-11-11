/* Lodestar content script: runs in the page's ISOLATED world, injected by the popup only when you press Capture or Fill
   (activeTab + scripting; nothing runs on any page otherwise). It reads the page and sets field values. It never
   clicks, submits, navigates, presses keys, ticks a checkbox or sets a radio, never talks to the network and never
   reads extension storage: the popup hands it the data as executeScript args (tests/test_extension_client.py). */
(() => {
  "use strict";
  if (globalThis.LodestarScan) return;  // injected again on the next click: keep the state of the first run
  const M = globalThis.LodestarMatcher;
  const FIELDS = 'input, textarea, select, [role="combobox"]:not(input), button[aria-haspopup="listbox"]';
  const SKIP = new Set(["hidden", "submit", "button", "image", "reset", "checkbox"]);
  const BLUE = "2px solid #2563eb", AMBER = "2px solid #d97706";
  const st = { fields: [], done: new Map(), host: null };  // per frame, until the page navigates

  const txt = (n) => (n ? n.textContent || "" : "").replace(/\s+/g, " ").trim();
  const clean = (v) => String(v || "").replace(/\s+/g, " ").replace(/[\s*✱]+$/, "").trim().slice(0, 200);
  const attr = (el, a) => clean(el.getAttribute(a));

  function* walk(root) {  // DOM order, into open shadow roots (SmartRecruiters web components)
    for (const el of root.querySelectorAll("*")) {
      if (el.matches(FIELDS)) yield el;
      if (el.shadowRoot) yield* walk(el.shadowRoot);
    }
  }

  function visible(el) {  // honeypots: hidden, transparent, tiny, off-page, disabled, read-only or aria-hidden fields
    if (el.disabled || el.readOnly || el.closest('[aria-hidden="true"]')) return false;
    if (el.checkVisibility && !el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return false;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return false;
    const x = r.left + scrollX, y = r.top + scrollY;
    return x + r.width > 0 && y + r.height > 0 && x < document.documentElement.scrollWidth + 5000;
  }

  function leading(el) {  // the text just before the field's container (Lever's .application-label and the like)
    let n = el;
    for (let up = 0; up < 3 && n.parentElement; up++, n = n.parentElement) {
      for (let p = n.previousElementSibling; p; p = p.previousElementSibling) {
        if (p.matches(FIELDS) || p.querySelector(FIELDS)) return "";  // another field's block: not this one's label
        if (txt(p)) return clean(txt(p));
      }
    }
    return "";
  }

  function byIds(el, ids) {
    const root = el.getRootNode();
    return clean(String(ids || "").split(/\s+/).map((id) => txt(root.getElementById ? root.getElementById(id) : null)).join(" "));
  }

  function labelOf(el) {
    if (el.type === "radio") {  // the group's question, never one option's text
      const g = el.closest('[role="radiogroup"], fieldset');
      const lg = g && g.querySelector("legend");
      const first = (el.form || el.getRootNode()).querySelector(`input[type="radio"][name="${CSS.escape(el.name)}"]`) || el;
      return (g && (byIds(g, g.getAttribute("aria-labelledby")) || attr(g, "aria-label"))) || (lg && clean(txt(lg))) || leading(first);
    }
    const ls = el.labels ? [...el.labels].map(txt).filter(Boolean) : [];
    if (ls.length) return clean(ls.join(" "));
    const lg = el.closest("fieldset") && el.closest("fieldset").querySelector("legend");
    return byIds(el, el.getAttribute("aria-labelledby")) || attr(el, "aria-label") || (lg && clean(txt(lg))) ||
      leading(el) || attr(el, "placeholder");
  }

  function section(el, heads) {  // the nearest heading before the field (work history / education groups)
    let n = el;
    while (n.getRootNode() !== document && n.getRootNode().host) n = n.getRootNode().host;
    let last = "";
    for (const h of heads) if (h.compareDocumentPosition(n) & Node.DOCUMENT_POSITION_FOLLOWING) last = txt(h);
    return clean(last);
  }

  function descriptor(el, i, heads) {
    const tag = el.tagName.toLowerCase();
    const type = tag === "input" ? (el.getAttribute("type") || "text").toLowerCase() : tag === "select" || tag === "textarea" ? "" : "widget";
    const d = {
      i, tag: type === "widget" ? "widget" : tag, type, name: attr(el, "name"), id: attr(el, "id"), label: labelOf(el),
      placeholder: attr(el, "placeholder"), aria: attr(el, "aria-label"), auto: attr(el, "data-automation-id"),
      qa: attr(el, "data-qa"), autocomplete: attr(el, "autocomplete"), options: [], group: null, section: section(el, heads),
    };
    if (tag === "select") d.options = [...el.options].slice(0, 300).map((o) => ({ v: clean(o.value), t: clean(o.text) }));
    if (type === "radio") d.options = radios(el).map((r) => ({ v: clean(r.value), t: clean([...(r.labels || [])].map(txt).join(" ")) }));
    return d;
  }

  const radios = (el) => [...(el.form || el.getRootNode()).querySelectorAll(`input[type="radio"][name="${CSS.escape(el.name)}"]`)];

  function agentExtra(el, d) {  // the apply agent's scan (Lodestar's own window): state its plan needs, read only
    const group = d.type === "radio" ? radios(el) : [el];
    const value = d.type === "radio" ? clean((group.find((r) => r.checked) || {}).value)
      : d.type === "checkbox" ? String(el.checked) : d.type === "file" ? clean([...(el.files || [])].map((f) => f.name).join(","))
      : d.tag === "widget" ? clean(txt(el)) : String(el.value || "").slice(0, 4000);
    group.forEach((r) => r.setAttribute("data-lodestar-i", String(d.i)));
    return { ...d, required: Boolean(el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(txt(el.labels && el.labels[0]))),
      value, help: byIds(el, el.getAttribute("aria-describedby")), maxlength: el.maxLength > 0 ? el.maxLength : null,
      hidden: d.type === "file" ? !visible(el) : false };
  }

  // opts.agent: the apply agent (lodestar/apply_ats.py, its own window, never the extension): checkboxes and every file
  // input too, each element tagged data-lodestar-i so Lodestar finds it again, plus required / value / help
  globalThis.LodestarScan = (opts) => {
    if (M.linkedin(location.hostname)) return { error: M.LINKEDIN, fields: [], questions: [], atsFrames: [] };
    const agent = Boolean(opts && opts.agent);
    if (agent) for (const el of walk(document)) el.removeAttribute("data-lodestar-i");  // a new step: fresh numbers only
    const heads = [...document.querySelectorAll('h1, h2, h3, h4, h5, h6, legend, [role="heading"]')];
    const seenRadio = new Set(), out = [];
    for (const el of walk(document)) {
      const type = el.tagName === "INPUT" ? (el.getAttribute("type") || "").toLowerCase() : "";
      if (SKIP.has(type) && !(agent && type === "checkbox")) continue;
      if (type === "radio") {  // one descriptor per group, visible when any option or its label is
        if (seenRadio.has(el.name)) continue;
        seenRadio.add(el.name);
        if (!radios(el).some((r) => visible(r) || [...(r.labels || [])].some(visible))) continue;
      } else if (type === "file") {
        if (!agent && !/resume|r[ée]sum[ée]|\bcv\b/i.test(labelOf(el) + attr(el, "name") + attr(el, "id"))) continue;
      } else if (!visible(el)) continue;
      out.push({ el, d: descriptor(el, out.length, heads) });
      if (out.length >= 400) break;
    }
    M.groups(out.map((f) => f.d));
    if (agent) return { fields: out.map((f) => ({ ...agentExtra(f.el, f.d), key: f.d.type === "file" ? "file" : M.classify(f.d) })) };
    st.fields = out.map((f) => ({ el: f.el, d: f.d, key: f.d.type === "file" ? "resume" : M.classify(f.d) }));
    const markers = Object.keys(M.MARKERS).filter((k) => document.querySelector(M.MARKERS[k]));
    const frames = [...document.querySelectorAll("iframe[src]")].map((f) => M.atsFrame(f.getAttribute("src"), location.origin)).filter(Boolean);
    return {
      ats: M.detectAts(location.hostname, markers),
      fields: out.map((f) => ({ ...f.d, group: null })),  // raw descriptors (what the node tests replay)
      keys: st.fields.map((f) => f.key),
      questions: [...new Set(st.fields.filter((f) => f.key === "question" && f.d.label).map((f) => f.d.label))].slice(0, 100),
      atsFrames: [...new Set(frames)],
    };
  };

  // ---- capture: what the posting says about itself
  function flat(x) {
    return typeof x === "string" || typeof x === "number" ? String(x) : x && typeof x === "object" ? String(x.name || x["@id"] || "") : "";
  }

  function jsonLd() {
    const seen = [];
    const visit = (n) => {
      if (Array.isArray(n)) n.forEach(visit);
      else if (n && typeof n === "object") {
        const t = n["@type"];
        if (t === "JobPosting" || (Array.isArray(t) && t.includes("JobPosting"))) seen.push(n);
        if (n["@graph"]) visit(n["@graph"]);
      }
    };
    for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
      try { visit(JSON.parse(s.textContent)); } catch (e) { /* bad JSON on the page: skipped */ }
      if (seen.length) break;
    }
    const p = seen[0];
    if (!p) return null;
    const locs = [].concat(p.jobLocation || []).map((l) => {
      const a = (l && l.address) || {};
      return [a.addressLocality, a.addressRegion, flat(a.addressCountry)].map(flat).filter(Boolean).join(", ");
    }).filter(Boolean);
    const b = p.baseSalary || {}, v = (b && b.value) || {};
    const range = typeof v === "object" ? [v.minValue, v.maxValue].filter((n) => n != null).join("-") || flat(v.value) : flat(v);
    return {
      title: flat(p.title), company: flat(p.hiringOrganization), posted_at: flat(p.datePosted),
      location: /TELECOMMUTE/i.test(flat(p.jobLocationType)) ? "Remote" : locs.join("; "),
      salary: range ? [flat(b.currency), range, flat(v.unitText)].filter(Boolean).join(" ") : "",
      description: flat(p.description).slice(0, 100000),
    };
  }

  globalThis.LodestarReadPosting = () => {
    if (M.linkedin(location.hostname)) return { error: M.LINKEDIN };
    const sel = String(getSelection() || "");
    const main = document.querySelector("main") || document.querySelector("article") || document.body;
    return {
      title: document.title, url: location.href.split("#")[0],
      desc: (sel.length > 200 ? sel : main ? main.innerText : "").slice(0, 12000), posting: jsonLd(),
    };
  };

  // ---- fill
  const PROTO = { input: HTMLInputElement, textarea: HTMLTextAreaElement, select: HTMLSelectElement };

  function setValue(el, v) {  // the native setter (React's value tracker sees a change), then the events apps listen for
    Object.getOwnPropertyDescriptor(PROTO[el.tagName.toLowerCase()].prototype, "value").set.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new FocusEvent("focusout", { bubbles: true }));
  }

  const CONTACT = {
    first: "first_name", last: "last_name", name: "name", email: "email", phone: "phone", location: "location",
    linkedin: "linkedin", github: "github", website: "website", current_company: "current_company", current_title: "current_title",
  };

  function wanted(f, data) {  // {value, kind} for this field, or null
    const k = f.key || "";
    let v = "", kind = "profile";
    if (CONTACT[k]) v = data[CONTACT[k]];
    else if (k === "city") v = String(data.location || "").split(",")[0];
    else if (k.startsWith("eeo.")) { v = (data.eeo || {})[k.slice(4)] || (k === "eeo.gender" && (data.eeo || {}).sex); kind = "answer"; }
    else if (k === "salary") { v = data.salary; kind = "answer"; }
    else if (k === "question") {
      const a = (data.answers || {})[f.d.label];
      if (!a) return null;
      return { value: String(a.answer || ""), kind: "answer", note: a.match === "suggested" ? `answer "${a.question}" (check)` : "" };
    } else if (k.startsWith("exp.") || k.startsWith("edu.")) {
      const [kindKey, field] = k.split(".");
      const row = (data[kindKey === "exp" ? "experience" : "education"] || [])[+(f.d.group || ":0").split(":")[1]];
      v = row && row[field];
    }
    if (!v) return null;
    v = String(v);
    if (["linkedin", "github", "website"].includes(k) && !/^https?:\/\//i.test(v)) v = "https://" + v;
    return { value: v, kind };
  }

  function dateText(f, v) {  // a stored date written the way this field asks for it
    const d = M.normalizeDate(v);
    if (!d) return { value: v };
    if (d.current) return { needs: "you currently work here: tick that box yourself" };
    const hay = `${f.d.label} ${f.d.aria} ${f.d.placeholder} ${f.d.id} ${f.d.auto}`;
    const mm = d.m ? String(d.m).padStart(2, "0") : "";
    if (f.d.type === "month") return d.m ? { value: `${d.y}-${mm}` } : { needs: `month and year (stored: ${v})` };
    if (/month/i.test(hay) && !/year/i.test(hay)) return d.m ? { value: f.d.tag === "select" ? M.MONTHS[d.m - 1] : mm } : { needs: `month (stored: ${v})` };
    if (/year/i.test(hay)) return { value: String(d.y) };
    if (/mm\s*\/\s*yyyy/i.test(f.d.placeholder)) return d.m ? { value: `${mm}/${d.y}` } : { needs: `month (stored: ${v})` };
    return { value: v };
  }

  globalThis.LodestarFill = (data) => {
    const rows = [], needs = [];
    let filled = 0, suggested = 0;
    const need = (f, hint) => { needs.push({ label: f.d.label || f.d.name || f.d.id, hint }); rows.push({ text: `${f.d.label || f.d.name}: ${hint} (needs you)` }); };
    for (const f of st.fields) {
      if (!f.el.isConnected) continue;
      if (f.key === "resume") { need(f, `upload ${data.job && data.job.resume ? data.job.resume : "your resume"}`); continue; }
      const w = wanted(f, data || {});
      if (!w) continue;
      let value = w.value;
      if (/\.(start|end)$/.test(f.key)) {
        const t = dateText(f, value);
        if (t.needs) { need(f, t.needs); continue; }
        value = t.value;
      }
      if (f.d.type === "radio" || f.d.type === "widget") { need(f, `your stored answer: ${value}`); continue; }
      if (f.d.type === "date") { need(f, `a date (stored: ${value})`); continue; }
      if (f.el.value !== "") continue;  // yours (or the form's default): never overwritten
      if (f.d.tag === "select") {
        const opts = [...f.el.options].map((o) => ({ v: o.value, t: o.text }));
        const pick = M.pickOption(opts, value);
        if (pick == null) { need(f, `dropdown, your stored answer: ${value}`); continue; }
        value = pick;
      } else if (f.d.type === "number") value = (value.match(/\d[\d,]*/) || [""])[0].replace(/,/g, "");
      if (f.el.maxLength > 0 && value.length > f.el.maxLength) { need(f, `too long for this field: ${value.slice(0, 80)}`); continue; }
      if (!value) continue;
      const prev = f.el.value, outline = f.el.style.outline;
      setValue(f.el, value);
      f.el.style.outline = w.kind === "answer" ? AMBER : BLUE;
      st.done.set(f.el, { prev, value: f.el.value, outline });
      if (w.kind === "answer") suggested++; else filled++;
      rows.push({ el: f.el, label: f.d.label || f.d.name, text: `${f.d.label || f.d.name} <- ${w.note || value.slice(0, 60)}` });
    }
    panel(rows);
    return { filled, suggested, needsYou: needs };
  };

  function undo(el) {  // only while the field still holds what we typed: an edit of yours is never undone
    const e = st.done.get(el);
    if (!e) return false;
    st.done.delete(el);
    el.style.outline = e.outline;
    if (!el.isConnected || el.value !== e.value) return false;
    setValue(el, e.prev);
    return true;
  }

  // ---- the panel: a closed shadow root, text only, our own trusted-click handlers
  function panel(rows) {
    if (st.host) st.host.remove();
    if (!rows.length) return;
    const host = document.createElement("div");
    Object.assign(host.style, { position: "fixed", right: "16px", bottom: "16px", zIndex: "2147483647" });
    const root = host.attachShadow({ mode: "closed" });
    const el = (tag, css, text) => { const n = document.createElement(tag); Object.assign(n.style, css || {}); if (text != null) n.textContent = text; return n; };
    const btn = (label, act, on) => {
      const b = el("button", { font: "12px system-ui, sans-serif", marginLeft: "6px", cursor: "pointer" }, label);
      b.setAttribute("data-act", act);
      b.addEventListener("click", (e) => { if (e.isTrusted) on(); });
      return b;
    };
    const box = el("div", { background: "#fff", color: "#111", border: "1px solid #888", borderRadius: "8px", padding: "10px",
      width: "360px", maxHeight: "50vh", overflow: "auto", font: "13px system-ui, sans-serif", boxShadow: "0 4px 16px rgba(0,0,0,.25)" });
    box.setAttribute("role", "dialog");
    box.setAttribute("aria-label", "Lodestar filled these fields");
    box.append(el("div", { fontWeight: "600", marginBottom: "6px" }, "Lodestar filled these fields. Check them; nothing was submitted."));
    rows.forEach((r) => {
      const line = el("div", { margin: "4px 0" });
      const t = el("span", {}, r.text);
      line.append(t);
      if (r.el) line.append(btn("Undo", `undo:${r.label}`, () => { t.textContent = `${r.text} (${undo(r.el) ? "undone" : "kept: you changed it"})`; }));
      box.append(line);
    });
    const bar = el("div", { marginTop: "8px", textAlign: "right" });
    bar.append(btn("Undo all", "undo-all", () => { [...st.done.keys()].forEach(undo); host.remove(); }),
      btn("Close", "close", () => { for (const [n, e] of st.done) n.style.outline = e.outline; st.done.clear(); host.remove(); }));
    box.append(bar);
    root.append(box);
    document.documentElement.append(host);
    st.host = host;
  }
})();
