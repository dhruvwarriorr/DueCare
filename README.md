# DueCare

DueCare combines Somaiya Google sign-in, academic onboarding, manually added subjects and weekly timetable context (typed or uploaded from the college timetable), tasks, calendar, read-only Gmail/Classroom imports, academic targeting, student review, rules and completion reconciliation. Activity tracks changes and sync issues. Settings provides resumable privacy operations, deleted-import suppression/restore and account deletion. The web app supports local development and [Vercel deployment](docs/Deployment.md). The [Flutter app](apps/mobile/README.md) brings the same workspace to Android and iOS.

Academic profiles use fixed KJSSE/BTech context and six student-entered fields: branch, class/year, semester, division, batch, and roll number. Branch choices display the supplied abbreviations and retain canonical code/full-name pairs for message matching. Admission year is not collected. Legacy recognized department values carry over; the next profile save replaces deprecated fields with the canonical profile shape.

The approved behavior lives in [the specification](docs/ProjectDocumentation.md) and [four-phase plan](docs/ImplementationPhases.md). See [current verification and live evidence gaps](docs/Phase4Validation.md) and [local operation/recovery](docs/OperationsLocal.md). Earlier phase verification files remain historical snapshots.

## Repository

- `apps/web`: Next.js, TypeScript, Tailwind, owned shadcn-style Radix components, React Hook Form/Zod, TanStack Query, Vitest, Playwright.
- `apps/api`: FastAPI/Pydantic, SQLAlchemy, Alembic, psycopg, Supabase Auth integration, PostgreSQL integration tests.
- `apps/mobile`: Flutter app for Android and iOS. It calls the API directly with a bearer session handle (see [its README](apps/mobile/README.md)).
- `docs/reference-files`: supplied academic evidence; these files are reference material, not runtime instructions or test identities.
- `scripts`: isolated local test provisioning and browser-test startup.

Use Node 24 (see `.nvmrc`), Python 3.13, uv, and PostgreSQL 18 for the tested environment. Dependencies are locked in `package-lock.json` and `apps/api/uv.lock`.

```sh
npm ci
cd apps/api
uv sync --frozen
```

## Configure Google and Supabase

1. Enable **Google only** under Supabase Auth providers. Disable email/password, anonymous sign-in, and other providers. Configure the Google client ID and secret inside Supabase. Phase 1 does not request Gmail or Classroom permissions.
2. In Google Cloud, use a **Web application** OAuth client. Its authorized redirect URI is `https://YOUR_PROJECT.supabase.co/auth/v1/callback`, as displayed by Supabase's Google provider setup. Google does not redirect directly to DueCare in this flow. If configuring JavaScript origins, use your actual web origin without a path, such as `http://localhost:3000`; this server flow does not require Google's browser sign-in SDK.
3. Supabase's Auth redirect allowlist must include the exact DueCare callback: `http://localhost:3000/auth/callback` for local development, and the HTTPS production equivalent later. For the mobile app, also add `duecare://auth/callback` and set `MOBILE_REDIRECT_URL` to it in `apps/api/.env`. Set the Site URL to the actual web origin. Avoid broad production wildcards. Add eligible test users while Google consent is in testing; university administrators may need to allow the app.
4. Use Supabase asymmetric JWT signing keys (**ES256 or RS256**) so the API can verify signatures through the project's JWKS. This implementation deliberately does not accept legacy HS256 JWTs. Keep Supabase's default session lifetime behavior.
5. Apply the database migration and restricted Auth access script described below. Enable the installed `duecare_internal.before_user_created` function in **Authentication → Hooks → Before user created**. It rejects non-Somaiya and non-Google account creation. The API additionally checks the confirmed email, Google provider identity, verified identity email, and native session on every request. A hosted Google round-trip is still required to validate the hook payload for the actual project.

### Gmail and Classroom source authorization (Phase 2)

Source authorization is separate from Supabase login and never adds a Supabase identity.

