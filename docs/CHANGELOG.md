# Changelog (development passes, newest first)

## Pass 28 (2026-11-13): calendar busy times, research for every kind of job

- New preference calendar_freebusy (off by default): interview replies and the slots Lodestar proposes avoid the times
  your Google Calendar shows busy. Turning it on makes the next Google sign-in also ask for free/busy access only (no
  event titles, nothing written). Without it, or without a Google sign-in, nothing changes and the reason is logged.
- The interview research pack and its web search look for a team's stack and engineering culture only for computer and
  engineering occupations; for every other job they look for its ways of working and culture.

## Pass 27 (2026-11-13): more resume formats, disputed facts, the claim check

- Resume import also reads .odt (OpenDocument), .rtf and .html files. A PDF with no text layer (a scan) is refused
  with what to do instead; nothing is guessed from it.
- `lodestar profile dispute KIND VALUES...` marks a fact in your profile bank as wrong: it stays in the bank but is
  left out of the master resume, studio versions, letters and career suggestions until you clear it (--undo).
- Studio versions show a Claim check: every claim beside the fact it cites, marked as written, reworded (checked
  against your facts) or put back by the guard with the reason.

## Pass 26 (2026-11-13): source capabilities, coverage, posting freshness, application stages, submitted copies

- Every job board declares what it can do (search, full descriptions, how you apply, keys, regions): none is an apply
  API, applying always happens on the posting's own page. Every Jobs search now says which boards were asked, which
  failed and which need a key, and that coverage is partial.
- The job drawer shows when the posting last answered (its feed listed it or its page was up). The apply agent never
  submits by itself for a posting that looked removed: it fills it and you decide.
- Applications have fine-grained stages (acknowledged, recruiter screen, assessment, technical / panel / final
  interview, references, negotiation, on hold, no response, position closed, declined offer ...) on top of the board
  columns, and every move is kept in a stage history: who moved it (you, or Lodestar with its tool and Inbox item) and
  on what evidence (the mail it read, the apply run). The history cannot be edited. `lodestar jobs stage ID STAGE`.
- When a job moves to applied, the resume, cover letter and form answers as they were are copied to the job's
  submitted/ folder with a SHA-256 manifest; later edits never touch them.

## Pass 25 (2026-11-13): one policy for every automatic action, and an audit log

- Every action a tool proposes now goes through one deterministic policy (no AI decides): allowed (the tool is on auto
  and nothing needs you), waits for you (the Inbox), or blocked, always with its reasons.
- Some things always wait for you, whatever a tool's auto switch says: a withdrawal or acceptance, a scheduling
  commitment (an interview slot), mail to a job at the offer stage (offers and negotiation), a reply to a sender
  Lodestar could not verify, and mail with attachments.
- The apply agent never submits by itself for a licensed occupation (nursing, law, CDL driving, trades ...): it goes
  to review.
- Setup > Audit log and `lodestar audit`: every decision and every action that ran, newest first, with the reasons in
  words. The log cannot be edited or deleted (the database refuses it).

## Pass 24 (2026-11-13): eligibility gates, career class on every job, Explore further

**Hard requirements are no longer hidden inside the fit score**
- Work authorization / visa sponsorship, a security clearance, a license or certification the requirements name, and
  your own excluded companies, title words and deal-breakers are now eligibility gates: each is met, not met or
  unknown, and unknown never counts as met. They are listed in the job drawer under "Hard requirements (kept out of
  the score)". The fit score is the same with or without them; a job with a gate not met is still marked blocked.
- Every job and listing shows its career class (Qualified now, Competitive with framing, Bridge required,
  Longer-term development, Currently ineligible, Insufficient evidence) beside the fit, and the drawer shows the fit's
  confidence (how much of it could be measured).
- auto_track never adds a job with an unknown hard requirement by itself (it waits in the Inbox, even on auto), and the
  pipeline's fit check keeps Autopilot away from it ("needs you: ... unknown"); a click still runs the next step.
- Every stored fit is re-scored once (fit.json version 2).

**Explore further (Careers tab, `lodestar careers explore`)**
- One AI call suggests occupations from what interests you and your profile (never your salary floor). Each is
  matched to O*NET by title; one O*NET does not know stays, marked "AI-suggested unmapped role: review".

## Pass 23 (2026-11-13): career discovery foundation (blueprint v1.1, first vertical slice)

**Your resume is evidence, not a boundary**
- New Careers tab and `lodestar careers`: the occupations your profile points to, from the O*NET 31.0 occupation
  database (1,016 occupations, bundled; Source: O*NET 31.0 Database by the U.S. Department of Labor, Employment and
  Training Administration, used under the CC BY 4.0 license).
- Your past titles map to O*NET occupations by O*NET's own title lists (never a guess). Their related occupations
  become expansion tiers: Equivalent roles, Closely related, Transferable fit, Longer-term pathway; the fields you
  choose are Requested targets, with Bridge opportunity roles into them when they need more preparation than you show.
- Each suggestion has a career class (Qualified now, Competitive with framing, Bridge required, Longer-term
  development, Currently ineligible, Insufficient evidence) from O*NET's Job Zones against yours, and says why it
  fits, what is missing, what does not transfer and how to close the gap. Licensed occupations (nursing, law, CDL
  driving, trades ...) carry a licensing warning and are never "Qualified now" without a matching credential.
- Career tracks: any field, even one your resume does not show. A desired field searches its own words only until you
  turn on Equivalent roles; nothing is broadened silently. Searching a track shows which job boards were asked, which
  failed and which need a key, and always says coverage is partial.
- Deliberately later (pass 24): hard eligibility gates kept apart from the fit score, the class on job cards, AI open
  exploration.

## Pass 21 (2026-11-11): fit score, sourcing everywhere, alerts, listing monitor, chance boosters

**Fit score: how well a job suits you, 0 to 100**
- Every job and every listing gets a fit score without any AI: your skills against what the posting requires (and,
  separately, what it only calls nice to have), the role and level, the years it asks for against yours, the place,
  and the pay against your private floor (pay under the floor lowers the score; it never blocks a job, and the floor
  itself never appears anywhere). Chips say why ("missing kubernetes", "remote OK", "possibly stale").
- When too little can be measured (a listing with a title only) the score leans toward 50 and says "partial".
- It shows on the board card, in a Fit column (the old Match column is now Coverage, right after it), in a Fit group in
  the job drawer with every part, its weight, and "Why not higher?", and as a "best fit" sort. AI fit adds one AI
  judgement as one part when you click it. Tools > Preferences > Fit weights changes the weights (`pay=0` switches a
  part off and now reads "pay=0 (off)"); Reset weights goes back to the defaults.
- `lodestar fit ID` prints the breakdown; Insights now shows the response rate by fit score.
- Headings such as "Nice to have" or "Preferred qualifications" are read from job pages too, so those skills no longer
  count as required (no false "missing" chips or "close a gap" suggestions).
- The interview-readiness chance band is now capped by the fit.

**One Jobs tab for every site**
- The Search tab is now **Jobs**: one All jobs list of every listing any source found (job APIs, saved searches,
  company boards, the browser extension and job-alert emails), merged when several sites list the same posting, with
  source chips, "new since your last visit", Track, Dismiss and AI fit. `lodestar jobs all` lists it too.
- New sources: Himalayas, We Work Remotely, and Adzuna and USAJOBS once you add their free keys (Setup > Job sources).
  SmartRecruiters, Recruitee and Personio company boards work where the employer made them public.
- Each board is asked only as often as its terms allow (Remotive about 4 times a day, Jobicy once an hour), and that now
  holds across restarts and separate `lodestar jobs search` runs: inside the window Lodestar reuses the last answer it
  saved, or skips the board.
- Two openings with the same title at one company (different posting ids) now stay two rows; the second is no longer
  called a repost of the first, and the first job's fit is no longer lowered for it.
- Without an AI key, strong rules-only matches are proposed for tracking (at most 10 a day); those proposals always
  wait in your Inbox, even when the tool is set to auto.

**Job-alert emails**
- With email connected, LinkedIn, Indeed, Glassdoor and ZipRecruiter job alerts in your own inbox are read into All
  jobs (Setup > Job alerts, on by default). Only mail from the site's known alert address that passed DKIM/DMARC
  counts. Alerts are never sent to the AI, never stored as mail, and their links are never opened by Lodestar; sign-in
  tokens are stripped from the links that are kept. Check email now says how many new listings the alerts held.
- LinkedIn's "your application was sent" mail is no longer mistaken for an alert: it is read as an application
  confirmation again.
- `lodestar email parse-alert FILE.eml` shows what Lodestar reads from a saved alert.

**Listing monitor**
- Once a day Lodestar checks the posting of every open tracked job: changes to the title, place, pay or description
  (with a diff saved in the job folder; your JD is replaced only when you click Use live description), removals (two
  misses in a row first; a saved job gets a withdraw proposal, an applied one a Today item) and reopenings. LinkedIn,
  Indeed, Glassdoor, ZipRecruiter and links from alert mail are never fetched.
- Confirmation and status mail from applicant systems (Greenhouse, Workday, iCIMS and others) is filed under the right
  job with the reason it was linked; it never counts as trusted and its status changes always wait for you.
- The drawer's **Listing activity** shows it all in one timeline: posting checks, alert sightings and mail.

**Job intelligence and chance boosters**
- The drawer's **Job intelligence**: company facts and recent news from the company's own site and Wikipedia (only on
  your click, robots.txt respected, never a job board), hiring signals from your own listing history, the role and pay
  context, each with its source and date; an AI summary keeps only lines that cite a source.
