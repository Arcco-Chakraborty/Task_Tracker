# BlackMoniker — Project Brief

> **Paste the mess. Get the plan.**
> BlackMoniker reads messy notes the way a tired friend with a highlighter
> would — then turns them into a sequenced, trackable plan with real dates,
> synced to your calendar. Live at **[blackmoniker.com](https://blackmoniker.com)**.

---

## The pitch

Every productivity app asks you to get organized *first*: create a project,
name your lists, pick a workflow, learn a syntax. But real plans don't start
organized. They start as a paragraph in your notes app, a professor's email,
the back page of a syllabus, a 3am voice-memo transcript — deadlines
mentioned in passing, three tasks hiding in one sentence, "sometime next
week" doing a lot of heavy lifting.

BlackMoniker meets you in the mess. You paste that text (or upload the PDF),
and ~25 seconds later you have a structured tracker: phases in the right
order, every action its own checkable task, hard dates extracted, vague ones
pinned down, urgent things flagged and floated to the top. The whole
onboarding is one paste box and one button.

**Who it's for:** students juggling syllabi and lab deadlines, founders whose
inbox is their roadmap, freelancers running three clients out of one brain,
researchers with 37 open tabs — anyone whose plans live in margins.

---

## The user flow

1. **Land** — blackmoniker.com shows a live demo: a messy note gets
   highlighted (deadlines / events / tasks / sources) and filed onto a week,
   exactly mirroring what the product does.
2. **Sign in with Google** — identity only (email/name/picture). No scary
   permission asks at the door; sign-in is one click.
3. **Paste or upload** — raw text, PDF, or Markdown. Optionally give a start
   date and a target due date.
4. **Watch it work** — extraction runs as a background job while an on-brand
   "reading theatre" plays: skeleton text being swept by highlighter marks, a
   live stage checklist (*hunting for deadlines → flagging time-sensitive →
   sequencing…*), and a progress bar. No timeout can kill the job; the page
   polls until the plan is ready.
5. **Get the plan** — a project with:
   - **Phases → tasks**, ordered by when things should happen (not where they
     appeared in the document) — "do this in week 1" lands at the top even if
     it was written at the bottom;
   - **Real dates** (stated or derived: "friday" resolves against an actual
     calendar; "week 2" becomes a date inside that window);
   - **Effort weights (1–5)** so progress is weighted by work, not task count;
   - **Time-sensitive flags** on registrations, bookings, blockers;
   - **Info cards** (grading splits, contacts, rooms, constraints) and
     **resources** (only URLs that literally appear in the document);
   - **Everyday items** — recurring habits tracked on a per-day grid where
     only *today* is editable (no back-filling streaks).
6. **Track** — Dashboard (greeting, weighted progress rings, focus score,
   overdue), Today (what needs attention + today's habits), Planner
   (timeline by date), Projects, Calendar, Analytics (14-day trend, effort
   distribution, urgency breakdown), streak counter.
7. **Send to Google Calendar** — first click triggers a one-time incremental
   OAuth grant for the narrowest write scope; after that, one click per task
   (or one click for a whole project) inserts all-day events. An `.ics`
   export covers every other calendar app.
8. **Stay in touch** — public contact form on the landing; messages land in
   an admin inbox.

---

## The technical part

**Stack (deliberately boring):** Python + Flask + Jinja, SQLite, Tailwind
(CDN) + vanilla JS. No build step, no Node, no ORM. Gunicorn behind nginx
with Let's Encrypt on an Oracle Cloud VM, managed by systemd. One server,
one process manager, one database file — trivially debuggable and cheap to
run.

### AI extraction pipeline
- **Model:** Gemini 2.5 Flash via the REST API. Chosen over Flash-Lite after
  live A/B verification — Lite got weekday→date arithmetic wrong ("sunday" →
  a Monday); Flash reasons it out correctly and sequences better.
- **Key rotation:** a ring of API keys, round-robin with two retry sweeps and
  backoff across 429/5xx/network failures.
- **Reliability:** JSON output mode (`responseMimeType`) plus a
  brace-slicing fallback parser; actionable errors for token-limit
  truncation and safety blocks; one automatic retry on a malformed response.
- **Prompt engineering, earned the hard way:**
  - *Sequence ≠ source order*: chronology and dependencies beat document
    position; "week N" is timing, never duration.
  - *A literal 14-day calendar* is injected into the prompt because LLMs are
    unreliable at weekday math.
  - *Lists must be expanded* — one action, one task.
  - *Weights are effort*, with the full 1–5 range enforced.
  - *URLs only verbatim* — no hallucinated links.
- **Long documents** are clipped keeping head **and** tail — deadline lists
  love to live on the last page.
- **Normalization layer** validates everything the model returns: dates
  coerced, durations capped, empty phases dropped, duplicate
  resources/habits deduped, time-sensitive items floated to the front.
- **Async jobs:** extraction runs in a background thread writing to an
  `extract_jobs` table; the browser polls. Neither nginx nor gunicorn
  timeouts apply — a 5-minute document behaves the same as a 5-second note.
- **Verification harness:** `scripts/verify_extraction.py` calls the real
  API with a trap-laden document and scores 14 checks (ordering,
  time-sensitivity, dates, weights, URL fidelity). Current score: 14/14.

### Auth & multi-tenancy
- Google OAuth implemented directly with `requests` (no heavyweight SDK).
- **Two-stage consent:** login asks for identity only (never shows a
  warning); the sensitive calendar scope (`calendar.events.owned` — the
  narrowest write scope) is requested *incrementally*, only when a user
  first clicks "Add to Google Calendar", then stored as a refresh token.
- Every query is scoped to the signed-in user; mutation routes verify
  ownership (403/404). Admin dashboard (users, signup trend, instance
  stats, contact inbox) is gated by an email allowlist and hidden (404)
  from everyone else.

### Security posture
OAuth `state` (login-CSRF), Origin-header checks on all POSTs layered over
SameSite=Lax cookies, CSP/HSTS/Permissions-Policy/X-Frame-Options headers,
parameterized SQL throughout, Jinja autoescaping, 10 MB upload cap, contact
form honeypot + per-IP rate limit, secrets in `.env` outside git and
deploys.

### Discoverability
robots.txt (app routes excluded), sitemap.xml, **llms.txt** for AI
assistants, canonical URLs, Open Graph/Twitter cards with a generated share
image, JSON-LD (`SoftwareApplication` + `FAQPage`).

### Quality
106 pytest tests covering routes, auth flows, extraction normalization, the
scheduler, multi-user isolation, security headers and the async job
lifecycle — plus the live extraction harness. Standing rule: every change is
tested and deployed the same day.

---

## Status & next steps

| Area | Status |
|---|---|
| Core product (extract → track → calendar) | **Live** at blackmoniker.com |
| Multi-user + admin + contact | Live |
| Google OAuth verification (calendar scope) | Prepared — pending submission |
| Search indexing | Configured — pending Search Console verification |
| Pricing | Free while in beta |

*Built by Arctek Systems. Brief last updated 2026-06-11.*