1. In the Somaiya-owned Google Cloud project, enable the **Gmail API** and **Google Classroom API**.
2. Configure the OAuth consent screen with an **external** audience and these scopes: `openid`, `email`, `profile`, `gmail.readonly`, `classroom.courses.readonly`, `classroom.coursework.me.readonly`, `classroom.announcements.readonly`, and the optional `classroom.rosters.readonly` (shows which teacher posted Classroom work; without it sync still works and posts show the course instead). `gmail.readonly` is a restricted scope: production use requires Google verification and the applicable security assessment (Phase 4). While in testing, add each eligible student and any personal source account as a test user.
3. Create (or reuse) a **Web application** OAuth client and add the exact authorized redirect URI `http://localhost:3000/connections/callback` (and the HTTPS production equivalent later). This is different from the Supabase login callback.
4. Put the client ID/secret in `apps/api/.env` as `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`. Generate a Fernet key for `SOURCE_TOKEN_KEYS=v1:<key>` with `SOURCE_TOKEN_KEY_VERSION=v1`. To rotate, add `v2:<new key>`, switch the current version, and keep `v1` listed: tokens are re-encrypted under the current version as they refresh.
5. Apply migration `0002` (`uv run alembic upgrade head`).

**Access is granted at sign-in (student decision).** Google sign-in through Supabase also requests the read-only Gmail and Classroom scopes, with offline access. Supabase returns Google's tokens once, at the PKCE exchange. The API then:

1. Verifies them with Google's tokeninfo endpoint. The audience must be `GOOGLE_OAUTH_CLIENT_ID` and the email must be the signed-in Somaiya account.
2. Encrypts the grant.
3. Activates both connections. Any service whose permissions were not granted is skipped.

This requires the Supabase Google provider to use the **same OAuth client** as `GOOGLE_OAUTH_CLIENT_ID`/`GOOGLE_OAUTH_CLIENT_SECRET`, so the grant can be refreshed, and the scopes to be listed on the consent screen. Sign-in never fails because of this step. If access is missing or revoked, **Allow Gmail and Classroom access** on the Sources page signs in again with `prompt=consent`.

This supersedes the specification's separate per-service connect step. The older per-service authorization endpoint remains for adding other Google accounts, but the UI no longer offers it.

Each service requests only its own permissions when connected. Authorization uses one-use state bound to the signed-in student, PKCE (S256), offline access, and incremental scopes; the callback requires the DueCare session. A verified Google ID token identifies the source account, which may be a personal account. Refresh and access tokens are encrypted server-side and never returned. If Google omits a new refresh token, the existing one is kept. Disconnecting one service keeps a grant still used by the other; the Google grant is revoked when no service on that account remains connected.

Google client credentials for login stay in Supabase's provider configuration. The API needs the Supabase project URL and publishable key, a restricted runtime database URL, and application-generated gateway/encryption secrets. It does **not** need a Supabase service-role/admin API key for Phase 1. A separate privileged **database migration** connection is required. Do not put secrets in chat or browser-prefixed variables.

