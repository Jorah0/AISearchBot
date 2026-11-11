/* Lodestar popup: pairing, the signed calls to the local server (POST /api/ext/* only) and the two buttons.
   The secret lives in chrome.storage.local and this popup's memory only; it never reaches a page or the content
   script. Capture and Fill go only to a port whose signed ping proved, in this popup session, that it holds the
   secret. Signatures and the proof both name the port dialled, so a process squatting a scanned port can neither relay
   our calls to the real server nor replay its proof. Every result is rendered as text. */
"use strict";
const $ = (id) => document.getElementById(id);
const PORTS = Array.from({ length: 10 }, (_, i) => 8765 + i);  // ponytail: 10 ports; past 8774 the paired port is tried first
const enc = new TextEncoder();
let cred = null;  // {port, id, secret}
let live = null;  // the proof-verified port of this popup session
let tab = null;

function say(text, kind) {
  $("status").textContent = text;
  $("status").className = kind || "";
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
  return Array.from(sig, (b) => b.toString(16).padStart(2, "0")).join("");
}

// the one network call: POST <port>/api/ext/<route>, signed with X-Lodestar-Ext unless pairing
async function post(port, path, obj, signed = true) {
  if (!/^\/api\/ext\/[a-z]+$/.test(path)) throw new Error("not an extension route");
  const body = JSON.stringify(obj || {});
  const headers = { "Content-Type": "application/json" };
  if (signed) {
    const ts = Math.floor(Date.now() / 1000);
    headers["X-Lodestar-Ext"] = `${cred.id}.${ts}.${await hmac(cred.secret, `${ts}\nPOST\n${port}\n${path}\n${body}`)}`;
  }
  const r = await fetch(`http://127.0.0.1:${port}${path}`, {
    method: "POST", headers, body, signal: AbortSignal.timeout(path === "/api/ext/ping" ? 2000 : 60000),
  });
  let data = {};
  try { data = await r.json(); } catch (e) { /* not Lodestar */ }
  return { status: r.status, data };
}

async function ping(port) {  // {version} when this port proved it holds our secret; {status: 401}; else null
  try {
    const { status, data } = await post(port, "/api/ext/ping", {});
    if (status === 401) return { status };
    const fresh = status === 200 && Number.isInteger(data.ts) && Math.abs(Date.now() / 1000 - data.ts) <= 120;
    return fresh && data.proof === await hmac(cred.secret, `pong\n${data.ts}\n${port}`) ? { version: String(data.version || "") } : null;
  } catch (e) {
    return null;
  }
}

async function connect() {
  say("Looking for Lodestar...");
  const first = await ping(cred.port);
  let port = first && first.version ? cred.port : null, version = first && first.version;
  for (const p of PORTS) {
    if (port) break;
    if (p === cred.port) continue;
    const r = await ping(p);
    if (r && r.version) { port = p; version = r.version; }
  }
  if (!port) {
    return say(first && first.status === 401
      ? `Lodestar on port ${cred.port} does not know this browser. Pair again from Lodestar > Setup, or Unpair.`
      : "Lodestar is not running. Start it, then open this popup again.", "err");
  }
  if (port !== cred.port) {
    cred.port = port;
    await chrome.storage.local.set({ cred });
  }
  live = port;
  say(`Lodestar ${version} connected (port ${port}).`, "ok");
  const lockedOut = !tab || !/^https?:/.test(tab.url || "") || hostOf(tab.url) === "";
  $("capture").disabled = $("fill").disabled = lockedOut || LodestarMatcher.linkedin(hostOf(tab.url));
}

function hostOf(url) {
  try { return new URL(url).hostname; } catch (e) { return ""; }
}

async function target() {  // the tab you clicked the icon on (test hook: ?url=http://127.0.0.1:... picks that tab)
  const u = new URLSearchParams(location.search).get("url");
  if (u && /^http:\/\/127\.0\.0\.1:\d+\//.test(u)) return (await chrome.tabs.query({})).find((t) => t.url === u) || null;
  return (await chrome.tabs.query({ active: true, currentWindow: true }))[0] || null;
}

async function pair() {
  const m = /^\s*(\d{2,5})\s*-\s*(\S.*?)\s*$/.exec($("pairing").value);
  if (!m || +m[1] < 1 || +m[1] > 65535) return say("Type the pairing string Setup shows, like 8765-K7QX-M2PD.", "err");
  const brands = (navigator.userAgentData && navigator.userAgentData.brands) || [];
  const label = brands.some((b) => /Edge/i.test(b.brand)) ? "Edge" : "Chrome";
  $("pair").disabled = true;
  try {
    const { status, data } = await post(+m[1], "/api/ext/pair", { code: m[2], label }, false);
    if (status !== 200 || !data.secret) return say(data.error || `Lodestar answered ${status}.`, "err");
    cred = { port: +m[1], id: String(data.id), secret: String(data.secret) };
    await chrome.storage.local.set({ cred });
    $("pairing").value = "";
    show();
  } catch (e) {
    say(`Nothing answered on port ${m[1]}. Is Lodestar running?`, "err");
  } finally {
    $("pair").disabled = false;
  }
}

async function inject(allFrames) {
  await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames }, files: ["matcher.js", "content.js"] });
}

