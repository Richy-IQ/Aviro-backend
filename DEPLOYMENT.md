# Deploying Aviro to Railway

Three services in one Railway project: **Postgres**, **aviro-backend**, and
**aviro-web**. Deploy them in that order — the frontend needs the backend's
address, and the backend needs the frontend's.

## 1. Postgres

Add the Postgres plugin. It provides `DATABASE_URL`, which the backend reads
directly.

## 2. aviro-backend

Deploy from `Richy-IQ/Aviro-backend`. It builds from the Dockerfile's
`production` target; `railway.json` sets the health check to `/api/health/`.

Variables:

| Variable | Value |
| --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.production` |
| `DJANGO_SECRET_KEY` | a long random string — generate one, never reuse the dev value |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
| `DJANGO_ALLOWED_HOSTS` | the backend's own domain, e.g. `aviro-backend-production.up.railway.app` |
| `CORS_ALLOWED_ORIGINS` | the **frontend's** domain, with scheme |
| `WEB_CONCURRENCY` | `3` to start |

Generate a secret key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

`CORS_ALLOWED_ORIGINS` is the chicken and egg: deploy the backend first with a
placeholder, then come back and set it once the frontend has a domain.

Migrations run automatically on start — see `docker-entrypoint.sh`. There is no
separate release step to forget.

Create your admin user once, from the Railway shell:

```bash
python manage.py createsuperuser
```

## 3. aviro-web

Deploy from `Richy-IQ/Aviro-web`. Builds from its Dockerfile, no build
arguments needed.

| Variable | Value |
| --- | --- |
| `API_URL` | the backend's public URL plus `/api`, e.g. `https://aviro-backend-production.up.railway.app/api` |
| `API_INTERNAL_URL` | *optional* — `http://aviro-backend.railway.internal:8080/api` to keep API traffic on the private network |

There is deliberately **no `NEXT_PUBLIC_` variable**. The browser never calls
Django: every request goes through a Server Action or route handler on the
Next server, which is what allows the session to live in an httpOnly cookie.
So the API address is read at run time and the same image can be promoted
between environments without rebuilding.

## Both services

`PORT` is injected by Railway and both images bind it. Nothing binds a fixed
port, which is the usual reason a Railway deploy builds green and is
unreachable.

## After the first deploy, check

1. `https://<backend>/api/health/` returns `{"status":"ok","database":"ok"}`
2. Sign-in works end to end — this is the real CORS test
3. `https://<frontend>/manifest.webmanifest` loads, and the app offers to
   install on a phone

## Known gaps at launch

- **OTP delivery has no provider.** Production raises rather than pretending to
  send, so sign-in will fail until you wire WhatsApp Business or an SMS gateway
  in `apps/accounts/services/otp.py`. Set `OTP_DELIVERY=console` to read codes
  from the logs while testing.
- **The growing guide has not been reviewed by a vet.** It is the highest-risk
  content in the product.
- **Service worker registration is unverified** on a real device.
