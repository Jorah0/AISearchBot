/* Lodestar field matcher: pure functions over field descriptors (no DOM), so node tests run it as is.
   Loaded into the page's isolated world by the popup (chrome.scripting, files) and in node by require().
   classify(d) -> key | null: the denylist first (never filled), then exact id/name/automation-id rules, repeat groups
   (work history, education), autocomplete tokens, label patterns, else 'question' (sent to Lodestar as a label). */
(function (root) {
  "use strict";
  if (root.LodestarMatcher) return;

  // never filled: identity numbers, birth date, money routes, secrets. False positives only mean "not filled".
  const DENY = /ssn|social.?security|national.?id|passport|birth|\bdob\b|driver.?s?.?licen[cs]e|tax.?id|iban|routing|bank|card.?number|cvv|password/i;
  const NO_TYPES = new Set(["password", "file", "hidden", "checkbox", "submit", "button", "image", "reset"]);
  const LINKEDIN = "Lodestar does not capture or fill on LinkedIn: its User Agreement bans browser add-ons that scrape " +
    "or copy it. Open the job on the company's own careers page instead.";

  const ATS_HOSTS = [
    ["greenhouse", /(^|\.)greenhouse\.io$/], ["lever", /(^|\.)lever\.co$/], ["ashby", /(^|\.)ashbyhq\.com$/],
    ["workday", /(^|\.)myworkday(jobs|site)?\.com$/], ["icims", /(^|\.)icims\.com$/],
    ["smartrecruiters", /(^|\.)smartrecruiters\.com$/],
  ];
  // DOM markers for a form hosted on the company's own domain (content.js tests them with querySelector)
  const MARKERS = {
    greenhouse: "#application_form, #grnhse_app, input#first_name",
    lever: 'input[name="urls[LinkedIn]"], .application-question',
    ashby: '[name^="_systemfield_"]',
    workday: '[data-automation-id^="legalNameSection"], [data-automation-id="workExperienceSection"]',
    smartrecruiters: "spl-input, oc-personal-information",
  };

  // exact id / name / data-automation-id -> key (one table: the ids do not clash across ATSs, and a form embedded on a
  // company domain is matched without knowing its ATS). Seeded from the bookmarklet and the public form markup.
  const EXACT = {
    first_name: "first", last_name: "last", email: "email", phone: "phone",  // Greenhouse
    gender: "eeo.gender", hispanic_ethnicity: "eeo.hispanic", race: "eeo.race", veteran_status: "eeo.veteran",
    disability_status: "eeo.disability",
    name: "name", org: "current_company", location: "location", "urls[LinkedIn]": "linkedin",  // Lever
    "urls[GitHub]": "github", "urls[Portfolio]": "website", "urls[Other]": "website",
    "eeo[gender]": "eeo.gender", "eeo[race]": "eeo.race", "eeo[veteran]": "eeo.veteran", "eeo[disability]": "eeo.disability",
    _systemfield_name: "name", _systemfield_email: "email", _systemfield_location: "location",  // Ashby
    legalNameSection_firstName: "first", legalNameSection_lastName: "last", "phone-number": "phone",  // Workday, SR
    addressSection_city: "city",
    "first-name": "first", "last-name": "last", "confirm-email": "email",  // SmartRecruiters
  };
  const AUTOCOMPLETE = {
    "given-name": "first", "family-name": "last", name: "name", email: "email", tel: "phone", "tel-national": "phone",
    url: "website", "address-level2": "city", organization: "current_company", "organization-title": "current_title",
  };
  const LABELS = [  // first hit wins, tested on the label (else aria-label, placeholder, then name/id)
    [/hispanic|latin[oax]/i, "eeo.hispanic"], [/\bgender\b|\bsex\b/i, "eeo.gender"], [/\brace\b|ethnicity/i, "eeo.race"],
    [/veteran/i, "eeo.veteran"], [/disabilit/i, "eeo.disability"],
    [/(desired|expected|target).{0,20}(salary|compensation|pay)|salary expectations?|compensation expectations?/i, "salary"],
    [/e-?mail/i, "email"],
    [/first.?name|given.?name|forename/i, "first"], [/last.?name|surname|family.?name/i, "last"],
    [/full.?name|legal.?name|^name$|^your name$/i, "name"],
    [/phone|mobile|\btel\b/i, "phone"], [/linkedin/i, "linkedin"], [/github/i, "github"],
    [/website|portfolio|personal.?(site|url)|\bblog\b/i, "website"],
    [/(current|most recent).{0,10}(company|employer)/i, "current_company"],
    [/(current|most recent).{0,10}(job.?)?(title|role|position)/i, "current_title"],
    [/\bcity\b/i, "city"], [/\blocation\b|where are you (based|located)/i, "location"],
  ];
  const GROUP = {
    exp: [[/description|responsibilit|summary|duties/i, "description"], [/start|\bfrom\b/i, "start"],
      [/\bend|\bto\b|until/i, "end"], [/location|\bcity\b/i, "location"],
      [/company|employer|organi[sz]ation/i, "company"], [/title|position|\brole\b/i, "title"]],
    edu: [[/start|\bfrom\b/i, "start"], [/\bend|\bto\b|until|graduat/i, "end"], [/degree/i, "degree"],
      [/field|major|discipline|study/i, "field"], [/school|universit|institution|college/i, "school"]],
  };

  const s = (v) => String(v == null ? "" : v);
  // 'Work Experience 2', 'Employment history', 'Experience'; never 'Equal Employment Opportunity information'
  const EXP_SECTION = /(work|employment|job)\s*(experience|history)|^(experience|employment)\b/i;

  function hostAts(host) {
    const h = s(host).toLowerCase();
    const hit = ATS_HOSTS.find(([, rx]) => rx.test(h));
    return hit ? hit[0] : null;
  }

  function detectAts(host, markers) {
    return hostAts(host) || (markers || [])[0] || null;
  }

  function linkedin(host) {
    const h = s(host).toLowerCase().replace(/\.$/, "");
    return h === "linkedin.com" || h.endsWith(".linkedin.com");
  }

  function fillable(d) {  // a field a question answer can go into
    return d.tag === "textarea" || d.tag === "select" || d.type === "radio" || d.type === "widget" ||
      (d.tag === "input" && ["", "text", "search", "date"].includes(d.type));  // a date only ever goes to "needs you"
  }

  function classify(d) {
    const ids = [d.id, d.name, d.auto, d.qa].map(s).filter(Boolean);
    const all = [d.label, d.aria, d.placeholder, ...ids].join(" ");
    if (DENY.test(all) || NO_TYPES.has(d.type)) return null;
    const text = s(d.label || d.aria || d.placeholder);
    if (d.group) {  // inside a work history / education repeat: 'Company' / 'location' there is that role's, not yours
      const kind = d.group.split(":")[0];
      const hay = `${text} ${ids.join(" ")}`;
      const hit = GROUP[kind].find(([rx]) => rx.test(hay));
      if (hit) return `${kind}.${hit[1]}`;
    }
    for (const k of ids) if (Object.prototype.hasOwnProperty.call(EXACT, k)) return EXACT[k];
    for (const tok of s(d.autocomplete).toLowerCase().split(/\s+/)) if (AUTOCOMPLETE[tok]) return AUTOCOMPLETE[tok];
    const hay = text || ids.join(" ");
    for (const [rx, key] of LABELS) if (rx.test(hay)) return key;
    return text && fillable(d) ? "question" : null;
  }

  // the repeat group of each descriptor: 'exp:0', 'edu:1' ... (ordinal by first appearance in DOM order), else null
  function groups(ds) {
    const seen = { exp: [], edu: [] };
    for (const d of ds) {
      const ids = [d.id, d.name, d.auto].map(s).filter(Boolean).join(" ");
      const kind = /work|experience|employment|position/i.test(ids) || EXP_SECTION.test(s(d.section)) ? "exp"
        : /education|school|degree/i.test(`${ids} ${s(d.section)}`) ? "edu" : null;
      if (!kind) { d.group = null; continue; }
      const m = /(?:^|[-_[])(\d{1,2})(?:[\]\-_]|$)/.exec(ids);
      const raw = m ? m[1] : (/\d{1,2}\s*$/.exec(s(d.section)) || ["0"])[0].trim();
      if (!seen[kind].includes(raw)) seen[kind].push(raw);
      d.group = `${kind}:${seen[kind].indexOf(raw)}`;
    }
    return ds;
  }

  const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

  function normalizeDate(v) {
    const t = s(v).trim().toLowerCase();
    if (!t) return null;
    if (/^(present|current|now|today)$/.test(t)) return { m: null, y: null, current: true };
    let m;
    if ((m = /^(\d{4})-(\d{1,2})/.exec(t))) return { m: +m[2], y: +m[1], current: false };
    if ((m = /^(\d{1,2})\/(\d{4})$/.exec(t))) return { m: +m[1], y: +m[2], current: false };
    if ((m = /^([a-z]{3})[a-z]*\.?\s+(\d{4})$/.exec(t)) && MONTHS.includes(m[1])) return { m: MONTHS.indexOf(m[1]) + 1, y: +m[2], current: false };
    if ((m = /^(\d{4})$/.exec(t))) return { m: null, y: +m[1], current: false };
    return null;
  }

  const norm = (v) => s(v).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const DECLINE = /decline|prefer not|don.?t wish|do not wish|not to (say|answer|disclose)|rather not/i;

  // the option value to select for a stored answer, or null (no confident pick: the field goes to "needs you")
  function pickOption(options, value) {
    const v = norm(value);
    const opts = (options || []).filter((o) => norm(o.t) && s(o.v) !== "");
    if (!v || !opts.length) return null;
    const by = (f) => { const o = opts.find(f); return o ? s(o.v) : null; };
    return by((o) => norm(o.t) === v || norm(o.v) === v)
      ?? by((o) => norm(o.t).startsWith(v))
      ?? by((o) => new RegExp(`^${norm(o.t).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`).test(v))  // 'Yes, without sponsorship' -> Yes
      ?? by((o) => norm(o.t).includes(v))
      ?? (DECLINE.test(value) ? by((o) => DECLINE.test(o.t)) : null);
  }

  function atsFrame(src, pageOrigin) {  // a cross-origin ATS iframe the popup offers to open in its own tab
    try {
      const u = new URL(src, pageOrigin);
      return /^https?:$/.test(u.protocol) && u.origin !== pageOrigin && hostAts(u.hostname) ? u.href : null;
    } catch (e) {
      return null;
    }
  }

  const api = { detectAts, classify, groups, normalizeDate, pickOption, linkedin, atsFrame, MARKERS, LINKEDIN, MONTHS };
  root.LodestarMatcher = api;
  if (typeof module === "object" && module && module.exports) module.exports = api;
})(globalThis);