const CANNOT = "Lodestar cannot run on this page (browser pages, extension stores, the PDF viewer and file:// pages are off limits).";

async function capture() {
  $("capture").disabled = true;
  try {
    let posting;
    try {
      await inject(false);
      [{ result: posting }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => LodestarReadPosting() });
    } catch (e) {
      return say(CANNOT, "err");
    }
    if (posting.error) return say(posting.error, "err");
    const { status, data } = await post(live, "/api/ext/capture", posting);
    if (status !== 200) return say(data.error || `Lodestar answered ${status}.`, "err");
    say(data.duplicate ? `Already on your Board (#${data.id}).` : `Tracked #${data.id}: ${data.company} - ${data.title}`, "ok");
  } catch (e) {
    say(`Lodestar did not answer: ${e.message}`, "err");
  } finally {
    $("capture").disabled = false;
  }
}

async function fill() {
  $("fill").disabled = true;
  $("needs").textContent = "";
  $("frames").textContent = "";
  try {
    let scans;
    try {
      await inject(true);
      scans = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: () => LodestarScan() });
    } catch (e) {
      return say(CANNOT, "err");
    }
    const ok = scans.filter((s) => s.result && !s.result.error);
    const err = scans.find((s) => s.result && s.result.error);
    if (err && !ok.length) return say(err.result.error, "err");
    for (const src of new Set(ok.flatMap((s) => s.result.atsFrames))) {  // a cross-origin ATS form: activeTab cannot reach it
      const b = document.createElement("button");
      b.textContent = `Open the form in its own tab (${hostOf(src)})`;
      b.addEventListener("click", () => chrome.tabs.create({ url: src }));
      $("frames").append(b);
    }
    const frames = ok.filter((s) => s.result.fields.length);
    if (!frames.length) return say("No form fields here that Lodestar can fill.", "err");
    const questions = [...new Set(frames.flatMap((s) => s.result.questions))].slice(0, 100);
    const { status, data } = await post(live, "/api/ext/autofill", { url: tab.url, questions, eeo: $("eeo").checked, salary: $("salary").checked });
    if (status !== 200) return say(data.error || `Lodestar answered ${status}.`, "err");
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id, frameIds: frames.map((s) => s.frameId) }, func: (d) => LodestarFill(d), args: [data],
    });
    let filled = 0, suggested = 0;
    for (const { result } of res) {
      if (!result) continue;
      filled += result.filled;
      suggested += result.suggested;
      for (const n of result.needsYou) {
        const li = document.createElement("li");
        li.textContent = `${n.label}: ${n.hint}`;
        $("needs").append(li);
      }
    }
    const held = data.withheld ? `, ${data.withheld} withheld by the salary-floor guard` : "";
    say(`Filled ${filled} from your profile, ${suggested} from your answers${held}. ${$("needs").children.length} need you. Nothing was submitted.`, "ok");
  } catch (e) {
    say(`Lodestar did not answer: ${e.message}`, "err");
  } finally {
    $("fill").disabled = false;
  }
}

async function show() {
  const got = await chrome.storage.local.get("cred");
  cred = got.cred && got.cred.secret ? got.cred : null;
  $("unpaired").hidden = !!cred;
  $("paired").hidden = !cred;
  if (!cred) return say("");
  tab = await target();
  const host = tab ? hostOf(tab.url) : "";
  $("host").textContent = host ? `This tab: ${host}` : "No web page in this tab.";
  if (LodestarMatcher.linkedin(host)) {
    $("host").textContent = LodestarMatcher.LINKEDIN;
    $("host").className = "err";
  }
  await connect();
}

$("pair").addEventListener("click", pair);
$("pairing").addEventListener("keydown", (e) => { if (e.key === "Enter") pair(); });
$("capture").addEventListener("click", capture);
$("fill").addEventListener("click", fill);
$("open").addEventListener("click", () => chrome.tabs.create({ url: `http://127.0.0.1:${live || cred.port}/` }));
$("unpair").addEventListener("click", async () => {  // this browser forgets; Setup > Browser extension > Revoke ends it there
  await chrome.storage.local.remove("cred");
  live = null;
  await show();
  say("Unpaired here. Revoke this browser in Lodestar > Setup > Browser extension too.", "ok");
});
show();
