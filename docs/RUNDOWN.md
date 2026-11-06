# Lodestar: full rundown

lodestar is a local, AI-assisted job-search operations tool. One Python package, one CLI, one local web UI,
one SQLite file. Nothing leaves your machine except the API calls you configure (AI providers, IMAP, job APIs).

## 1. What it is made of

| Layer | Module | Responsibility | Depends on |
|---|---|---|---|
| Config | `lodestar/config.py` | `~/.lodestar/` paths, `.env` loading, setting lookup (env > vault > default) | stdlib |
| Secrets | `lodestar/vault.py` | OS keyring store for API keys, mail creds, site logins; name index only on disk | `keyring` |
| AI | `lodestar/ai.py` | `chat()`, `ask()`, `ask_json()` over Anthropic + every OpenAI-compatible API; `council()` pools providers and synthesizes | urllib |
| Data | `lodestar/db.py` | jobs, events, watches, seen-keys; status pipeline; stats; follow-up query; thread-local connections | sqlite3 |
| Documents | `lodestar/resume.py` | master profile, per-job tailoring, cover letter, ATS gap JSON, review, Markdown to .docx | `python-docx` |
| Inbox | `lodestar/email_monitor.py` | IMAP scan, keyword prefilter, AI classification, status upgrade rules, auto-created jobs, reply drafts | imaplib |
| Web | `lodestar/web_monitor.py` | career-page diffs with keyword filter; six free job sources (Remotive, Arbeitnow, RemoteOK, HN Who is hiring, Jobicy, The Muse); AI fit ranking | urllib |
| Interview | `lodestar/interview.py` | prep pack (questions, STAR answers, pitch, negotiation); mock-interview REPL | ai |
| Profile bank | `lodestar/profile.py` | saved resumes, pooled skills / languages / roles, LinkedIn import, `candidate_text()` for prompts | ai |
| Apply | `lodestar/apply.py` | answer bank drafts, checklist, follow-up, thank-you, offer review, auto-track | ai, approvals |
| Approvals | `lodestar/approvals.py` | the Inbox: propose, execute, reject; the only code that acts on Lodestar's initiative | db, settings |
| Settings | `lodestar/settings.py` | tool switches (enabled / auto) and preferences in `settings.json` | stdlib |
| Ideas | `lodestar/ideas.py` | idea crafting: diverge across providers, critique, rank, refine | ai |
| Extras | `lodestar/extras.py` | outreach, .ics, digest, Obsidian export, backup, export, research, packet, autofill data | ai, db |
| Loop | `lodestar/loop.py` | the monitor cycle behind `run`, `app` and `desktop` (email, watches, follow-ups, backups) | all |
| Desktop | `lodestar/desktop.py` | native window (Edge WebView2 via pywebview), browser fallback | pywebview |
| Doctor | `lodestar/doctor.py` | install diagnostics (`lodestar doctor`, Setup > Diagnostics) | stdlib |
| Comp | `lodestar/comp.py` | your market-rate table, quoted by gap, offer and prep | stdlib |
| Inventory | `lodestar/inventory.py` | `lodestar features`: the generated FEATURES.md | argparse |
| Support | `lodestar/log.py`, `lodestar/util.py` | rotating log file; safe URL fetches, source reading, alerts, SMTP sending | stdlib |
| CLI | `lodestar/cli.py` | argparse front end, `chat` coach, `ui` launcher | all |
| UI | `lodestar/web.py` + `lodestar/static/index.html`, `app.js`, `app.css` | localhost dashboard; long actions run as background tasks and are polled | http.server |