- **Chance boosters**: specific actions ranked by expected effect (high, medium, low; never a number), such as apply
  while the posting is fresh, ask a contact for a referral, tailor to the missing must-haves, close a named skill gap,
  follow up on time, prepare the stories the company stresses, fix resume issues, and where your own response record
  is better. Each has a button into the feature. "More from AI" adds up to 3 more, each with its basis; anything that
  states odds or a multiplier ("4x more likely") or cites a source or posting text that does not exist is dropped.
- Today and Insights list the best boosters across your search; `lodestar boosters` and `lodestar intel ID` do the same.

**What you need to do**
- Save one real LinkedIn and one real Indeed alert email (as .eml) and run `lodestar email parse-alert FILE.eml`: the
  alert formats were built from made-up samples, so a real one confirms the parser (a missing sender is a one-line fix).
- For Adzuna and USAJOBS results, add their free keys under Setup > Job sources (`lodestar keys link adzuna` /
  `usajobs`).

## Pass 20 (2026-11-11): browser extension, market pay data, command palette, restore

**Browser extension for Edge and Chrome (replaces the bookmarklets)**
- Load the `extension` folder once (`edge://extensions` > Developer mode > Load unpacked), then Setup > **Browser
  extension** > **Pair a browser** and type the string it shows (like `8765-K7QX-M2PD`) into the extension's popup.
  Setup clears the string as soon as the browser pairs and lists the browser; each string works once.
- **Capture this posting** puts the job you are looking at on the Board, with the company, location, date and pay
  the page itself publishes. **Fill this form** types your contact details, work history and saved answers into the
  empty fields of an application form, highlights what it filled and lists what needs you (radio buttons, file
  uploads, dates, unclear dropdowns). It never clicks, submits or ticks anything. EEO answers and your desired salary
  go only when you tick them for that fill; your salary floor and private answers never do.
- Never on LinkedIn: its User Agreement bans add-ons like this, so the extension does nothing there.
- Each request from the extension is signed with a secret only that browser holds, and the signature names the port
  it was sent to, so another program on your PC listening on one of the ports the popup tries cannot pass its
  requests on to Lodestar and read your answers. Setup > Browser extension > **Revoke** ends a pairing.
- The bookmarklets turn off once a browser is paired (Setup > Browser extension > Bookmarklets turns them back on).

**Command palette (Ctrl+K)**
- Press Ctrl+K (Cmd+K on a Mac) anywhere: type a few letters of a tab, a job (company or title), a contact, a document
  or a setting, or an action (Add job, Check email, Run watches, Recommend on this tab, Open Today), then Enter. Arrows
  move, Esc closes and puts you back where you were. The letters only have to appear in order ("orch staff" finds
  Orchid Health - Staff Data Engineer). Works with the keyboard alone and with a screen reader. Check email and Run
  watches leave the keyboard on their button, and the Master resume is offered only once you have built one.
- Any button that runs a background job gives the keyboard focus back to itself when the job finishes.

