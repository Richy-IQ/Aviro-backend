# Deploying Aviro

**Frontend on Vercel, backend and database on Railway.**

Deploy the backend first — the frontend needs its address.

## Railway: Postgres

Add the Postgres plugin. It supplies `DATABASE_URL`.

## Railway: aviro-backend

Deploy from `Richy-IQ/Aviro-backend`. It builds the Dockerfile's `production`
target; `railway.json` points the health check at `/api/health/`, which touches
the database rather than returning a static 200.

| Variable | Value |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` |
| `DJANGO_SECRET_KEY` | a long random string |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `DJANGO_ALLOWED_HOSTS` | the backend's Railway domain |
| `CORS_ALLOWED_ORIGINS` | the Vercel domain, with scheme |
| `OTP_DELIVERY` | `console` until a provider is wired — see below |

Generate the secret key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Migrations run on start, so there is no release step to forget. Create your
admin user once from the Railway shell:

```bash
python manage.py createsuperuser
```

### A note on CORS

`CORS_ALLOWED_ORIGINS` is set for completeness, but it is not what will break
first. No browser ever calls Django: the phone talks to the Next server on
Vercel, and that server talks to Railway. CORS is a browser mechanism, so
server-to-server calls never trigger it. `DJANGO_ALLOWED_HOSTS` is the setting
that genuinely matters — get it wrong and every request returns 400.

## Vercel: aviro-web

Import `Richy-IQ/Aviro-web`. Vercel detects Next.js and needs no build
configuration; `next.config.ts` already switches off standalone output when it
sees Vercel's own builder.

| Variable | Value |
| --- | --- |
| `API_URL` | the Railway backend URL plus `/api`, e.g. `https://aviro-backend-production.up.railway.app/api` |

Set it for Production, Preview and Development, or preview deploys will fail
the startup check.

There is deliberately **no `NEXT_PUBLIC_` variable**. Every request goes
through a Server Action or route handler on the Next server, which is what
allows the session to live in an httpOnly cookie the browser cannot read.

The repository also contains a `Dockerfile` and `railway.json`. Vercel ignores
both; they exist so the frontend can be self-hosted if you ever move it.

## After the first deploy

1. `https://<backend>/api/health/` returns `{"status":"ok","database":"ok"}`
2. Open the Vercel URL and request a sign-in code
3. Read the code from Railway's log viewer — it prints as a labelled block
4. Sign in, create a farm, log a day

If step 2 fails, check `API_URL` on Vercel before anything else.

## Known gaps

- **OTP delivery has no provider.** With `OTP_DELIVERY=console` the code is
  printed to the Railway logs, which is fine for you and unusable for farmers.
  Implement `_deliver()` in `apps/accounts/services/otp.py` against WhatsApp
  Business, with SMS as a fallback, before real users arrive. Leaving
  `OTP_DELIVERY` unset in production makes sign-in raise rather than silently
  do nothing.
- **The growing guide has not been reviewed by a veterinarian.** It is the
  highest-risk content in the product.
- **Service worker registration is unverified on a real device.** It never
  registers on localhost by design, so this has to be checked on the deployed
  site.
- **The frontend has no tests.**

## The npm install-scripts warning

`unrs-resolver … not yet covered by allowScripts` is expected and harmless. It
arrives through `eslint-config-next` and is only used by the linter; the build
never touches it.
