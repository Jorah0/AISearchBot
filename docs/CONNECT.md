# Link everything

How to connect Lodestar to your AI provider and your mailbox, what each status means, and what to do when something
stops working. Setup in the app has the same steps in short; the terminal commands are listed next to each step.

## 1. What Lodestar connects, and where each secret lives

| What | Why | Secret | Where it is kept |
|---|---|---|---|
| AI provider key (Anthropic, OpenAI, Gemini, Groq, OpenRouter, Mistral; Ollama needs none) | drafts, tailoring, classification | the API key | OS keyring (Windows Credential Manager, macOS Keychain, Secret Service) |
| Mailbox, signed in with Google or Microsoft | reading hiring replies, sending mail you approve | a refresh token | OS keyring |
| Mailbox, with an app password | the same | the app password | OS keyring |
| Your own Google / Microsoft sign-in client | lets the sign-in above work | Google client secret (Microsoft has none) | OS keyring |

- Secrets are never written to disk in plain text, never shown again after you paste them, never put in logs, error
  messages, exports or backups, and never sent anywhere except to the provider they belong to.
- Access tokens for Google / Microsoft mail live in memory only, for about an hour; only the refresh token is stored.
- A value in the environment or a `.env` file still wins over the keyring (Setup says so when that happens).
- Each data folder has its own keyring namespace. The default folder (`~/.lodestar`) uses the service name `lodestar`
  (and still reads secrets saved under the old name `jobbot` once, copying them over). Any other `LODESTAR_HOME` (a
  test copy, a sandbox, a second profile) uses `lodestar:` plus 12 hex characters derived from that folder's path, so it
  never sees or changes the secrets of your real install: link keys and the mailbox again there. `lodestar doctor` (and
  Setup > Run diagnostics) shows the active namespace on the `vault namespace` line. The name comes from the folder's
  full path, so moving or renaming such a folder starts an empty namespace. A portable install that wants one
  fixed name sets `LODESTAR_VAULT_SERVICE`, in the environment or a `.env` file (for example
  `LODESTAR_VAULT_SERVICE=lodestar` to share the default folder's secrets on purpose). Never set it for a test or
  sandbox run (the unit tests, E2E suite and update check blank it themselves). Upgrading an install that already used
  its own `LODESTAR_HOME`: its secrets were saved under `lodestar`, so link them again or set
  `LODESTAR_VAULT_SERVICE=lodestar`; the `vault namespace` line WARNs and names the missing ones. To remove the secrets of a non-default folder, run `lodestar keys rm`, `lodestar email disconnect` or
  `lodestar vault rm` with that same `LODESTAR_HOME`. `.env` files still load for any data folder: a key written
  there is plain config and is used wherever that `.env` is read.

## 2. AI keys

Setup > **Link an AI key**: pick the provider, paste the key, click Link. The key is checked at once and again every
time Lodestar starts (`lodestar ui`, `app`, `desktop`), in the background. The check lists the provider's models, so it
**spends no tokens**. Terminal: `lodestar keys link anthropic` (asks for the key without showing it), `lodestar keys`,
`lodestar keys check [NAME]`, `lodestar keys rm NAME`.

| Provider | Get a key | The key looks like |
|---|---|---|
| Anthropic (Claude) | https://console.anthropic.com/settings/keys | starts with `sk-ant-` |
| OpenAI | https://platform.openai.com/api-keys | starts with `sk-` |
| Google Gemini | https://aistudio.google.com/apikey | starts with `AIza`; has a free tier |
| Groq | https://console.groq.com/keys | starts with `gsk_`; has a free tier |
| OpenRouter | https://openrouter.ai/settings/keys | starts with `sk-or-` |
| Mistral | https://console.mistral.ai/api-keys | |
| Ollama (local, no key) | https://ollama.com/download | runs on this computer; Link checks that it answers and saves its model only then (not running: nothing saved); Remove unlinks it |

All paid providers are pay as you go. What the status pill means:

| Status | Meaning | What to do |
|---|---|---|
| Verified | the provider accepted the key; the model in use is shown | nothing |
| Failed | the provider rejected the key, or the account has no credit | copy the whole key again, or add billing / credit |
| Failed (quota or rate limit) | the key was accepted, but the account hit its quota or rate limit (HTTP 429) | wait, or check your plan; AI features stay on |
| Couldn't reach, will retry | no answer (offline, outage, a provider error) | nothing: AI features stay on, the next start re-checks; or click Re-check |
| Not checked | linked but not checked yet, or the key changed | Re-check |

Set `LODESTAR_NO_STARTUP_CHECK=1` to skip the start-up check (for people who start the app many times a day).

## 3. Email: which way to connect

| | Sign in with Google / Microsoft | App password |
|---|---|---|
| 2-step verification | every method works, on the provider's own page (section 7) | checked once, when you create the app password |
| Setup | one-time client setup, about 10 minutes (sections 4, 5) | a minute |
| Works for | Gmail, Outlook.com / Hotmail / Live, Microsoft 365 | Gmail, Yahoo, AOL, iCloud, Fastmail, Zoho, custom servers |
| Not possible with | an organization that blocks the app | Google accounts with security-key-only 2-step, Advanced Protection, most work accounts; Microsoft (no app passwords for IMAP) |

Lodestar never sees your normal password or your 2-step codes either way.

## 4. Gmail with Google sign-in

Lodestar cannot ship one shared Google app: the only scope that grants IMAP and SMTP (`https://mail.google.com/`) is a
"restricted" scope, which needs Google verification plus a yearly security assessment for an app anyone can use. A
personal app that only you use needs neither ("fewer than 100 users"). So you create your own, once (Google Cloud
console, as of November 2026):

1. https://console.cloud.google.com/ > create a project named "Lodestar".
2. APIs & Services > Library > enable **Gmail API** (needed for the scope to appear in the scope list; Lodestar itself
   uses IMAP and SMTP, not the API).
3. Google Auth Platform > **Branding**: app name "Lodestar (personal)", your address as support and developer contact.
   **Audience**: External. **Data access**: add the scope `https://mail.google.com/` (plus `openid`, `email`).
4. **Clients** > Create client > Application type **Desktop app** > Create. Copy the Client ID and Client secret into
   Lodestar right away (Setup > Connect email > Gmail > "Set up your Google client (one time)", or
   `lodestar email client google`):
   Google shows the full secret only once, at creation. Lost it? Add a new secret to the client (or create a new
   client) and paste that.
5. **Audience** > Test users: add your own address.
6. **Audience** > **Publish app** ("In production"). Google shows the app as unverified: that is fine for your own use.
   Skip this step and the sign-in stops working after 7 days (Setup then shows "Your Google app is in Testing").
7. In Lodestar click **Sign in with Google** (`lodestar email signin google`). Your browser opens Google's page. On
   "Google hasn't verified this app" click Advanced > Go to Lodestar (unsafe): it is your own app. Then your usual
   2-step check, then Allow. Lodestar tests IMAP and SMTP and shows the result.

## 5. Outlook.com / Hotmail / Live and Microsoft 365 with Microsoft sign-in

Microsoft accepts only this sign-in for IMAP and SMTP, no passwords. One-time setup (Microsoft Entra admin center):

1. You need a Microsoft Entra tenant to register an app
   (https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-create-new-tenant). Work or school: ask IT, or
   use your organization's tenant if you may register apps. Personal: create a free tenant (Microsoft may ask you to
   sign up for a free Azure account, which can ask for a card to prove who you are; an app registration costs nothing).
   Not for you? Forward your Outlook mail to a Gmail address and connect that instead.