Data layout: see [SETUP.md, Where things live](SETUP.md#8-where-things-live).

## 2. The workflow it supports

1. **Find**: `jobs search` hits six free job sources, dedupes, filters by must-have keywords, optionally AI-ranks
   against your profile (0-100 with a one-line reason). `watch search-add` turns a query into a standing alert.
2. **Qualify**: `resume gap` scores the posting like an ATS and a hiring manager: match score, missing keywords,
   weak areas, red flags, verdict apply / stretch / skip. Cheap, so run it before spending effort.
3. **Produce**: `resume tailor` rewrites the master resume for the posting without inventing anything (hard rule in
   the system prompt), `resume cover` writes the letter, `--docx` exports an upload-ready file. `--council` runs the
   same prompt through every configured provider and merges the strongest parts.
4. **Apply and track**: `jobs status N applied`. Everything is an event, so the timeline per job is complete.
5. **Monitor**: `email check` classifies replies (interview, rejection, offer, assessment, recruiter outreach) and
   moves the job forward automatically; it never moves a job backward. `watch run` diffs career pages. `run --every 30`
   loops all of it and nudges you about applications that have gone quiet.
6. **Prepare**: `interview prep` builds a pack from the actual posting and your actual history; `interview mock`
   runs a live interview with a scored debrief.
7. **Decide**: `jobs stats` gives response and interview rates so you can see whether the resume or the targeting
   is the problem. `chat` is a coach with the profile and tracker loaded.

## 3. The UI

`lodestar ui` (or the desktop window) serves the dashboard on 127.0.0.1 (port 8765, or the first free port for
`desktop`). Every API call carries a per-launch token and the Host header must be loopback; see
[AUTOMATION.md, Security model](AUTOMATION.md#security-model-of-the-local-ui).

- **Board**: kanban by status, orange edge on anything quiet for `followup_days` (default 7), upcoming interviews,
  add a job from a URL or pasted text. Click a card: timeline, job description, generated documents as tabs, status dropdown, notes, and one-click
  gap / tailor / cover / prep / draft-reply with a council toggle.
- **Inbox**: approve, edit or reject the actions Lodestar queued on its own.
- **Search**: free-API search with keyword filter and AI ranking, "track" button saves a listing with its description.
- **Monitor**: watches (URL or saved search), run watches, check email, email dry-run, live alert log.
- **Ideas**: craft, refine and track ideas across providers.
- **Answers**: application-form answer bank; draft an answer for a job.
- **Coach**: chat with profile and tracker context, council mode; mock interview for a tracked job, with dictation.
- **Profile**: edit the master resume in place, AI review, import, Adjust, profile bank, LinkedIn import.
- **Tools**: per-tool enabled / auto switches and preferences.
- **Setup**: provider readiness and test, model list, local-only preset, keyring vault, market rates, bookmarklets,
  Diagnostics (doctor), Data panel (backup, export, folders).

All AI and network actions run as background tasks (`/api/run/<action>` returns a task id, the page polls
`/api/tasks/<id>`), so the UI stays responsive and a failed provider shows a readable error instead of a hang.

## 4. Multi-AI design

One function, two wire formats. `anthropic` uses the Messages API; everything else (OpenAI, Gemini's OpenAI-compatible
endpoint, Groq, OpenRouter, Mistral, local Ollama) uses chat-completions. Keys resolve from env, then the keyring.
`<PROVIDER>_MODEL` overrides a model, `LODESTAR_PROVIDER` picks the default, otherwise the first configured provider wins.

`council()` is the "pool ideas" primitive: every configured provider answers independently, then the default provider
merges them with instructions to keep the strongest elements and drop contradictions. It is exposed everywhere a
document is produced (`--council`) and as a standalone `council "<question>"` command.

## 5. Safety and privacy choices

- Secrets never touch disk in plain text (OS keyring). `.env` is supported for convenience and git-ignored.
- The resume prompts forbid inventing employers, dates, metrics, or skills. Rephrasing and reordering only.
- Email classification runs only on mail that passes a keyword prefilter or comes from a tracked company, which keeps
  both cost and exposure low. `--dry` shows what would happen without touching the tracker.
- Nothing auto-submits applications. Most job sites forbid it and it measurably lowers response rates.
- The UI binds to 127.0.0.1 only.
- `.gitignore` excludes every personal artifact (profile, database, applications, alerts, snapshots, vault index,
  `.env`) and every development artifact (graph outputs, caches, build dirs), so the repo can be shared safely.

## 6. Current state (2026-11-06, pass 14)

92 offline tests pass (`python -m unittest discover -s tests`). Live-verified: installer, desktop window (Edge
WebView2), every UI route with token and Host checks, six free job sources, page watches, Obsidian export. Not yet
exercised with real credentials: AI calls and SMTP sending. Pass-by-pass history is in [CHANGELOG.md](CHANGELOG.md).

## 7. Roadmap (shipped)

All twelve items below have shipped: 1 capture bookmarklet, 2 autofill bookmarklet, 3 `outreach`, 4 `.ics`, 5 `comp`
market-rate table, 6 `variants`, 7 `template.docx`, 8 `research`, 9 mock interview with dictation (and spoken
questions) in the Coach tab, 10 `digest`, 11 `providers local`, 12 `export obsidian`. Also shipped along the way:
approvals and tool switches, auto-replies, scheduling, follow-ups, thank-you notes, answer bank, checklist, offer
evaluation, listing triage, idea crafting, feature inventory, profile bank. Still open: item 5 fills its table by hand
(`comp set` or Setup > Market rates); nothing pulls ranges from levels.fyi or Glassdoor automatically.

The original proposals, kept for the reasoning:

1. **LinkedIn / Indeed capture via the browser you already use.** Neither has a public API. A tiny bookmarklet or a
   Claude-in-Chrome routine that posts the current page's title, company, and description to `POST /api/jobs` on the
   local UI would close the biggest gap: most real postings live there. Zero scraping risk because it is your own tab.
2. **Application autofill, not auto-submit.** A browser-side form filler fed from `profile.md` (name, links, work
   history, EEO answers) that stops before the submit button. Saves the most minutes per application of anything here.
3. **Recruiter and referral outreach drafts.** `outreach draft --company X --role Y --person "Name, title"` producing a
   short LinkedIn note or email from the tailored resume. Referrals convert several times better than cold applies.
4. **Calendar hooks.** When `email check` classifies an interview with a date, create a calendar event and a prep
   reminder two days before. The Google Calendar connector or an `.ics` file both work; `.ics` needs no auth.
5. **Compensation data.** Pull levels.fyi / Glassdoor-style ranges by title and city into `gap.json` so the verdict
   also reflects pay, and feed the negotiation section of interview prep with real numbers.
6. **Resume A/B tracking.** Hash the tailored resume per application and join it to outcomes in `stats`, so after
   20 applications you know which resume variant actually gets responses.
7. **ATS-safe docx template.** The current exporter is structurally clean but plain. A single `template.docx` with
   named styles (python-docx supports it) gives a better-looking file with no risk to parsing.
8. **Company research pack.** For each interview-stage job: recent news, product, funding, engineering blog, Glassdoor
   themes, pulled by `read_source` and summarized. Pairs with the "questions to ask" section of prep.
9. **Voice mock interview.** Browser speech-to-text in the Coach tab feeding `interview mock`; the hard part of
   interviews is speaking, not typing.
10. **Weekly digest.** A `run` option that emails a Monday summary: new matches, pending follow-ups, interview rate
    trend, and what to do this week. Cheap, keeps momentum.
11. **Local-only mode.** Ollama is already supported; a `lodestar providers --local` preset (model picks + the
    council restricted to local models) gives a zero-cost, zero-data-sharing path for people who want it.
12. **Obsidian mirror of the tracker.** One note per application in the vault with status, timeline, and links to
    the generated documents, so the job hunt sits next to the rest of your knowledge base and is searchable there.

Items 1, 2, and 4 are the ones that most directly raise interview counts; 6 is the one that tells you whether the
rest is working.