**Restore from backup**
- Setup > Data > **Restore from backup** (or `lodestar restore ZIP`) puts your data folder back to a backup: the
  tracker, profile, settings, answers and documents; files made since are removed. A safety backup of what is there
  now is taken first (`before-restore-*.zip`), and the backup must pass its checks (only the files a backup holds, no
  path tricks, size limits, a database that opens and passes its integrity check) before anything changes. Refused
  while the monitor loop is mid-cycle, mail is being sent or scanned, an update runs or another Lodestar window is
  open. AI keys, the mail sign-in and paired browsers live outside backups and stay as they are, whatever spelling a
  zip uses for them (`Extension.json`, `.ENV`, `Backups\`); zips with Windows short names (`EXTENS~1.JSO`) are refused.
- Backups no longer carry `capture.token`, `update-state.json` or `procs\` (running-process markers).

**Market pay from the Bureau of Labor Statistics (opt-in)**
- Turn it on once (the drawer's **Turn on market pay**, or `lodestar tools set market_pay on`): every job then shows
  what employers in its area pay its occupation, as public BLS percentiles (10th to 90th and the mean). Off, Lodestar
  never contacts BLS.
- The board card gets a "market median" chip; the drawer's **Market pay (BLS)** group draws the percentiles with the
  posting's own pay over them and says where it sits; Insights > Offers adds a BLS row with where each base sits.
- A counter-offer can cite the public median or 75th percentile for the job you are countering, as public data (never
  as another offer, never your floor); Lodestar refuses a figure at or below their base. Interview prep, the gap check
  and offer evaluation see the figures too.
- The occupation comes from the job title (or your pick, or your AI's pick from a fixed list when you click), the area
  from the location (metro, else state, else national; remote jobs use your home area). Both always show next to the
  figure, with what the figure is not: not the company's band, base pay only, and it lags the market. Jobs outside
  the U.S. get no figure, even when their country code matches a state ("Berlin, DE" is not Delaware).
- Only occupation and area codes go to api.bls.gov. 25 queries a day without a key (500 with a free `BLS_API_KEY`),
  cached until the next yearly release. `lodestar comp market ID` shows it on the command line, `lodestar doctor` the
  state and today's count.

## Pass 19 (2026-11-11): AI recommendations, Full AI and AI helpers

Ask the AI to suggest edits to your own content in any tab, apply the ones you like with one click, let it apply
everything safe on its own, and take any of it back.

**An AI toolbar on every tab and card**
- Profile, the profile bank, a job's Details and Documents, the answer bank, STAR stories (the list and each story),
  Contacts (the tab and each contact), Search and Monitor (saved searches), Today, Insights and the Inbox (each email
  waiting for approval) have the same four buttons: **Recommend**, **Apply suggestions**, **Full AI** and
  **Undo AI changes**. This is about your content only, never the app's own code or settings.
- **Recommend** makes one AI call and shows a card per suggestion: what the text says now and what it would say
  (removed lines struck, added lines marked), the reason, and how big and how risky the change is. Nothing changes yet.
- **Apply suggestions** writes the cards you ticked. (It is a different button from the profile import's
  "Apply selected", which keeps its meaning.) A card whose text you changed since is skipped as stale.
- **Full AI** asks the AI for suggestions and applies every one that passes the safety checks. The first time it asks
  you to confirm and explains what it will never do: send mail, submit anything, change a job's status, add a job,
  approve or propose an Inbox item, add a watch, or touch automation, privacy, provider settings or your saved keys.
  Those are blocked in code while it writes, not only in the prompt. An Inbox draft it improves still waits for you.
- **Undo AI changes** puts the last batch back exactly. A field you edited since keeps your version.
- Setup > Data > **AI changes** lists every batch (Apply suggestions or Full AI, when, what changed, before and after)
  with an Undo per batch.
- Today and Insights give advice only; new saved searches and companies to watch are suggestions you add yourself.

**Safety checks on every change**
- Text an employer reads (profile, resume, cover letter, form answers, answers, stories, emails) gets no invented
  facts: no new skill, number, title, degree, name, link or pay figure your profile does not already state. Your
  salary floor and Preferences never get in.
- Eligibility and EEO answers and answers you marked private are never sent to the AI or changed.
- A form answer cannot add a new question to the form, and the "check this" note the pipeline puts under an answer it
  was unsure about always stays; such an answer gets no credit for its own claims.
- A job's details and a contact cannot gain a link, email address or phone number they did not have, so an
  instruction hidden in a job posting cannot slip its own contact details into your to-dos; notes keep every line you
  wrote (the AI may add lines).
- Job postings, emails and company pages go to the AI marked as data, never as instructions.
- Text you typed and have not saved is never thrown away: the job drawer keeps it (a message says the AI change is
  saved), and on Profile the message tells you Save waits until the editor matches the file (Undo AI changes makes
  Save work again).

**AI help menus**
- Each area has a folded **AI help** menu with one-click helpers, one AI call each, that only answer and change
  nothing: What to do next and Plan my day (Board), Summarise the posting, Red flags, Questions to ask them, Likely
  interview topics and Map my stories to this job (a job), Who to ask for a referral (Contacts), Draft an intro (a
  contact), Fill STAR from my notes (a story: its suggestions land in the story's toolbar for you to apply), Explain my
  numbers (Insights), Suggest search terms (Search), Companies like my targets (Monitor) and Explain this setting
  (Setup and Tools).
- Without an AI provider every AI button says it needs one; a local Ollama model counts.

**Terminal**
- `lodestar advise SCOPE [TARGET]` recommends, `--apply IDS`, `--auto` (Full AI), `--undo BATCH`, `--history`,
  `--list`. `lodestar ai-help [NAME [TARGET]]` runs a helper or lists them.

## Pass 18 (2026-11-11): interview readiness and company-referenced questions

Practise with the questions this company is known to ask, see how prepared you are for each interview, and get a
plain chance estimate that never pretends to be a probability.

**Questions the company is known to use**
- Every practice question now says where it came from, best-founded first: a question you logged in one of your own
  rounds, one in notes you pasted (for example interview reviews you read yourself), one based on the company's own
  public hiring and values pages, one from the job description, and only then the general bank. Questions an AI
  "reports" a company asks are off unless you turn on Settings > Reported interview questions, and are always labelled
  "Reported, unverified".
- Lodestar reads the company's own website for this: the job link's site when it is registered under the company's
  name (never a job board or an applicant-tracking site), or the website you type in the drawer. It respects
  robots.txt, makes at most 12 requests per company, and reuses what it read for 30 days. LinkedIn, Indeed, Glassdoor,
  ZipRecruiter, Blind and SimplyHired are never opened; a link you paste with your notes is kept as a citation only.
- One AI call turns your notes, the pages and the job description into questions, and Lodestar checks every one
  against the exact words it quotes. The AI cannot claim you were asked something, or that the company asks it.
- The drawer has a **Question sources** group (website, pages read, your pastes, a paste box, Refresh) and a
  **Questions** list by competency. CLI: `lodestar interview questions / sources / paste / site / unsource`.

**Mock interviews use them**
- The mock interview picks each question itself, word for word from that set: your logged, pasted and company-page
  questions first (the ones you have not answered in an earlier session before the ones you have), a motivation
  opener, then the areas the company's material stresses most. Coach > Mock interview has a **Focus** choice, shows
  where each question came from, and each score card says which question and area it scored.

**Readiness and the chance estimate**
- Each job in screening, interview or offer gets a readiness score from 0 to 100 that measures your preparation only:
  your mock answers, which areas you have practised, your STAR stories, how many of the company's own questions you
  have practised, and the prep and research packs. Every part shows its reasons, and **Raise it** lists the three
  things that would add the most points.
- The chance estimate is a band (low, fair, good or strong), never a percentage, and always says "not a probability".
  Once 8 of your rounds have a recorded result (with at least 2 passed and 2 not), Insights shows your own record per
  band as plain counts. Readiness never goes into anything an employer reads.
- Today shows the readiness of an interview coming up, with the top tip when it is under 60. CLI:
  `lodestar interview readiness ID` and `lodestar interview calibration`.

**Fixes before release**
- A company page that redirects to another site (often a job board) is no longer read as the company's own page;
  a redirect is followed only on the company's site and only when that page's robots.txt allows it, and every redirect
  counts toward the 12-request limit.
- Job-board and applicant-tracking sites such as BambooHR, Recruitee, Breezy, Teamtailor, We Work Remotely or
  AngelList are never taken for the company's website, even when the company's name appears in their address.
- A company website on its own port (for example `http://acme.example:8080/`) is read on that port.
- A prep pack can no longer show a question as "logged", "from the company's page" or "reported" unless the practice
  set really holds it from that source; anything else reads [AI-written].
- Deleting a paste (or changing the company website) also removes the practice questions built from it.
- Refreshing the company's pages, when nothing on them changed, no longer marks the prep pack out of date, and the
  prep step is no longer out of date straight after its own first run.
- A logged "Why <Company>?" counts as a motivation question, so it is asked first; another company's "Why Orchid?" is
  never asked. With a Focus that has run out of questions, the mock says so and never repeats the question it just
  asked.
- The "Prep pack and research" part now says when its points come from the company's own questions; with 8 or more
  results but too few passes (or too few non-passes) the record says exactly what it is waiting for.
- A resume saved with a byte-order mark by another editor keeps the name as its heading in the .docx, PDF and preview.
- Carried over from pass 17.1: imported .md and .txt files saved by Notepad with a byte-order mark no longer start with
  a stray character; a role written as "Title | Company | City | Jan 2021 - Present" keeps its company after a title
  change; `lodestar resume audit` on master.docx no longer reports "a very long name".

## Pass 17.1 (2026-11-10): credential isolation and fixes

**Upgrading with your own `LODESTAR_HOME`?** If you set `LODESTAR_HOME` to a folder other than `~/.lodestar`, your
keys and mailbox were saved under the shared keyring name and that folder no longer sees them: AI falls back to the
offline templates and mail checks stop. Link your keys and mailbox again (Setup), or set the environment variable
`LODESTAR_VAULT_SERVICE=lodestar` to keep using them. `lodestar doctor` WARNs on the `vault namespace` line and names
what is missing. The default `~/.lodestar` needs nothing.


- Each data folder has its own keyring namespace. Only the default `~/.lodestar` uses the keyring service `lodestar`
  (with the old `jobbot` fallback); any other `LODESTAR_HOME` uses `lodestar:` plus a hash of its path and can no
  longer read or change the real keys and mail password. `LODESTAR_VAULT_SERVICE` sets a fixed name on purpose;
  `lodestar doctor` shows the active one. The update gate's test run and the unit and browser test suites never
  inherit a fixed name, even from a `.env` line.
- Linking **Ollama (local, no key)** under Setup > Link an AI key now shows it linked: the link saves its model, but
  only when Ollama answered. A link while Ollama is not running saves nothing, so the offline templates keep working.
  **Remove** on the Ollama row (`lodestar keys rm ollama`) now unlinks it. A saved model no longer leaks into the
  shared preference defaults.
- The document viewer's **Open in new window** asks before writing a resume with lines your profile does not support,
  like a download and Save document already did (it used to skip the question).
- `lodestar doctor` warns on a null or fail keyring backend again (both are classes named `Keyring`; the row now names
  the module, for example `Windows.WinVaultKeyring` or `null.Keyring`).
- docs/SETUP.md re-checked against the final pass 17 code (import review, master resume card, studio formats, the
  viewer's Save prompt and Format panel, PDF engines) and the keyring namespace; CONNECT.md and `.env.example` updated.

## Pass 17 (2026-11-10): resume import, master resume, resume studio, document viewer

Import a resume or LinkedIn export into a review and keep every section of it; a master resume that follows your
profile on its own; an AI resume studio that builds PDF / DOCX / text resumes from your own facts in the look you
choose; and one viewer with real pages and a formatting panel for every document Lodestar writes. The parts below
list each in detail.

**Fixes before release**
- Saving an edited resume in the viewer now asks first when a line says something your profile does not (a new
  employer, title or number), the same as exporting does. Every changed line is checked, however long the edit.
- A resume the studio writes may say "N years of experience" (counted from your first role), but that number is
  no longer accepted anywhere else in the text (for example as a team size).
- "Use for this job" with a studio version built before you changed your profile now shows "Profile changed" on the
  job (and marks the pipeline's Tailor step stale) instead of hiding it.
- When resume.pdf is open in another program, "Use for this job" stops before changing anything, so the PDF that mail
  attaches always matches the resume text. Saving or re-tailoring a job's resume prints its PDF again (or removes it
  when no PDF can be printed) instead of leaving an older PDF beside the new text.
- The pipeline's Tailor step no longer spends a second AI call when only one is left in the day's budget: it shortens
  the resume without the AI instead.
- Importing a resume no longer adds roles, bullets, skills, education or your LinkedIn link to profile.md a second
  time when profile.md already shows them, and "Re-read my master profile" only fills the profile bank.
- Bulleted awards, publications and certifications read by AI are no longer flagged "quote not found".
- A date that only gets more precise ("2021" to "Mar 2021") is an update, not a conflict, so the new bullets that come
  with it are no longer dropped; a conflict you keep as yours still takes the bullets you ticked.
- The Profile tab's master resume card now updates by itself after a background rebuild ("Building from your
  profile shortly…", then the new date), and whenever you open the tab.

### Part 3 (2026-11-10): a viewer and formatting for every document

**Document viewer**
- The master resume, studio versions, tailored resumes, cover letters, form answers, offer notes, interview prep,
  research and a counter-offer draft all open in one viewer: real pages (Letter or A4, your margins, page numbers),
  zoom, page count and an over-the-limit marker, the actual PDF Edge prints, a Word-layout preview, the exact TXT and
  MD, print, open in a new window, download every format, and compare two versions side by side.
- A formatting panel with a live preview: template, font, sizes, accent, margins, line and paragraph spacing, page
  size and limit, density, date format, bullet style, contact line, headings, and sections you drag to reorder or hide;
  letters get date line, recipient and signature options. Kept per document; "Save as my default look" and "Reset to
  template".
- Edit any section beside the page (click a heading to jump there). Exports re-check the salary floor every time, and
  resume lines your profile does not support ask before export.
- Download buttons now work in the desktop window too.

### Part 2 (2026-11-10): the AI resume studio

**Studio tab**
- Describe the resume you want ("one page, lead with leadership, navy accent, drop the 2015 job"), aim it at a
  tracked job or a pasted job description, and set any formatting: template, font (ATS-safe list), size, accent,
  margins, line spacing, paper, date format, contact line, heading case, density, page limit, sections in order with
  show / hide, bullets per role, entries to leave out, formats. You get PDF (printed with Edge), DOCX, plain text and
  markdown, a preview, the page count, JD coverage and the ATS checks.
- The AI only chooses and rewords: employers, titles, dates, schools, degrees, certifications and contact details are
  copied from your profile, and any sentence it writes that adds a number, a tool, a title, a link or personal data
  goes back to your own words. You see each such correction.
- Over the page limit, the AI shortens once, then the oldest bullets and optional sections are cut until it fits.
- Refine a version with a follow-up ("shorter"); every version is kept with Open and Delete; "Use for this job" makes
  it the job's resume; "Make this my default look" keeps the look. Works without AI too (Build without AI).
- `lodestar resume build / versions / open / catalogue`; the drawer has "Build in Studio".

**Pipeline**
- The Tailor resume step now uses the studio, and reads stale only when a part of your profile that resume used
  changed (the same rule as the drawer badge).

### Part 1 (2026-11-10): full resume import and the profile-synced master resume

**Import with review**
- An imported resume (or LinkedIn export) is read into a review instead of straight into your profile. Each fact
  shows as new, changed, conflict or duplicate, with the line it came from; you accept them one by one or with
  "Accept all new", and choose keep mine / use incoming / add separately for conflicts.
- Every section is kept now: awards, publications, volunteering, patents, talks, links, interests and any other
  section, plus locations, technologies, honors, credential ids and expiry dates.
- Plain-text resumes are read much better offline: "Title | Company | City | dates" lines, two-line headers,
  "Title at Company", degrees with field and school, certifications with issuer and id.
- Facts read by AI are checked against the file; anything not found there is flagged and starts unchecked.
- Personal details (date of birth, ID numbers, photo, pay, references and the like) are never stored or sent to an AI.
- Accepted facts are also written into profile.md, in the right section, with one snapshot. Saving the editor after
  an import changed profile.md is refused instead of erasing the imported lines. "Re-read my master profile" fixes
  older one-line education entries.

**Master resume**
- resumes/master.pdf / .docx / .md / .txt follow your profile automatically (offline, a few seconds after a change),
  with a "what changed" line and warnings for sections that may be private. Profile tab > Master resume.
- A tailored resume shows "Profile changed since this resume was made" only when a section it used changed; it is
  never rewritten on its own.
- PDFs are printed with Microsoft Edge (or Chrome) when no Word or LibreOffice is installed, so Export PDF writes a
  real PDF on every Windows 11 machine; ligatures are off so parsers read the text correctly.
- `lodestar doctor` names the PDF engine; CLI output no longer crashes on accented characters in a piped console.

## Pass 16.5 (2026-11-10): step-by-step pipeline automation

**Pipeline**
- Every job now has 13 steps, from the fit check to closing it out. Each step uses what the earlier ones produced
  (the cover letter reads the tailored resume and the research; form answers read both; prep reads the next round;
  thank-yous name the interviewers; follow-ups carry the application date and confirmation number).
- When something a finished step was built from changes, the step is marked stale. It is never redone without you.
- A step that lacks a fact asks you once. One answer covers every job that asks the same question, or only this job.
  Eligibility, work-authorization and EEO questions are never answered by AI; private answers never reach employers.
  However a form words them ("legally eligible to work in", "18 years or older"), Lodestar recognises them. Such an
  answer is filled in on a form only when you wrote it yourself (under Answers, or by answering the question), and
  it is never shown to an AI, even when you saved it without a tag. An answer you saved before this update for one
  of these questions is asked once more, so you can confirm it.
- Questions that only look alike stay apart: "pending criminal charges" is not "convicted of a felony", "sex
  assigned at birth" is not "gender identity", and "start date of your current role" is not your earliest start date.
- Re-running Form answers looks every saved answer up again: a changed answer is used, and one you have since marked
  private is asked for instead of being copied.
- A fact you give for one job only (when the AI asks for one) is used in the redraft of that answer.
- In the app: the job drawer's Pipeline group (step strip, Run next step, Run to, Re-run / Retry / Skip, Continue
  anyway past a "skip" fit verdict, form questions, run log), a Next step chip and column on the Board with bulk runs,
  and Questions for you at the top of the Inbox. In the terminal: `lodestar pipeline`.

**Autopilot**
- Off by default (top-bar pill, Setup > Autopilot). When on, the monitor loop moves jobs along within AI budgets (6
  calls a cycle, 30 a day, 3 jobs a cycle). Steps not set to auto ask once per job in the Inbox. Nothing is sent,
  submitted or moved without its own approval.
- A batch you approve in the Inbox spends from the same daily budget; when the budget is used up, the rest waits and
  Setup > Autopilot says so. The Inbox card's AI-call estimate counts each form question the batch will draft, and
  the card lists the saved answers it will fill in on the form (work authorization, sponsorship and so on).
- The budget message says which limit was reached: this cycle's or the day's.
- Building documents (fit check, research, tailored resume, cover letter, interview prep), by a click or a step, no
  longer pushes back the date a follow-up is due.
- Only a confirmation mail Lodestar trusts marks the Confirmation step done, and only its reference number is quoted
  in a follow-up.
- The Follow-up step says no follow-up is needed while an interview is booked.

**Fixed**
- A bulk Run next step reported jobs with nothing ready as errors (red, with the job number twice). They are now
  counted as "had nothing ready".
- A drawer button refused while a step runs said "Autopilot is running this step" even when your own run held it.
- Rejecting an Autopilot batch now clears "waiting on you" from the Board at once.
- A question asked for a job you deleted while its step was running no longer stays in the Inbox.
- Saving a setting could fail on Windows while another part of the app was reading the settings file at that moment.

## Pass 16.4 (2026-11-09): auto-update

**Updates**
- Lodestar can now update itself. `lodestar update check` shows the commits and these changelog notes an update
  would bring; `lodestar update apply` backs up your data, moves the install forward, runs the tests on the new code
  and puts the old version back if anything fails. `lodestar update status` and `lodestar update log` show what
  happened, and so does `lodestar doctor`.
- The monitor loop checks once a day (preference `update_every_hours`). Preference `update_mode`: `notify` (the
  default) tells you when an update is out, `auto` applies it, `off` never checks.
- An update is never applied while the install folder has changes or commits of its own, or while a mail scan or a
  send is running. Updates come only from an https:// origin.
- The standalone .exe only tells you a new version is out and where to download it.
- In the app, Setup > Updates: choose off / notify / auto and how often to check, Check now (the commits and what's
  new), Update now (asks first, then shows progress and the result), a Restart button in the desktop app, and the
  update log. A badge at the top says when an update is out or a restart is needed; a failed update shows under
  Getting started.

**Update safety (fixed before release)**
- If Lodestar is closed, killed or loses power in the middle of an update, the next start puts the previous version
  back and says so in the update log, instead of quietly running code that never passed its tests.
- Restart is no longer possible while an update is still running; the Updates card says an update is in progress and
  brings Restart back when it ends.
- When an update fails half-way through (for example because another program held a file open), the install folder
  is put back exactly as it was, so later updates are not blocked by leftover files. If even that fails, the update
  log and `lodestar doctor` say so plainly (a FAIL line) with the one command that fixes it, and the next start
  tries again.
- A test run that hangs can no longer stall the update: after the time limit every process it started is stopped.
- A failed update now names the tests that failed.
- A release that was withdrawn from the origin is no longer offered or installed.
- In auto mode, a version that failed its tests is tried only once (no new backup and test run every interval); you
  get one alert, and `lodestar update apply` tries it again by hand.
- An update is not applied while another Lodestar window, app or loop is running, since that one would otherwise run
  a mix of old and new files. Update from that window, or close it first.
- A running Lodestar keeps showing the screens it started with until you restart it, even while an update is being
  tested on disk.
- When Update now is refused (the origin moved since your check, or another update is running), the card says why,
  clears the old plan, and the refusal is in the update log.

## Pass 16.3 (2026-11-09): browser test suite and full test list

**Browser tests**
- 120 tests now drive the real app in a browser: every tab, the Board, Today, the job drawer, Search, Monitor, Inbox,
  Contacts, Insights, Profile, Answers and stories, Ideas, Coach, Setup and Tools. Each runs against its own throwaway
  data folder with made-up data, and every outside service is faked: no AI, mail, sign-in or job-site call leaves the
  machine, and your own `~/.lodestar` is never touched.
- Run them with `pip install -e .[e2e]`, then `python -m unittest discover -s tests/e2e -p "e2e_*.py"`. They use the
  Microsoft Edge you already have; CI runs them in Chromium. Without Playwright they are skipped, not failed.
- Any console error fails a test, and a failing test leaves a screenshot and the page in `tests/e2e/_artifacts/`.

**Full test list**
- [TESTS.md](TESTS.md) lists every feature with the tests that cover it, by name. A check fails when a row names a
  test that does not exist, when a test is listed nowhere, or when a row disappears. Combined coverage of both suites
  is in TESTS.md too.

**Fixed (found by the browser tests)**
- Insights tables and the Board's table view no longer push the whole window sideways on a narrow window; the table
  scrolls on its own.
- A bad preference value now names the preference in the error instead of `***`.
- A blank application-form question is refused before any AI call, and no empty "save answer" item reaches the Inbox.
- When the mail server drops the connection during Connect & test, Setup now says so ("test again in a minute")
  instead of telling you your app password was refused.

**Test reliability**
- Board drags now always move the card you meant (a long column could make the browser pick up a different card).
- Tests wait for each tab's own data to load, which fixed a failure that only showed in Chromium.
- Checks that could not fail now can: the token and Host protection, the 1280px layout, STARTTLS on custom mail
  servers, "an AI call happened", and "an empty chat message sends nothing".

## Pass 16.2 (2026-11-07): connections - keys, email sign-in with 2-step verification, attachments

How to link everything, step by step: [CONNECT.md](CONNECT.md).

**AI keys**
- Setup > **Link an AI key**: pick the provider, paste the key, click Link. Lodestar checks it at once by listing the
  provider's models, so the check costs nothing. Terminal: `lodestar keys link anthropic`, `lodestar keys`,
  `lodestar keys check`, `lodestar keys rm NAME`.
- Every time the app starts, keys and the mailbox are re-checked in the background (it never slows the start). Being
  offline shows "Couldn't reach", never "broken". A quota or rate limit shows as Failed (quota), and AI features stay on.
- Getting started names a key that stopped working, and an email problem.

**Email: sign in with Google or Microsoft**
- Sign in on Google's or Microsoft's own page in your browser, so every 2-step method works there: authenticator apps,
  SMS, phone prompts, passkeys, security keys. Lodestar keeps only a refresh token in the OS keyring, never your
  password or your codes.
- Outlook.com, Hotmail, Live and Microsoft 365 now work (Microsoft takes no app passwords). Proton Mail works through
  Proton Mail Bridge with its exported certificate, on Bridge's default settings (IMAP and SMTP with STARTTLS). Not yet
  tried against a real Bridge.
- You set up your own free Google or Microsoft sign-in client once; CONNECT.md and Setup walk you through it.
- When a sign-in expires, Setup and Getting started say so with a **Sign in again** button. Signing in again, or any
  passing Connect & test, clears an old email warning at once.
- Typing your address picks the right provider again (an Outlook address switches to Sign in with Microsoft).

**Attachments**
- An Inbox email for a job can carry that job's resume and cover letter, or files you put in its `attach/` folder
  ("Show attach folder"). Never private notes, never on an automatic send. A file that names your salary floor is
  greyed out in the list with the reason, and is refused at send.
- Files that come with mail about a tracked job are saved in its folder (safe types only, marked as downloaded, never
  opened). A calendar invite fills in the interview time.

**Emailed sign-in codes**
- Codes that job sites email you (from mail that passes DKIM/DMARC, last 15 minutes) show in the Inbox's **Codes**
  panel, in memory only. Any code in a mail is now hidden as `******` before the mail goes to the AI or into the mail
  list, so it is never sent or saved.

**Also**
- Company research checks each site's robots.txt and never fetches LinkedIn, Indeed, Glassdoor or ZipRecruiter. The
  Wikipedia summary is read again (it comes from Wikipedia's API, which its robots.txt does not cover).
- Long secrets in the keyring (Microsoft refresh tokens) are stored so that a crash or a damaged index can never give
  back half of one or a mix of two.

## Pass 16.1 (2026-11-07): full feature overview fixes

Every feature was checked end to end (code read, then driven in the app against faked job boards, AI, IMAP and SMTP).
What was broken or half-done and now works, by area:

**Tracker and sourcing**
- Adding a job whose posting cannot be fetched still adds it (with its link; fetch the description later); a mistyped
  file path is refused instead of being stored as the description.
- Withdrawing, being rejected or accepting closes the follow-up and thank-you emails still waiting in the Inbox.
- Follow-ups: one at a time per job (asking again gives you the waiting one, sending one closes any duplicate), and
  "ghosted" counts only follow-ups that were actually sent.
- Saved searches reuse a board's recent answer instead of asking it again every cycle; a bad `--save` index says so.
- Save as watch on the Search tab no longer wipes a saved search's keywords and filters when its fields are blank; the
  toast says it updated the existing search.
- One unreachable job board no longer marks a whole saved search as "last run failed": the run counts, and the watch
  shows "some boards unreachable".
- Ranking keeps your salary floor out of the prompt, survives odd scores, and an unranked search still prints.
  LinkedIn titles in the current "(3) Role | Company | LinkedIn" form, autofill contact lines in any order, and
  posting checks that never mark an unknown link as withdrawn.

**Profile, resume and AI**
- The salary floor stays out of cover letters, offline drafts and every email or answer an employer reads, at one
  choke point. A counter-offer may now cite a competing offer that happens to equal your floor (the figure you ticked
  is sent by your choice); the ask is still checked.
- Rebuilding the master profile from the bank keeps everything you typed by hand: roles, summary, and education and
  certification lines without a keyword (only a LinkedIn PDF's sidebar is filtered).
- Provider names are checked when you set them (no crash at the next AI call), the allowlist ignores case
  (`Anthropic` = `anthropic`), and the default provider respects it. The local preset changes nothing when Ollama does
  not answer; a council keeps its synthesis when the judge fails.
- Answers can be marked private and never reach an employer prompt or form; an edited answer that names the floor
  stays in the Inbox instead of failing.
- Saving an adjusted resume or a document from the editor keeps the old version in history.

**Mail, people and interviews**
- Short replies from a job's contact or in a thread Lodestar started are scanned; without an AI provider the scan
  files that mail and carries on instead of stopping.
- An interview reply whose chosen slot clashes with another interview is refused before it is sent (it waits in the
  Inbox); accepting the invite's own slot is no clash. A new time moves the pending round instead of adding one.
- Inbox bookkeeping no longer restarts the follow-up clock; referral asks skip the job's own recruiter; mock
  interviews run from the question bank without a provider.
- Connect email warns when an `IMAP_HOST` / `SMTP_HOST` line in `.env` overrides the provider you chose (a Yahoo
  connection logging in to Gmail), and the login hint names that line first.

**Outcomes and platform**
- Email digest goes to `LODESTAR_NOTIFY_EMAIL`, else your connected mailbox, and says where it went; alert emails get
  a one-line subject and a failed send is reported.
- The monitor loop survives every error, skips the mailbox step quietly when none is connected, and shows only current
  problems. Preferences are range-checked; backups keep at least one and never overwrite in the same minute; the
  scheduled task works from the exe build and reads the install folder's `.env`; the installers keep the Start Menu
  folder and check for Python 3.11+.
- The vault trims a pasted key and refuses a blank one (a blank key made a provider look configured);
  `lodestar vault set` with nothing typed prints one line, not a traceback.

**UI**
- Add job refuses an empty card and fills company and title from a link; Esc asks before discarding typed text and Tab
  stays in the drawer; blank notes and an empty profile are refused, and unsaved edits warn before you leave.
- Preferences have labels and help; the master profile editor, Coach and Answers selects have accessible names; the
  narrow layout keeps the nav on one row; one no-key message points to Setup.

Tests: 386 in total (98 new: `tests/test_overview_*.py`, including `test_overview_review.py` for the review findings).

## Pass 16 (2026-11-07): audit fixes, email connection, mail linking, AI options

- Connect email (Setup > Connect email, `lodestar email connect|test|test-send|status|disconnect`): pick Gmail,
  Yahoo, iCloud, Fastmail, Zoho, AOL or a custom server, paste an app password, and Lodestar logs in to IMAP and SMTP
  to check both (it sends nothing) and explains a failure in plain steps (app password and 2-Step Verification, IMAP
  turned off, wrong host, timeout, port or mode). "Send me a test email" only ever writes to your own address.
  Outlook / Hotmail is refused with the reason (Microsoft allows only OAuth sign-in). The password stays in the OS
  keyring and is never returned. Sent mail now carries `Date` and `Message-ID`; doctor shows the mail servers and
  `--live` logs in once each. `.env.example` no longer sets `IMAP_HOST` (it silently overrode a connected provider)
  and backups leave `.env` out.
- Mail linked to jobs: every relevant scanned message and everything Lodestar sends is kept per job (deduped by
  Message-ID) and shown in the job drawer's Mail section, both ways, trusted or unverified. Replies in a thread Lodestar
  started are filed under the right job. Mail no job claims is listed under Inbox > Unmatched mail: Link to job, Track
  as new job, or Dismiss (`lodestar mail list|link|unlink|dismiss`). Deleting a job deletes its mail; exports include
  it.
- AI draft options: Options buttons in the drawer (follow-up, thank-you, withdrawal, offer check-in, outreach,
  referral, counter-offer, cover letter, reply to a mail), on each Inbox email, in Answers and Offers give up to 3
  drafts from one AI call, one recommended with a reason, plus rewrite chips (shorter, warmer, formal, direct, your
  own words). Picking one never sends anything: it waits in the Inbox for review, to the recipient Lodestar already
  knows. Every draft passes the salary-floor guard. Today lists suggested emails (thank-you after a round, follow-up,
  unanswered recruiter mail, offer check-in, referral ask) without an AI call; Dismiss for now hides one for 3 days.
  CLI: `--options` / `--pick N` on followup, thanks, withdraw, outreach and `offers counter`; `lodestar draft options`,
  `draft rewrite`, `suggest`.
- Audit fixes (security): lookalike sender domains (globex-hiring.com, globex.attacker.net) no longer tie mail to a
  company; any heading spelling of Preferences stays private, and employer-facing text that still names the salary
  floor is refused; idea cards can no longer inject markup; the research pack and scheduling replies no longer leak
  the floor or name your other interviews; calendar files escape company names; oversized LinkedIn zips are refused
  before reading; page fetches pin the checked address (no DNS-rebinding to a private address), cap size and total
  time; mail sockets time out.
- Audit fixes (data and tracker): a duplicate contact or story no longer leaves the database locked; a status proposal
  never moves a job that moved since (it closes as stale), and changing a status by hand closes waiting ones; job ids
  are never reused; withdrawn jobs leave Today, clash checks and the activity log; concurrent calendar imports store one
  round; a failed send keeps your edited draft for a retry; a booked round stops follow-up nudges; one person touched
  and mailed counts once; a new or cleared JD rescores the match; unknown ids say "no job #N"; the funnel counts a
  skipped stage as passed; withdrawing a saved job is not an application; blank answers are refused; applied dates use
  your local day.
- Audit fixes (sources and UI): search says which boards could not be reached instead of "nothing found", and
  watches show "last run failed"; AI ranking without a provider says so; a research pack built from no source says it
  is unverified recall and lists what it read; provider tests and council keep going past one rejected model; a missing
  CLI file is one clear line; profile import keeps the name out of location and project bullets as bullets; the closed
  drawer is inert and focus returns; narrow windows keep the top-bar actions; only editable documents offer Edit;
  stored UTC times show in local time.
- Review fixes (mail trust): a domain that only names the company under another suffix (globex.xyz, stripe.xyz) is
  now a weak tie: the mail is filed under the job, but it never becomes the contact, never books a round, and its status
  moves and replies wait for you. A strong tie needs something Lodestar already holds: the stored contact, our own
  thread, or the company site of the job's posting URL (`careers.globex.com` vouches for `globex.com`). Behaviour
  change: recruiter outreach about a company you do not track yet always waits in the Inbox (it no longer creates the
  job on its own) and its sender is not made the contact; mail from the company's domain moves a job unreviewed only
  when the job has a contact or a posting URL on that domain.
- Review fixes (threads): a reply in our thread is trusted only when our mail went to someone already trusted (it
  answered trusted mail, or went to the job's stored contact). Replying to a mail you linked by hand no longer makes
  its sender trusted one message later. A threaded reply on a rejected or withdrawn job is filed but never trusted: no
  round, no calendar file, no reply accepting a slot.
- Review fixes (Inbox and Setup): a reply to unverified mail shows "unverified sender" on its Inbox card, and
  approving it sends the mail only (an offer reply no longer moves the job). The "track this company" proposal and the
  same message under Unmatched mail are tied together: tracking or linking the mail closes the proposal, and approving
  the proposal files the mail, so you never get two copies of a job. Changing the mail address or servers without
  typing a password removes the stored one, so one provider's app password is never sent to another server. A test
  whose sign-in failed reads "Saved, but sign-in failed" instead of "Connected as". Picking Outlook no longer locks the
  address field. The Answers answer box is multi-line, so "Use this" keeps paragraph breaks.
- Tests: 288 in total (103 new this pass) (`tests/test_pass16_audit_a.py`, `test_pass16_audit_b.py`, `test_pass16_email.py`,
  `test_pass16_mail.py`, `test_pass16_drafts.py`, `test_pass16_review.py`); mail servers, keyring and AI are faked, so
  no real IMAP, SMTP or AI call has been made yet. Older trust tests now give the job a posting URL or contact (the new
  rule) and expect untracked-company outreach to wait.

## Pass 15 (2026-11-06): best-in-class gaps

- Review fixes (batch 2): an interview mail with only a date (often a reply-by date) or from an unverified sender no
  longer creates an interview round, so it cannot add a fake "interviewed" line to the activity log or Insights.
  `sponsors import` reads the current USCIS hub export (New Employment / Continuation / Change of Employer / ...
  Approval columns; every "... Approval" column is summed, denials ignored). The weekly posting check reads Greenhouse
  embed links (`token=`) and `/apply` / `/application` links as their posting and never flags a link that names no
  posting. A newly watched company's open roles are a baseline (one summary alert) instead of one alert and AI
  judgement each. The one-time contacts migration runs under `BEGIN IMMEDIATE`, so parallel first connections cannot
  duplicate contacts or fail. Reminder and toast keys include the round's time (a rescheduled round reminds again).
  Cross-source de-dup no longer folds two openings from the same source (or with different ATS ids) into one. Pay
  stated per month / week / day / hour is no longer read as annual (`parse_salary` skips it; min-salary marks it
  unknown). Every CSV export defuses formula cells (`extras.csv_cell`). Saving a blank offer records nothing and
  clearing every field removes the offer. Re-adding a saved search without filter fields keeps its saved filters.
  Behaviour change: the first poll of a watched company no longer alerts each open role (test updated). 3 new
  regression tests and 6 extended; 185 in total.

- Tracker fields: location, workplace (onsite/hybrid/remote), pay range and currency, source, posted date, deadline,
  excitement (1-5), tags, match score, next action and its due date. Filled on add, capture and search-save from what
  the listing carries; old jobs backfilled once (empty fields only, `updated_at` untouched). Validated, whitelisted
  writes through `db.set_fields`, `lodestar jobs set ID key=value`, `POST /api/jobs/ID/fields` and the drawer's
  Details form. The funnel's "by source" now reads the editable source field.
- Board: drag and drop between columns (moving back asks first; `accepted` keeps proposing withdrawals), focusable
  cards, filter bar (text, status, workplace, minimum pay, tag, has deadline), sort (last activity, stalest, match,
  salary, excitement, deadline), Board/Table toggle with sortable headers and bulk status / tag / delete, all
  remembered in localStorage. Cards show stars, pay, match, location and a red deadline chip at 3 days.
- `jobs list` gains `--sort`, `--remote`, `--min-salary`, `--tag` and shows the new fields.
- Today: `lodestar today` and a Today panel on the Board (next actions due or overdue, deadlines within 3 days,
  interviews within 48 h, follow-ups due, Inbox size).
- Desktop notifications (opt-in, default off): daily agenda, interview within 2 hours, deadline tomorrow, each once.
  Windows toast via PowerShell, macOS osascript, Linux notify-send; never raises. Setup has a toggle and a test.
- Offline drafts: follow-up, thank-you and the new withdrawal email fall back to a plain template when no provider
  is configured, still routed through the Inbox; `--template` / a drawer checkbox picks it with a key present. The
  monitor loop now drafts template follow-ups without a provider. Sending a withdrawal moves the job to `withdrawn`.
- Unknown `POST /api/jobs/ID/<op>` operations now return an error instead of a silent ok.
- 12 new tests (`tests/test_pass15_tracker.py`), 104 in total; browser smoke test of drag, table, bulk tag, filters
  and the Details form on a temp home.
- JD coverage engine (`lodestar/ats.py`, lexicon `lodestar/data/skills.json`, ~1,500 terms across 16 fields plus
  certifications, soft skills, degrees and aliases): deterministic score 0-100 by category (hard .45, title .15,
  education .10 only when a degree is named, soft .10, other .20 from repeated posting phrases), word-boundary matching
  that handles c++, c#, .net and node.js, stuffing flags, and per-job "not mine" keywords (`jobs.ats_skip`,
  `POST /api/jobs/ID/skip`). Presented as JD coverage, not an ATS verdict. `lodestar match ID [--file] [--skip]` and a
  Match section in the drawer (score, category bars, keyword table, title and education lines).
- `resume gap` computes coverage first and saves it even without an AI provider or when the AI call fails; the AI gets
  the missing-keyword table and keeps verdict, weak areas and suggestions. `missing_keywords` / `present_keywords` and
  `match_score` in `gap.json` now come from coverage (the AI no longer supplies its own score). `resume tailor`
  re-scores and logs `coverage X -> Y`. The job's match score follows every coverage run.
- Resume lint (`lodestar/lint.py`, `lodestar resume lint [file] [--job ID]`, Check buttons on Profile and in the drawer):
  weak openers, bullets without numbers, pronouns, passive-voice hint, repeated verbs, long/short bullets, cliches,
  missing email/phone/sections, gaps over 6 months as information only. No age or graduation-year heuristics.
  `resume review` passes the lint results to the AI.
- File audit (`lodestar resume audit FILE`, drawer and profile-bank buttons): contact in header/footer, tables, text
  boxes, images, columns, fonts under 10 pt, non-standard headings, scanned or unreadable PDFs, size over 2 MB, odd file
  names, and the plain text a parser sees. Lodestar's own .docx export comes out clean.
- Packaging: `data/*` in package data and `--add-data "lodestar/data;lodestar/data"` in the PyInstaller line.
- 16 new tests (`tests/test_pass15_coverage.py`), 120 in total.
- Bullet-level tailoring: `resume.tailor_bullets` / `apply_bullets`, `lodestar resume tailor ID --bullets` and
  `--accept all|unflagged|1,3,5`, and a "Tailor by bullet" table in the drawer (original | proposed with added keywords
  highlighted | accept). One AI call; deterministic "unsupported" (added keyword not in profile or bank) and "new
  number" flags; flagged rows start rejected. Proposals in `bullets.json`; building writes `resume.md` through the
  tailoring save path (history kept, `.docx` regenerated), re-scores coverage and logs the delta. Whole-document tailor
  unchanged.
- Tailoring can start from a saved resume in the profile bank (`--base RID`, "tailor from" select); `profile show`
  now prints each saved resume's id.
- Resume styles `classic` (default, the previous look), `modern`, `compact` (preference `resume_style`, validated;
  selects in the drawer and Tools > Preferences); each passes the file audit.
- PDF export (`lodestar resume export ID --pdf`, drawer "Export PDF"): Microsoft Word over COM, else LibreOffice, else
  an HTML print page opened in the system browser; reports which one ran. `resume export` now takes a job id too.
- 8 new tests (`tests/test_pass15_bullets.py`), 128 in total; browser smoke test of the bullet table, Build and Export
  PDF on a temp home.
- Review fixes. Bullet tailoring works from a saved `.docx` (the importer now keeps Title/Heading N as `#` and list
  paragraphs as `-` bullets; re-importing the same file refreshes its text) and from PDF text with `•`-style marks and bare
  section names. Reordering never moves a bullet to another employer: bold or plain role lines between bullets start
  a new group. The "unsupported" flag also covers any hard skill, certification or degree the rewrite adds, not just
  posting keywords. Preferences headings at any level or case are kept out of employer text, and a bullet build that
  still names a salary floor stops. Coverage is saved to `coverage.json` (gap.json is the gap check's: "Fit checked"
  no longer ticks from coverage alone; an existing gap.json's keyword lists are refreshed on re-score). `$120-150k`
  parses as 120,000-150,000. "Hybrid cloud" no longer marks a job hybrid. Tracker field writes, match score and "not
  mine" leave `updated_at` alone. `resume export ID` without a tailored resume prints a message, not a traceback.
  UI: Save details no longer writes back a stale match score after Compute or "not mine"; Search "track" sends the
  listing's location and date; the drawer status select needs "move" (arrow keys fired a change per step) and
  marking a job accepted asks first. 9 new tests (`tests/test_pass15_fixes.py`), 137 in total.
- Company boards: `lodestar companies add|list|rm`, a Companies panel under Monitor and `POST /api/companies`.
  `web_monitor.detect_ats` maps Greenhouse (`boards.` / `job-boards.greenhouse.io`), Lever and Ashby links or
  `vendor:slug` to their documented public JSON feeds; postings become ordinary listings (`source` greenhouse / lever /
  ashby, HTML stripped, pay and posting date kept). The monitor loop reads each board once per cycle; new postings go
  through the saved-search path (one alert, `auto_track` judgement, seen only once judged). Workday, Taleo and iCIMS
  links get a clear "no public feed, use a page watch" message. New table `companies`; jobs gain `ats_feed`.
- Page watches read robots.txt first (once per host per cycle, `urllib.robotparser`); a disallowed page is skipped with
  one alert. Page watches added from the UI must be http(s) URLs.
- Search filters for `jobs search`, saved searches (`watch search-add`, stored in the new `watches.filters` column), the
  Search tab ("Save as watch") and auto-track: location substring or remote, minimum pay (parsed with the existing
  salary parser), posted within N days, seniority from the title. Unknown salary / location / date pass and are
  marked, never dropped. Private dealbreakers (prefs `excluded_companies`, `excluded_title_words`) apply first.
  Cross-source de-dup on normalised company + title + location keeps the richest description and every link. Results
  carry JD coverage against `candidate_text(private=False)` with the top 3 matched / missing terms (skipped for a
  template profile).
- H-1B sponsor hint: `lodestar sponsors import FILE` loads the user-downloaded USCIS H-1B Employer Data Hub export
  (CSV or UTF-16 tab file, old and new column names) into a `sponsors` table per employer and fiscal year; results and
  board cards show "possible H-1B sponsor (N approvals)". `sponsors lookup`, `sponsors clear`. No automatic download.
- Stale / repost signals: `web_monitor.ghost_signals` scores posting age over 30 days, a repost (same company, title
  and location first seen over 21 days ago under another link, new `postings` table), a very short or skill-free
  description, and for board jobs a posting gone from the live feed. "Possibly stale" chip with reasons on results and
  saved board cards; `auto_track` skips listings at 60+. New tool `posting_check`: weekly, saved board jobs are
  re-checked and a vanished posting is proposed for `withdrawn` ("posting removed"), always through the Inbox.
- 13 new tests (`tests/test_pass15_sourcing.py`), 150 in total; all HTTP faked.
- Contacts CRM: new tables `contacts` (name, email, phone, LinkedIn URL, company, position, how met, source, last /
  next touch, notes; email and LinkedIn URL unique) and `job_contacts` (role recruiter / hiring_manager / referrer /
  interviewer / other). One-time migration: each job's stored contact became a contact linked as recruiter; the job
  columns stay and alone drive mail trust. `lodestar contacts add|list|show|edit|rm|import|due|link`, a Contacts tab
  (sortable, filterable table; contact drawer with fields, notes, next touch, linked jobs, recent activity) and
  `GET|POST /api/contacts...`. Setting a job's contact also files the person under Contacts.
- LinkedIn connections import (opt-in, `profile.linkedin_connections`): the export zip or `Connections.csv`, preamble
  skipped; de-dup by LinkedIn URL, then email, then name + company; known contacts only gain blank fields; no next
  touch is set. The profile's LinkedIn import still ignores connections.
- Warm paths: "you know N people here" on board cards, search results (`jobs search` too) and the job drawer, from a
  normalised-company match. The drawer's People section links a contact with a role or drafts **Ask for referral**
  through `extras.outreach` to the contact's own address (Inbox, always reviewed; no address: a LinkedIn note).
  `extras.outreach` and `apply.mail_proposal` take an explicit recipient.
- Touches: any scanned mail from a contact's exact address sets its last touch (mail date); sending an approved email
  to it sets today. Contacts whose next touch has come appear on Today, in `lodestar today`, the daily desktop agenda
  and `contacts due`; nothing is drafted for them. Exports include both new tables.
- A contact never makes mail trusted or becomes a job's contact (tested). `jobs contact` now validates the address.
- Behaviour changes: `state.today` gains `contacts`; JSON / CSV exports gain `contacts` and `job_contacts` (two
  existing tests updated for that).
- 11 new tests (`tests/test_pass15_contacts.py`), 161 in total; mail, AI and HTTP faked.
- Interview rounds: new table `interviews` (job, round, kind phone / technical / onsite / panel / final / other, time,
  interviewers, notes, questions asked one per line, outcome pending / passed / rejected / unknown). `extras.ics`, an
  accepted slot and interview mail with a stated time from a trusted sender record rounds (re-scans add nothing); a
  date-only or unverified mail records only an `interview_date` note. `upcoming_interviews` (Today, reminders, desktop toasts, clash checks) reads the rounds; old calendar
  events are imported once. Drawer section to add / edit / delete rounds; `lodestar interview log|rounds`,
  `POST /api/jobs/ID/rounds`, `POST /api/rounds/ID/edit|delete`.
- Question bank: `lodestar questions [ID]` lists questions logged at the company, then for similar titles, then a
  bundled set of 30 behavioural questions (`lodestar/data/questions.json`). Prep and mock interviews use logged
  questions first.
- STAR stories in the answer bank (new `answers.star` column; `Story: <title>`, tags `story,<competencies>`), ten fixed
  competency tags, a guided form under Answers > Stories, **Save as story** on ideas of the `stories` topic (no second
  drafter), `lodestar stories list|show|add|rm` (`--from-idea`), `POST /api/stories`. The drawer prompts with the
  competencies a posting stresses that no story covers (small keyword table). Prep and mock inject matching stories.
- Mock scoring: per answer one `ai.ask_json` rubric (STAR parts, relevance, specificity 0-2, metrics used, one fix,
  rewrite) plus offline metrics (words, ~140 wpm time vs 60-120 s, repeated words, JD keywords, wpm only from a
  dictation duration; no filler counts). Sessions saved in new table `mock_sessions` with averages; Coach tab cards,
  session summary and an inline SVG trend; `interview mock` prints the card. `mock_interview.md` is still written.
- Behaviour changes: JSON / CSV exports gain `interviews` and `mock_sessions` (export test updated); deleting a job also
  deletes its rounds and mock sessions; the answer bank in the UI no longer lists stories (they have their own view).
- An unauthenticated POST now has its body read before the 403, so Windows no longer resets the connection (a flaky
  failure seen once in the sourcing route test).
- 9 new tests (`tests/test_pass15_interviews.py`), 170 in total; AI faked.
- Insights: `extras.analytics` / `GET /api/analytics` / `lodestar insights`: per-ISO-week applications (jobs entering
  `applied`; auto-tracked saves never), interview rounds, offers, people contacted and mock sessions; response and
  interview rate by source and by match-score band (<40, 40-59, 60-79, 80+); groups under 5 say "not enough data
  yet". Reuses `db.funnel()` and `db.variant_stats()`. New Insights tab with inline SVG bar charts (`<title>` per bar,
  table fallback). No cover-letter or outreach A/B.
- Weekly goals: pref `weekly_goals` (contacts, tailored_applications, mock_sessions, applications), all unset by
  default, validated; progress from this week's events on Insights and in the Friday digest when set.
- Offers: new table `offers` (validated `db.set_offer`; recording one moves the job to `offer`), pure `comp.total`
  (year-1 / 4-year cash and total, equity by year with cliff, match, labelled estimates), `comp.compare` with best per
  row, market range and the gap to the private salary floor (`profile.salary_floor`, shown only in Lodestar's views).
  `apply.offer` reads the structured rows (accepted offers count as live too). Counter-offer `apply.counter`: cites
  the competing figures you tick, AI or offline template, `candidate_text(private=False)`, proposed with
  `review=True`; a test proves the floor never reaches the draft. `lodestar offers [compare|set|counter]`,
  `GET /api/offers`, `POST /api/offers/ID`, run action `counter`.
- Activity log: `extras.activity_log(start, end)` (applied, contacted, followed up, interviewed; only your own
  actions: sent Inbox mail, rounds up to today, touches you record), weekly counts against pref
  `activity_weekly_min`, CSV (formula cells neutralised) and Markdown + printable HTML through `resume.export_html`.
  `lodestar activity`, run action `activity`, a date-range panel on Insights. Labelled a helper report, not a
  compliance claim.
- New table `touches`: the contact touches you record (a last-touch date or "Touched today"), so weekly counts have a
  history; mail touches are not stored there (the sent mail itself is counted).
- Behaviour changes: JSON / CSV exports gain `offers` and `touches` (export test updated); deleting a job deletes its
  offer; a non-numeric value for a whole-number preference is now a clear error instead of a traceback.
- 12 new tests (`tests/test_pass15_insights.py`), 182 in total; AI and HTTP faked.

## Pass 14 (2026-11-06): gap audit, CLI features in the UI, docs caught up

- New status `accepted` (after offer): accepting a job proposes withdrawing your other open applications, always
  through the Inbox. Stats, variants and the funnel count it as a positive outcome.
- Mail you send yourself goes through the Inbox too: Draft reply and email outreach are proposed to the job's contact
  like follow-ups, and always wait for review even when `email_reply` is on auto (the Inbox label names the real
  recipient, since an outreach note may be written for someone else). Set the contact in the job drawer. The checklist counts a follow-up or thank-you as done only once
  it is sent, not when drafted.
- Interviews: a mail with only a date (often a reply-by date) no longer writes an .ics at midnight; the date goes on
  the timeline. Interview prep quotes real pay figures (posting, your market range, your private floor) and uses the
  research pack and gap check. Mock interviews save the transcript and debrief to `mock_interview.md`; in the Coach
  tab they can speak the questions aloud.
- Offers: each `offer.md` opens with its terms line, and evaluating one offer now weighs it against the others.
- `followup_days` drives the Board, digest, loop and `jobs followups` (`--followup` / `--days` still override).
- Listing salaries are kept on saved jobs, so the gap check sees them.
- UI: upcoming interviews and an empty-board hint on the Board; cover letter tone, length and .docx; .ics from
  the drawer; editable non-mail Inbox payloads (JSON); "Auto-track strong fits" on Search; Email digest; idea count;
  answer tags; certifications in the profile bank; offline-only imports; review of an open document; Setup gets
  List models, Local only (Ollama), Market rates, a 30-day usage line, vault removal, Export CSV and Open exports.
- `providers local` pins a model Ollama actually serves. `tools set models provider=model` is validated. `vault rm`
  also removes the old `jobbot` copy.
- Docs: CAPTURE.md shows the token-carrying bookmarklet and documents autofill; RUNDOWN lists all modules, all ten
  tabs and the shipped roadmap; COMMANDS documents the API token, every background action, `/api/open_folder`,
  `/api/comp` and all preferences; SETUP lists every data file and installer flag; AUTOMATION describes the pass-13
  mail trust rules; FEATURES.md regenerated (now with `lodestar profile`).
- Found by the review of this pass and fixed: Review in the drawer is limited to resumes (its prompt is
  resume-specific) and an empty text is an error instead of silently reviewing profile.md; `jobs followups` prints
  the real day count; Setup, onboarding and doctor use the same "profile filled in" rule as prompts, so a short real
  profile no longer keeps the Getting started banner up. Browser smoke test of Board, Coach, Setup and the drawer.
  92 tests.

## Pass 13 (2026-11-06): the faults pass 12 left open

- Private preferences: `candidate_text(private=False)` drops the Preferences section (salary floor, deal-breakers)
  from everything an employer reads: tailored resume, cover letter, outreach, follow-up and thank-you mail, email
  replies, form answers. The gap check gets the preferences as a separate private block, so it still weighs the floor
  after a tailored resume exists. Ranking, offer review, interview prep, research, ideas and coach keep them.
- Mail trust: a job is matched to an email by its stored contact address, then by the sender's company domain
  (`careers.acme.com` -> Acme), and only then by the company name the classifier read. Only the first two can act
  without review. Free-mail senders (gmail.com, outlook.com, ...) are trusted only when they are the job's exact stored
  contact; they never become a contact on their own, and outreach from them (or unauthenticated outreach) waits in
  the inbox instead of creating a job.
- Inbox items left `running` by a crash are closed as `error` ("interrupted: check before redoing") after 30 minutes,
  never re-run automatically (the mail may already have gone). The claim time is stored in `decided_at`.
- Schema migration: a column added by another thread or process between the check and the ALTER is ignored.

## Pass 12 (2026-11-05): profile bank, LinkedIn import, design-review fixes

- Profile bank (`lodestar/profile.py`): every imported resume is kept; contact, skills, spoken languages, roles,
  education, certifications and projects are pooled in `profile.json` with their sources. AI extraction with an
  offline parser fallback. LinkedIn: profile URL, "Download your data" zip (profile CSVs only), "Save to PDF".
  `lodestar profile ...`, Profile bank panel, doctor line, autofill falls back to bank contact details.
- Prompts read `candidate_text()`: the master plus bank facts it omits, fitted by whole sections. The old
  `profile_text()[:N]` cut the Preferences section out of ranking and reply prompts. A template master never reaches
  a prompt (the bank stands in, or the feature stops with a clear message).
- Design review (6 dimensions, 42 confirmed findings, about 20 distinct) and fixes: the monitor loop no longer dies
  silently on SystemExit from the AI layer (per-step guards, `last_error` in the top bar, `running` reset); IMAP and
  SMTP verify TLS certificates; a cross-process lock stops duplicate mail scans; unauthenticated senders no longer
  become a job's contact; watch listings are marked seen only after judgement and manual searches mark nothing;
  truncated AI replies raise instead of being saved; a self-healed model is remembered only after it answers;
  settings.json writes are atomic and locked; profile.md writes are snapshotted; regenerated job documents keep the
  previous version; backups snapshot SQLite with the online backup API; the capture token persists across restarts;
  the page cannot be framed; the public autofill route no longer returns the answer bank; search-result XSS fixed;
  inbox draft edits survive the refresh; drafted answers show on the Answers tab; council chat keeps the coach
  context; merge uses the editor text; the .docx is regenerated when an edited document is saved; follow-up cadence
  counts nudges once and proposes the ghosted close-out once; the AI client retries network errors and timeouts.
- Left open here, fixed in pass 13: email-to-job matching by company name only, DKIM trust for free-mail domains,
  private preferences living inside the resume file, inbox items stuck in "running", schema migration race.

## Pass. Verified state (2026-11-04, seventh pass: coverage and analytics)

- Three more keyless job sources (Hacker News Who is hiring via Algolia, Jobicy, The Muse), URL de-duplication on
  add/capture, a conversion funnel with median days per stage and outcomes by source (`jobs funnel`, Board header),
  interview reminders 48 hours ahead from the calendar files, application packet zips, pay figures extracted from
  postings into the gap check, per-ATS autofill selectors. 34 tests.

## Passa. Verified state (2026-11-04, sixth pass: hardening)

- 26 offline tests pass. Fixed: cross-origin access to the local API (per-launch token, CORS only on the two
  bookmarklet routes), lost mail on classification failure, substring company matches, scheduler command that
  depended on `VIRTUAL_ENV`, deprecated UTC calls. Added: rotating log file, task-table pruning, stale Obsidian notes
  removed, chunked ranking, council allowlist and default-provider preference, token usage accounting, model
  discovery with a clear wrong-model error, ATS-aware autofill matching, backup and export commands with a nightly
  backup tool, accessibility attributes and focus handling, mock interview and dictation in the UI, local-only
  preset, version 0.2.0, CI workflow, unix installer.
- Verified live: 403 without token, 200 with token, CSRF-style approve blocked, bookmarklet routes still work
  cross-origin, no CORS headers on private routes.

## Passa. Verified state (2026-11-03, fifth pass: Lodestar rename + UI overhaul)

- Full rename: package and CLI `lodestar` (`jobbot` kept as an alias), data in `~/.lodestar` (an existing `~/.jobbot`
  is copied over on first run), `LODESTAR_*` env vars (`JOBBOT_HOME` still honoured), keyring service `lodestar`
  (old secrets are read and copied transparently), scheduled task and shortcuts renamed, docs and tests rewritten.
- UI overhaul: sidebar navigation with inbox badge, top bar with stats and quick actions, status-coloured board,
  right-hand job drawer with grouped actions (Documents / Communicate / Schedule and decide / Admin), inline offer
  form, loading states on every AI button, empty states, toasts with severity, Esc to close, responsive under 900px.
  Markup, styles and script split into `index.html`, `app.css`, `app.js`; one `/static/<file>` route with a
  traversal guard. Verified: JS syntax, all routes, 18 tests.
- Still not exercised with real credentials: live AI calls and SMTP sending.

## Passa. Verified state (2026-11-03, fourth pass: idea crafting + lifecycle gaps)

- 18 offline tests pass. New: idea-crafting engine (`ideas.py`: diverge across providers or one provider plus a
  critic pass, converge, score impact x fit / effort, refine with history, status tracking) with ten preset topics;
  company research pack; autofill-not-submit bookmarklet (`/api/autofill`); docx template hook; `lodestar features`
  self-generating inventory (`docs/FEATURES.md`); Ideas tab in the UI.
- Verified live: autofill data route, ideas status and delete endpoints, craft error path without a provider.

## Passa. Verified state (2026-11-03, third pass: automation with approvals)

- 16 offline tests pass. New in this pass: per-tool switches (`settings.py`), the approvals inbox with the only
  executors that send mail / move status / add jobs (`approvals.py`), reply drafting for confirmations, assessments,
  interview invites (slot acceptance from your availability, .ics on send) and offers (never accepts or names a number),
  recruiter contact capture, follow-up and thank-you drafts, answer bank + form-question answering, per-job checklist,
  offer evaluation, AI triage of new listings, Inbox / Tools / Answers tabs in the UI, `docs/AUTOMATION.md`.
- Verified live through the UI: tool toggles, preferences, answer bank, checklist task, propose -> inbox -> approve.
- Verified offline with a faked model: an interview email from a human sender captures the contact, leaves the status
  untouched while `email_classify` is manual, and queues one `set_status` and one `send_email` proposal carrying the
  chosen slot and In-Reply-To; a no-reply sender gets neither contact nor reply.
- Still not exercised with real credentials: live AI calls and SMTP sending.

## Passb. Verified state (2026-11-03, second pass)

- 12 offline tests pass. Added since the first pass: browser capture endpoint with CORS and title splitting,
  resume-variant hashing + `lodestar variants`, interview `.ics` files (auto-created from interview mail with a date),
  outreach drafts, weekly digest, Obsidian mirror of the tracker (`lodestar export obsidian`), scheduled-task installer,
  `lodestar app` (loop + UI in one process), one-click `start.bat` / `start.sh`, and `install.bat` / `uninstall.ps1`.
- Installer verified on this machine: `.venv` created, `.env` created, Desktop + Start Menu shortcuts written,
  `lodestar.exe app` launches. The scheduled task and standalone exe are opt-in flags and were not exercised.
- Earlier verified state:

- 9 offline tests pass (`python -m unittest discover -s tests`).
- Live checks passed: job search against the three APIs, page watch baseline and no-change cycle, every UI endpoint
  (add, status, note, detail, background search task, clean no-key error, watches, delete).
- Not yet exercised with real credentials: AI calls (no provider key stored yet) and IMAP (no mail creds stored yet).
  Both paths are covered by request-shape tests with a faked HTTP layer.