2. https://entra.microsoft.com > Applications > App registrations > **New registration**: name "Lodestar", Supported
   account types **Any Entra ID Tenant + Personal Microsoft accounts**, Redirect URI platform **Public client/native
   (mobile & desktop)** with `http://localhost`. Register.
3. **Authentication** > Advanced settings > **Allow public client flows**: Yes. Save.
4. **API permissions** > Add a permission > APIs my organization uses > "Office 365 Exchange Online" > Delegated >
   `IMAP.AccessAsUser.All` and `SMTP.Send` (plus Microsoft Graph `offline_access`, `openid`, `email`, `profile`). Work
   accounts: an admin may need to grant consent.
5. Copy the **Application (client) ID** into Lodestar ("Set up your Microsoft client (one time)", or
   `lodestar email client microsoft`). There is no secret.
6. Outlook.com only: turn on IMAP (Outlook.com > Settings > Mail > Forwarding and IMAP;
   https://support.microsoft.com/en-us/outlook/pop-imap-and-smtp-settings-for-outlook-com).
7. Pick **Outlook.com / Hotmail / Live** or **Microsoft 365 (work or school)**, choose Personal or Work, click **Sign in
   with Microsoft** (`lodestar email signin microsoft`, add `--work` for Microsoft 365) and finish your usual 2-step
   check on Microsoft's page.

Microsoft 365 sending: if your organization turned SMTP AUTH off, Lodestar can read but not send; the test says so and
names what to ask your admin.

## 6. App passwords

Turn on 2-step verification first; the provider then lets you create an app password. Paste it in Setup > Connect
email (or `lodestar email connect`, which asks without showing it).

| Provider | Where |
|---|---|
| Gmail | https://myaccount.google.com/apppasswords (paste the 16 letters) |
| Yahoo Mail | https://login.yahoo.com/account/security > Generate app password |
| AOL Mail | https://login.aol.com/account/security > Generate app password |
| iCloud Mail | https://account.apple.com > Sign-In and Security > App-Specific Passwords |
| Fastmail | https://www.fastmail.help/hc/en-us/articles/360058752854-App-passwords |
| Zoho Mail | https://accounts.zoho.com/home#security/app_password (turn on IMAP in Zoho Mail first; organisation or EU accounts: pick Other (custom server)) |
| Proton Mail (via Bridge) | install Proton Mail Bridge (https://proton.me/mail/bridge, paid plans), sign in there (your 2-step check happens in Bridge), use the Bridge password it shows. Export Bridge's TLS certificate (Settings > Advanced > Export TLS certificates) and give its path under Advanced > CA certificate file (`lodestar email connect --preset proton --cafile PATH`). Lodestar then trusts only that certificate. The preset uses Bridge's default ports and security: IMAP 127.0.0.1:1143 with STARTTLS, SMTP 127.0.0.1:1025 with STARTTLS (if you switched Bridge to SSL, pick ssl under Advanced > IMAP security / SMTP security, or `--imap-mode ssl --smtp-mode ssl`). Not yet tested with a real Bridge. |
| Other (custom server) | your provider's IMAP and SMTP servers under Advanced; an app password if it offers one |

## 7. Every 2-step method

With **Sign in with Google / Microsoft**, whatever your account has turned on runs on the provider's own page in your
normal browser: authenticator apps (Google Authenticator, Microsoft Authenticator, Authy, any TOTP app), SMS or voice
codes, phone prompts, passkeys and Windows Hello, security keys, backup codes, Advanced Protection. Lodestar gets only
the result. With an **app password**, 2-step verification is checked when you create the app password.

## 8. When the sign-in expires

Setup and Getting started say "Sign-in expired" with a **Sign in again** button, and `lodestar doctor` shows a FAIL
on "email sign-in" (`lodestar email signin google|microsoft`). Why it happens:

- you revoked Lodestar's access, or changed your Google password (Gmail scopes end with the password);
- unused for 6 months (Google) or 90 days (Microsoft);
- your Google app is still in Testing: sign-ins last 7 days (publish it, section 4 step 6);
- more than 100 sign-ins for the same client (Google drops the oldest);
- your organization's policy changed.

## 9. Emailed codes from job sites

Job and ATS sites often email a one-time code when you sign in. When your mailbox is connected, the Inbox shows a
**Codes** panel (and a "Codes (1)" button at the top) with the code in large type, the sender's domain, Copy and
Dismiss. "Check for a code now" looks at the last few messages right away.

- Only codes from the last 15 minutes, only from senders whose mail passes DKIM/DMARC; always check the domain.
- Kept in memory for 15 minutes, never saved, logged, sent to an AI or entered anywhere for you. Before a mail goes to
  the AI or into the mail list, every code in it is replaced by `******` (also an expired code, or one from a sender
  that failed DKIM), so a hiring mail that happens to hold a code is still filed, without the code.
- Lodestar never stores your authenticator (TOTP) secret: next to your other sign-ins on the same computer it would
  turn two factors into one. Your phone, passkey or security key stays the second factor.

## 10. Attachments

Out: an Inbox email for a job can carry that job's `resume.pdf` / `resume.docx`, `cover_letter.pdf` /
`cover_letter.docx`, and pdf, docx, png or jpg files you put in the job's `attach/` folder ("Show attach folder" opens
it). Limits: 10 MB per file, 10 MB per mail in total (about 14 MB once encoded), 10 files. Notes, interview prep, offer
notes, research, gap checks, calendar files, received mail and old versions are never attachable, and a document that
names your salary floor is refused (the Inbox's "Add from this job's files" list shows it greyed out with the
reason). Drafts you ask for (outreach, referral asks, replies to verified mail) pre-tick
your tailored resume; you can remove it. Lodestar never attaches a file on its own: mail with attachments always waits
in the Inbox.

In: attachments of mail filed under a tracked job are saved under `applications/<job>/mail/<date>-<id>/` (pdf, docx,
odt, txt, png, jpg, gif, ics, csv, xlsx; 10 MB each, 25 MB and 10 files per message), marked as downloaded from the
internet, and listed in the job's Mail section with "Show in folder". Programs, scripts, web pages and macro documents
are never kept, and Lodestar never opens a received file. Mail no job claims keeps its files in your mailbox. A
calendar invite (.ics) fills in the interview time when the mail text gives none; the usual trust rules decide whether
it becomes an interview round.
Backups leave the saved mail files out (they are still in your mailbox).

## 11. Security notes

- The sign-in listener is loopback only: 127.0.0.1 on a random port, plus ::1 on the same port for Microsoft (which
  sends the browser to `localhost`). It serves one sign-in, answers only the sign-in it started (state and Host
  checked, PKCE), and closes after 5 minutes at most.
- The sign-in page always opens in your system browser, never inside the Lodestar window.
- Revoke access any time: Google https://myaccount.google.com/connections; Microsoft
  https://account.live.com/consent/Manage (personal) or https://myapps.microsoft.com (work). Disconnect in Setup
  revokes Google tokens itself and tells you where to remove Microsoft's.

## 12. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `redirect_uri_mismatch` | the Google client is not a Desktop app | create a Desktop app client (section 4 step 4) |
| `access_denied`, "Access blocked: app has not completed the Google verification process" | not a test user, or you cancelled | add yourself as a test user or publish the app (section 4 steps 5, 6) |
| `invalid_client` | client ID or secret pasted wrong | paste them again (Google Cloud > Clients, or the app registration's Application (client) ID) |
| `client_secret is missing` | Google wants the secret too | Set up client again with the secret |
| `org_internal`, `admin_policy_enforced` | your Google Workspace admin blocks the app | ask them, or use an app password if allowed |
| `AADSTS50011` | redirect URI missing | add `http://localhost` under Authentication > Mobile and desktop applications |
| `AADSTS700016`, `unauthorized_client` | wrong application ID, or the app does not allow this account type | set Supported account types to "Any Entra ID Tenant + Personal Microsoft accounts" |
| `AADSTS65001`, `consent_required` | an admin must approve the app | ask your admin, or use another account |
| `AADSTS7000218` | public client flows are off | Authentication > Advanced settings > Allow public client flows: Yes |
| Sign-in expired | see section 8 | Sign in again |
| Your Google app is in Testing | refresh tokens last 7 days | publish the app, sign in again |
| Browser did not open | no default browser, or a remote session | use the "Open the sign-in page" link (or `--no-browser` and open the printed page) |
| Firewall prompt or blocked port | the listener is loopback only (127.0.0.1, and ::1 for Microsoft) | nothing leaves the computer: allowing private networks is not needed |
| Signed in with the wrong account | the browser picked a saved account | Disconnect, Sign in again, pick the account |
| Outlook: "User is authenticated but not connected" | IMAP is off in Outlook.com | turn on IMAP (section 5 step 6), test again |
| Microsoft 365: 5.7.139, SMTP AUTH disabled | your organization turned SMTP AUTH off | ask your admin to allow it for your mailbox, or send from another account |
| Sign-in was refused (app password) | normal password used, or a typo | create an app password (section 6) |
| Could not find the server / did not answer / secure connection failed | wrong host, port or security mode, or offline | IMAP 993 with ssl (Proton Mail Bridge: 1143 with starttls); SMTP 465 with ssl or 587 with starttls; check the internet connection |
| Certificate does not match that host name | host typed differently from your provider's list | use the exact host |
| IMAP access is turned off | the provider has IMAP disabled | turn it on in your mail settings |
| `IMAP_HOST=... in .env overrides` | an old line in `.env` | remove it, test again |
| Key: Failed, no credit | the provider account has no credit | add billing or credit |
| Key: Failed, quota or rate limit | too many calls, or the plan's quota is used up | wait, or check your plan |
| Key: Couldn't reach | offline or the provider is down | nothing: the next start re-checks |
| Getting started still shows an old email problem after a fix | an older check result | any passing test (Connect & test, Sign in again, Re-check all) replaces it at once |
| A file cannot be attached | not in the allowed set, too large, a link, or it names your salary floor | put a pdf/docx/png/jpg in the job's `attach/` folder; edit the floor out |