References: [Google with Supabase](https://supabase.com/docs/guides/auth/social-login/auth-google), [PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow), [Auth hooks](https://supabase.com/docs/guides/auth/auth-hooks/before-user-created-hook), [sessions](https://supabase.com/docs/guides/auth/sessions), [signing keys](https://supabase.com/docs/guides/auth/signing-keys).

## Environment and migration

Copy `apps/api/.env.example` to `apps/api/.env`, and `apps/web/.env.example` to `apps/web/.env.local`. Both are ignored by Git. Keep `WEB_ORIGIN` identical and exact in both files; keep the gateway secret identical. `API_URL` is the server-to-server API address, not a public browser variable. Generate secrets locally using the API environment:

```sh
cd apps/api
uv run python -c 'import secrets; print(secrets.token_urlsafe(48))'
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

Use the first output as `GATEWAY_SECRET`, the second as `SESSION_ENCRYPTION_KEY`. Store them privately. Preserve the encryption key across API restarts. Replacing it without re-encrypting existing session rows makes those sessions unreadable and requires a deliberate session reset. Versioned key rotation is part of the later release work.

Set `MIGRATION_DATABASE_URL` to a privileged direct or session-pooler PostgreSQL URL, using `postgresql+psycopg://...` and TLS (`?sslmode=require`) for hosted connections. This is used only by Alembic/setup. From `apps/api`:

```sh
uv run alembic upgrade head
```

Using a privileged database SQL session, execute `apps/api/sql/supabase_auth.sql`. This also enables RLS and removes public API-role access to Alembic revision metadata, then installs a private, narrowly scoped identity/session lookup function and the creation hook. The lookup runs as the privileged migration role because Supabase protects its managed Auth tables with RLS; runtime gets only execute access, not direct Auth-table access or RLS bypass privileges. This matches [Supabase’s managed Auth RLS migration](https://github.com/supabase/auth/blob/master/migrations/20240612123726_enable_rls_update_grants.up.sql). Then create a dedicated password-bearing runtime login, `duecare_app`, with `NOSUPERUSER NOBYPASSRLS` and membership in the migration-created `duecare_runtime` role. Set its password through your private database administration session, never in a committed SQL file. It must not own application tables or inherit privileged roles.

Set `DATABASE_URL` to that dedicated login's connection URL. Use the appropriate Supabase pooler hostname, port, and project-qualified username when using a pooler; copy the host/port/project format from that project's Connect panel. Transaction pooling is supported with prepared statements disabled. Require TLS for hosted connections. Keep application schemas `duecare` and `duecare_internal` out of Supabase's exposed Data API schemas.

The `duecare` tables enforce and force row-level ownership policies using transaction-local user context. Composite foreign keys prevent cross-owner subject/task/history associations. Internal login states and encrypted token rows are restricted to the server runtime role. Browser requests contain an opaque HTTP-only session handle; JWTs and refresh tokens remain encrypted on the server. The API rechecks the native Supabase session and serializes refresh using a database row lock.

## Run locally

In one terminal:

```sh
cd apps/api
uv run uvicorn duecare.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

From the repository root in another terminal:

```sh
npm run dev
```

Open `http://localhost:3000`. `GET http://127.0.0.1:8000/health` checks the API process; `/ready` also checks the migrated runtime database connection. API schemas are available at `/api/v1/openapi.json`. The browser uses only Next.js's same-origin gateway. HTTPS is required in production for the `__Host-` secure cookies.

Without provider configuration, sign-in displays a setup error; there is no production demo login or auth bypass. The test-only provider exists exclusively under `apps/api/tests` and is not used by `duecare.main`.

## Local verification without hosted credentials

Run a **separate disposable** PostgreSQL server on `127.0.0.1:55432` with an administrative `postgres` role. The provisioner is hard-coded to loopback and the disposable `duecare_test` database. Do not point it at an existing application database. CI uses an isolated PostgreSQL service. For a dedicated local PostgreSQL installation, one option is:

```sh
mkdir -p .local
initdb -D .local/postgres -U postgres -A trust
pg_ctl -D .local/postgres -l .local/postgres.log -o '-h 127.0.0.1 -p 55432' start
cd apps/api
uv run python ../../scripts/local-test-db.py
uv run pytest
uv run ruff check duecare tests migrations
uv run ruff format --check duecare tests migrations
```

Trust authentication is for this loopback-only disposable test cluster. The provisioner creates synthetic managed-Auth tables, real encrypted web sessions and signed test JWTs, applies the real Alembic migration and Auth SQL, and runs application queries as a non-owner/non-bypass runtime role. It writes generated test configuration under ignored `.local/`.

From the repository root:

```sh
npm run typecheck
npm run lint
npm run test:web
npx playwright install chromium
npm run test:e2e
npm run build
npm audit --omit=dev
```

Browser tests start their own local API and Next.js servers on ports 8001/3001, seed a synthetic account, and test through the actual gateway. Do not run tests and the development server on those ports simultaneously. Test screenshots and retained failure traces are ignored local artifacts. Stop the disposable server when finished with `pg_ctl -D .local/postgres stop`.

For migration recovery, test downgrades only on a disposable database. Downgrade removes application data. Back up real data and use reviewed forward repairs for hosted recovery. The configured development project is on migration `0004`; [current verification](docs/Phase4Validation.md) records the database checks and [recovery instructions](docs/OperationsLocal.md) explain the tested disposable round-trip.

## API behavior

The web gateway exposes `/api/v1/me`, `/overview`, `/subjects`, `/subjects/{id}`, `/subjects/{id}/timetable`, `/timetable-imports/extract|interpret|confirm`, `/subjects/{id}/classroom-mappings/{connectionId}/{courseId}`, `/tasks`, `/tasks/{id}`, `/tasks/{id}/history`, `/connections`, `/connections/authorize`, `/connections/{id}`, `/connections/{id}/sync`, `/connections/{id}/reprocess`, `/connections/{id}/classroom-courses`, `/sync-jobs/{id}`, `/sync-jobs/{id}/advance`, and `/sender-preferences/{email}`. The OAuth callback is reachable only through the `/connections/callback` browser route. All require the verified eligible server session. Mutation requests require an exact Origin and CSRF header. Edits require the current `revision`; conflicts return `409`. Inaccessible IDs return `404`. Timetable replacement, timetable-import confirmation, task edits, and deletions additionally use durable idempotency keys. Lists use bounded, stable cursor pagination.

Only title and type are required for a task. Precise times are stored in UTC and displayed/entered in IST. A stated date without a time uses a labeled 23:59 IST deadline default for assignments and tests; this does not invent an exam start. Date ranges and tentative alternatives remain undated. Incomplete assignments become `overdue`; incomplete tests become `missed` at their applicable cutoff, including attempt-window closing. Completion is recorded independently and wins over elapsed deadlines and ordinary edits. Reopening is explicit. All subject kinds inherit the one profile batch.

### KT notices

Settings → **KT notices** chooses whether Gmail and Classroom items meant only for KT (ATKT/backlog) students are processed (default) or ignored. Notices that also include regular students are always kept. Use **Reprocess** on a source to apply a changed choice to earlier messages.

### Timetable upload

Subjects → **Upload timetable** accepts either the department's timetable PDF (or a scan or picture of it) or up to four screenshots of the Somaiya roster scheduler (My Scheduler → Week view, scrolled so every hour appears). No AI reads the files. PDFs are read from their own text and table lines, including merged two-hour labs and side-by-side batch columns. Screenshots are read from the grid's pixels with local Tesseract OCR, and overlapping screenshots are joined; install it with `brew install tesseract` on macOS or `apt-get install tesseract-ocr` on Linux. Your profile batch keeps only your batch's labs and tutorials; numbered groups such as `DA_1…DA_8` and one course in several rooms at once are choices you make. Exact subject names/codes link automatically; abbreviations get suggestions (initials, sibling lab/theory, then AI) that you accept. Each course appears once in the review with one subject picker for all its weekly slots; a missing subject can be created from the course card, and subjects with the same name and kind are never created twice. A dry-run summary lists additions, skipped duplicates, removals and overlaps before one atomic save. Files and drafts are not stored. See [the specification](docs/ProjectDocumentation.md#timetable-upload).

### Source imports

The API starts an embedded background worker with its lifespan. The browser enqueues syncing on app open, refocus after 15 minutes, and **Sync now**, then observes progress. The worker advances durable jobs independently of tab visibility, page navigation, or closing the browser. Each sync chunk holds a lease and works for at most `SYNC_WORK_BUDGET_SECONDS` (90 s); checkpoints and partial results commit together. One active job exists per connection, and leases prevent duplicate processing across API processes. Temporary Google failures back off (15 s doubling, capped at 30 min); revoked grants require reconnection. Reprocessing requested during an import is saved and starts after that import finishes. Saved pending sync, source privacy, and account deletion jobs are discovered automatically after API restart. Processing requires the API service to remain running; no scheduled new imports are created by the worker.

Import and interpretation run concurrently within that lease: one lane keeps reading Google while a second interprets committed records and adds tasks and deadlines immediately. Sources, tasks, overview, and calendar refresh every five seconds during active sync, including while an advance request is still running. Submission confirmations are interpreted as they arrive. An unmatched receipt is retried automatically when its exact task appears, so newer confirmations can complete work while import continues. Reprocessing finishes re-queuing before interpretation starts. Paid OpenRouter uses a bounded worker pool (`OPENROUTER_CONCURRENCY=10`) shared across Gmail and Classroom, with distinct records prepared concurrently and task changes committed serially. Other providers retain one shared request slot; HTTP 429 responses put the affected model on cooldown using `Retry-After` (60 seconds when absent), and server errors use a short cooldown. Other configured providers and deterministic parsing can continue. Safe logs record rejected HTTP status codes without provider bodies or prompts. An exhausted advance budget leaves unfinished interpretation queued for the next advance; provider outages retain saved records and schedule an automatic retry in the same active job in the server worker. A download is never reported as a completed sync while eligible records still await AI interpretation. HTTP 429 retry delays are also saved on the affected records, so daily quota exhaustion does not discard imported assignments or announcements.

Gmail keeps a temporary index of keyed duplicate identities in the active import checkpoint so a copy is recognized even when streaming interpretation already minimized its original. The index contains opaque fingerprints and record IDs, and is removed when importing ends, fails, or is cancelled; ignored messages still retain no title, excerpt, body, or plain content hash.

Gmail scans only the last 30 days, newest first. Each incremental sync reads recent messages before draining mailbox history, and expired history relists only within that same 30-day window. Pending older Gmail is excluded from interpretation and pending counts; previously accepted tasks and evidence remain saved. The complete sender blocklist is checked from metadata before any body is fetched, and again under a per-sender lock when results are committed, so a block added mid-import cannot commit content. Non-academic senders (outside `ACADEMIC_SENDER_DOMAINS`, unless included) are not fetched. Blocked and ignored mail keeps only identifiers, sender, and reason, with 30-day expiry. Eligible mail is MIME-decoded safely (plain text preferred unless HTML tables would be flattened; no remote content or scripts), split into authored/quoted/forwarded/signature/footer sections, and stored as identifiers, timestamps, a content hash, section structure, attachment metadata, and links—never the full body. Identical Message-ID and content in the same account is marked as a duplicate occurrence.

Classroom discovers courses as metadata only; nothing creates subjects. Students explicitly link a course to one or more existing subjects (theory/lab/tutorial remain separate; no batch override). Only linked courses are read: own submissions, coursework (initially the last 90 days, older work with future deadlines, and older outstanding work), and announcements (90 days), then incrementally by update time. Changed content increments the source record's revision. Imported records pass through interpretation and review before becoming tasks.

### Interpretation, review, and completion (Phase 3)

For OpenRouter, set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` in `apps/api/.env` (for example, `OPENROUTER_MODEL=openai/gpt-oss-20b`). The key stays on the API server. OpenRouter uses the same JSON validation and rate-limit retry handling as the other providers. `OPENROUTER_CONCURRENCY=10` permits ten calls at once; `OPENROUTER_MAX_OUTPUT_TOKENS=8192` caps each response including reasoning, and `OPENROUTER_REASONING_EFFORT=low` reduces reasoning overhead. Parallelism changes throughput, while billing still depends on tokens and retries. Restart the API after editing its environment file. Existing Groq configuration remains available as a fallback.

Apply migration `0003` (`uv run alembic upgrade head`). During import, the same browser-driven job interprets committed records: Gmail newest first, and Classroom coursework before dependent submission states:

1. **Sender block recheck** under the per-sender lock; blocked mail never reaches AI or tasks.
2. **Content**: Gmail bodies and Classroom text are re-fetched for the step, never stored.
3. **Recognized LMS templates** from `lms-kjsse@somaiya.edu` (always recognized; `LMS_SENDERS` can add others) (submission confirmations, due/overdue notices, quiz open/close windows, digests, `[LMS-Reminder]` tables) are parsed deterministically from labelled absolute dates and activity links. Recruitment, councils/clubs, placements, internships, hackathons, workshops and promotional communities are ignored before extraction, even when they mention tests or deadlines. Everything else with an academic signal goes to **AI**: OpenRouter first when `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are set, then Groq (`GROQ_MODEL` and `GROQ_FALLBACK_MODEL`), then OpenAI/Gemini if configured. Each model gets one repair attempt on invalid output. Mail with no academic signal (events, clubs, placements) is ignored without an AI call. If both providers fail or none is configured, only AI items pause; templates and Classroom states continue.
4. **Academic targeting** compares observed class/year, semester, divisions, and batches with the profile (Division B + batch 2 = B2; SY = second year; III = 3; `A-B-C-D` includes B; room codes are not batches). Explicit mismatches are ignored silently with minimal metadata. Missing or ambiguous targeting goes to **Needs attention**. Subjects are linked automatically from course names and short forms (AI when needed), and Classroom courses link themselves the same way (shown as “auto” on Sources; unlinking is remembered). A linked Classroom course or a personal LMS notification for an enrolled course establishes course membership; lab work still needs batch evidence unless it comes from such a trusted context.
5. **Subjects** come only from the student's own subjects. A course name matching both a theory and a lab subject is asked, never guessed; confirming it can remember the LMS course label for that subject.
6. **Rules** (ordered, allowlisted conditions) decide inclusion and priority for new tasks only. Natural-language rules are AI-interpreted into a preview that must be saved explicitly.
7. **Reconciliation**: exact activity/coursework identities link notices, revisions, and receipts to one task. Older notices never roll back newer values. Student-edited fields remain authoritative. For source-derived dates and details, the latest publication/edit timestamp wins automatically, independent of import order; source disagreements do not create Needs attention items. Similar-looking work is asked, never merged. Quiz closing notices do not overwrite an established classroom session. Windows, tentative alternatives, unknown start times and inconsistent schedules are imported as normal undated tasks without a timing review. A later clear source or manual edit can add the schedule.

**Completion precedence** is enforced in the applying transaction. Due/overdue notices, digests, countdowns, deadline passage, and late-submission warnings never clear completion. A student's newer reopen survives replay of older receipts. Receipts are validated: recognized template, configured sender, Gmail-observed DKIM+DMARC pass for the sender domain, addressed to the connected account, not forwarded, and an exact activity link to an existing task. Classroom uses only the connected student's own `TURNED_IN`; a newer `RECLAIMED_BY_STUDENT` reopens. Verified LMS assignment and quiz submission receipts complete matching assignments and tests automatically. Quiz receipts require recognized submission-confirmation wording, saved-answer confirmation, and an exact quiz link; quiz closing reminders never prove submission. Own Classroom `TURNED_IN` states complete matching work automatically without an environment opt-in. Unsupported or unverified receipt evidence requires review.

**Approved faculty** remembers exact Gmail sender addresses when academic work is automatically accepted or accepted by the student. Approve or remove faculty from Needs attention, Tasks, Overview, task details, or Sources. Approval supplies missing class/division context; explicit audience mismatches, sender blocks, nonacademic filters, and submission validation still apply. Removing an approval prevents automatic reapproval until the student explicitly approves again. Competition-cell mail (including `projectcompetitioncell.engg@somaiya.edu`), exhibitions, promotional training programs, and student registrations are excluded.

**Needs attention** retains ambiguous targeting and unverified evidence. Missing or inconsistent dates/times stay in Tasks with no specific dates. Source-to-source date/detail disagreements are settled automatically and nonacademic mail is excluded. Saved evidence can be reconciled without another AI extraction through `duecare.reconcile.refresh_attention`. It shows the question, observed versus profile context, the proposal, and source excerpt. You can accept (with subject/time corrections), link to an existing task, keep current values, confirm completion, reopen, remove withdrawn work, or dismiss. The server rechecks sender blocks, current academic context, and revision first. Task detail shows source evidence, completion origin, and change history by actor. It also supports moving evidence to another task and merging duplicates with undo (different subjects never merge). **Reprocess** on a source reconsiders earlier ignored, unmatched, and interpreted items under current senders, profile, subjects, timetable, and rules, without duplicating evidence.

### Activity and privacy

Activity supports read/unread filters and opens the related task, review or source. In Settings, delete a connection's imported data separately from disconnecting it, restore suppressed imports and explicitly reimport, or permanently delete the account with typed confirmation. Interrupted operations have saved checkpoints and Resume controls. Student work and other-source evidence are preserved during imported-data deletion; account deletion removes the entire owned workspace and native login. See [operation and recovery details](docs/OperationsLocal.md).

The gateway also exposes `/activity`, `/activity/{id}`, `/privacy/jobs`, `/privacy/jobs/{id}/advance`, `/privacy/source-data-deletions`, `/privacy/account-deletion`, `/suppression-records`, `/suppression-records/{id}/restore`, and `/connections/{id}/reimport`. Account-deletion capabilities stay in HTTP-only cookies, never browser-facing JSON. All ordinary ownership, gateway and mutation protections remain in force.

See [current verification and remaining live checks](docs/Phase4Validation.md) before claiming live provider or production acceptance. Code is not committed or pushed automatically.
