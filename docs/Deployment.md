# DueCare on Vercel and Supabase

Production URL: https://duecare-xi.vercel.app

## Architecture

The root `vercel.json` deploys two Vercel Services together: Next.js in `apps/web` and the FastAPI container in `apps/api`. The service binding supplies the private `API_URL` to Next.js. The container includes Tesseract for scheduler screenshot extraction. Public API traffic passes through the existing Next.js session/Origin/CSRF gateway. Only health/readiness and the separately authenticated worker dispatcher are routed directly to FastAPI.

Supabase remains the existing Auth and PostgreSQL project. The restricted application database role is used at runtime; the privileged migration connection is never configured in Vercel. Existing session and source-token encryption keys must remain stable across deployments.

On Vercel, `BACKGROUND_WORKER_MODE=external` disables the permanent local worker thread. Supabase Cron checks for durable pending jobs every minute and invokes one authenticated batch, with up to four concurrent jobs. Existing database ownership checks, leases, retries and checkpoints continue to govern execution. A scheduled invocation without pending work makes no HTTP call. The normal embedded worker remains the local default.

Timetable originals upload directly to the private `duecare-timetable-temp` Supabase Storage bucket, retaining the existing 10 MB/file and 20 MB total limits. Signed upload URLs contain a temporary capability for a single generated path; user JWTs and service credentials are never sent to the browser. RLS limits access to the authenticated owner's folder. The API downloads bounded content, deletes originals, then extracts the timetable in memory. The browser also requests cleanup after partial failures. A Supabase Edge Function removes uploads older than one hour, in batches of 100 every five minutes; large backlogs can take additional runs. Extracted text and drafts are not persisted. The cleaner uses custom dispatcher authentication and its built-in service credential, limited in code to this bucket.

## Configuration

The Vercel project is `duecare` under `dhruvkumar31712-6617s-projects`. Deploy from the repository root. Production environment variables come from the API's `.env.example`, excluding `MIGRATION_DATABASE_URL`. Additionally set:

```dotenv
WEB_ORIGIN=https://duecare-xi.vercel.app
BACKGROUND_WORKER_MODE=external
WORKER_DISPATCH_SECRET=<a-long-random-secret>
```

Do not manually configure `API_URL`; Vercel's service binding provides it. Secrets belong in Vercel environment settings. Local `.env` files, `.local`, tests, caches and private reference files are excluded from source uploads by `.vercelignore`.

`supabase/deployment.sql` records the hosting infrastructure migration applied to the existing project. It creates the private temporary bucket, RLS policies, service-only cleanup RPC and two Cron schedules. It is separate from the application's Alembic migrations and is intended for initial installation, not repeated application without adapting existing policies. Store the dispatcher secret as `duecare_worker_secret` and the production origin as `duecare_web_origin` in Supabase Vault. Never put literal secrets into Cron command text or checked-in SQL. Deploy `supabase/functions/duecare-clean-timetable-uploads/index.ts` with JWT gateway verification disabled: its body explicitly authenticates each request through the service-only RPC before deleting anything.

Supabase Auth Site URL must be the production origin. Add the exact `https://duecare-xi.vercel.app/auth/callback` to its redirect allowlist. Google Cloud must retain the Supabase provider callback and also authorize `https://duecare-xi.vercel.app/connections/callback` for source reconnects. Keep localhost callbacks for development. Google consent/testing restrictions and university administrator policies still apply.

## Mobile app

The Flutter app (`apps/mobile`) calls the API directly. `vercel.json` routes `/api/v1/mobile/*`, and any `/api/v1/*` request with an `Authorization: Bearer` header, to the API service. Browser requests carry no bearer token, so they still reach the Next.js gateway. Set `MOBILE_REDIRECT_URL=duecare://auth/callback` in the production environment, and add the same URL to Supabase's Auth redirect allowlist. Build the app with `--dart-define=API_URL=https://duecare-xi.vercel.app` (see `apps/mobile/README.md`). `.vercelignore` keeps the mobile project out of web deployments.

## Deploy updates

After confirming the CLI is linked to the project above:

```sh
npx vercel@63.1.2 deploy --prod
```

This uploads local files directly and requires no Git commit or push. Production is public; preview deployments retain Vercel Authentication. Environment changes take effect with the next deployment.

## Operational checks

`/health` checks the API process; `/ready` also checks runtime database access, required tables, the background-job migration and dispatcher configuration. An unauthenticated POST to `/internal/jobs/advance` must return 401. The authenticated response reports only attempted/advanced counts. Check `cron.job_run_details` for scheduler failures, `net._http_response` for actual HTTP results, and Vercel runtime logs for safe error codes. A successful Cron SQL call alone does not prove the HTTP worker succeeded.

Build completion and health checks do not establish real Google consent, mailbox/Classroom synchronization, AI extraction, account deletion or large-upload acceptance. These flows require an eligible account and live acceptance separately. The Supabase advisor currently reports the managed `pg_net` extension in public, deny-all RLS on `public.alembic_version`, and disabled leaked-password protection; DueCare uses Google OAuth and does not expose the application tables through public PostgREST.
