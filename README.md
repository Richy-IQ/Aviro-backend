# Aviro API

Farm intelligence for Nigerian poultry farmers. Django + DRF, PostgreSQL,
Docker.

## Running it

Development — Postgres and the API with autoreload:

```bash
docker compose up
```

The API is then on `http://localhost:8000`, and the frontend's
`NEXT_PUBLIC_API_URL` already points at `http://localhost:8000/api`.

Production-shaped, to check the real image before deploying:

```bash
cp .env.example .env    # fill in the production values first
docker compose -f docker-compose.prod.yml up --build
```

Tests and linting:

```bash
docker compose run --rm api pytest
docker compose run --rm api ruff check .
```

## How it is arranged

```
config/settings/   base, development, production — nothing hidden behind `if DEBUG`
apps/common/       base models, error envelope, pagination, health check
apps/accounts/     phone identity, OTP sign-in
apps/farms/        farms, pens, membership and roles
apps/flocks/       bird types, batches, daily logs, sales
apps/insights/     alerts and benchmarks, both derived
apps/markets/      feed prices and buyers
```

Views are thin. They resolve the farm, check the membership, validate input and
hand off. Business rules live in `services/`, which means they can be read and
tested without HTTP.

## Decisions worth knowing

**The account is a person, not a farm.** A phone number identifies a user;
`Membership` carries their role and pen scope on a given farm. This is what
lets an invited manager verify their own number and join an existing farm.

**Metrics are derived, never stored.** Feed conversion, mortality, cost per
bird and the sell window are computed from the daily logs on read. Storing them
would let a corrected log and a stale figure disagree, and a farmer would have
no way to know which to trust.

**Cycle length belongs to the bird type.** A broiler finishes in 42 days; a
layer rears for 140 before her first egg. Vaccination schedules are scoped the
same way, so a layer keeper is never shown broiler dates.

**Logging a day twice updates it.** A farmer who cannot remember whether they
logged should be able to log again — which is also what makes an offline queue
safe to replay.

**Sign-in is two screens.** Request a code, enter it. The account is created on
first successful verification; name and location are collected later, on the
screens where they change an answer.

## Things left open

- **OTP delivery has no provider.** Development prints the code to the log.
  Production raises rather than pretending to send. Wire WhatsApp Business (with
  SMS fallback) in `apps/accounts/services/otp.py`, and end the SMS body with
  `@<domain> #<code>` so the browser's Web OTP API can autofill it.
- **The growth curve is characterised for broilers only.** Other bird types
  return `null` for weight and feed conversion rather than an invented number.
- **Benchmarks fall back to published industry figures** until there are at
  least 20 closed cycles of a bird type. The response says which source it used.
