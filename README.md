# DueCare

Phase 1 is the manual academic workspace: Somaiya Google sign-in, academic onboarding, subjects, weekly timetable context, tasks, calendar, dashboard, and settings. Gmail and Classroom source connections belong to Phase 2; interpretation and submission reconciliation belong to Phase 3.

The approved behavior lives in [the specification](docs/ProjectDocumentation.md) and [four-phase plan](docs/ImplementationPhases.md). [Phase 1 verification](docs/Phase1Validation.md) distinguishes tested local behavior from pending hosted acceptance.

## Repository

- `apps/web`: Next.js, TypeScript, Tailwind, owned shadcn-style Radix components, React Hook Form/Zod, TanStack Query, Vitest, Playwright.
- `apps/api`: FastAPI/Pydantic, SQLAlchemy, Alembic, psycopg, Supabase Auth integration, PostgreSQL integration tests.
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
3. Supabase's Auth redirect allowlist must include the exact DueCare callback: `http://localhost:3000/auth/callback` for local development, and the HTTPS production equivalent later. Set the Site URL to the actual web origin. Avoid broad production wildcards. Add eligible test users while Google consent is in testing; university administrators may need to allow the app.
4. Use Supabase asymmetric JWT signing keys (**ES256 or RS256**) so the API can verify signatures through the project's JWKS. This implementation deliberately does not accept legacy HS256 JWTs. Keep Supabase's default session lifetime behavior.
5. Apply the database migration and restricted Auth access script described below. Enable the installed `duecare_internal.before_user_created` function in **Authentication → Hooks → Before user created**. It rejects non-Somaiya and non-Google account creation. The API additionally checks the confirmed email, Google provider identity, verified identity email, and native session on every request. A hosted Google round-trip is still required to validate the hook payload for the actual project.

Google client credentials stay in Supabase's provider configuration. The API needs the Supabase project URL and publishable key, a restricted runtime database URL, and application-generated gateway/encryption secrets. It does **not** need a Supabase service-role/admin API key for Phase 1. A separate privileged **database migration** connection is required. Do not put secrets in chat or browser-prefixed variables.

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
uv run uvicorn duecare.main:app --reload --host 127.0.0.1 --port 8000
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

For migration recovery, test `alembic downgrade base` followed by `upgrade head` only on a disposable database. Downgrade removes all application data. On a configured Supabase project, disable the creation hook and remove both `duecare_internal.before_user_created` and `duecare_internal.lookup_auth_identity` functions before downgrading the application schemas. Back up real data and use reviewed forward repairs for production recovery; hosted migration revision `0001` has been applied to the configured DueCare project; hosted application acceptance is tracked in `docs/Phase1Validation.md`.

## API behavior

The web gateway exposes `/api/v1/me`, `/overview`, `/subjects`, `/subjects/{id}`, `/subjects/{id}/timetable`, `/tasks`, `/tasks/{id}`, and `/tasks/{id}/history`. All require the verified eligible server session. Mutation requests require an exact Origin and CSRF header. Edits require the current `revision`; conflicts return `409`. Inaccessible IDs return `404`. Timetable replacement, task edits, and deletions additionally use durable idempotency keys. Lists use bounded, stable cursor pagination.

Only title and type are required for a task. Precise times are stored in UTC and displayed/entered in IST. A date-only assignment uses a labeled 23:59 IST default; an unspecified exam start remains unresolved. Incomplete assignments become `overdue`; incomplete tests become `missed` at their applicable cutoff, including attempt-window closing. Completion is recorded independently and wins over elapsed deadlines and ordinary edits. Reopening is explicit. All subject kinds inherit the one profile batch.

See [verification evidence and remaining live checks](docs/Phase1Validation.md) before treating Phase 1 as hosted-accepted. No commit, push, deployment, or hosted data mutation is performed automatically.
