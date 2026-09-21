# Formula E Fantasy

A fantasy team game for the ABB FIA Formula E World Championship. Pick four
drivers and one team; score from real race weekend performance.

`docs/SPEC.md` is the single source of truth for game rules, scoring, domain
model, API quirks and roadmap. Read it before changing anything structural.

**Status: Phases 0–8 complete; Phase 9, production readiness, in progress.**
The game is finished and Season 12 is backfilled locally. Production is live
and waiting on the Season 13 calendar, which the worker picks up on its own.
See `docs/SPEC.md` §8.

---

## Local setup (Raspberry Pi, Debian 12)

Runtime is Python 3.11.2 and PostgreSQL 18, matching production's major
version so `pg_dump` restores in both directions.

### 1. Database

```bash
sudo -u postgres psql <<'SQL'
CREATE ROLE fe_user WITH LOGIN PASSWORD 'fe_pass';
CREATE DATABASE fe_fantasy OWNER fe_user;
CREATE DATABASE fe_fantasy_test OWNER fe_user;
SQL
```

Confirm both exist:

```bash
psql -U fe_user -h localhost -l | grep fe_fantasy
```

### 2. Application

```bash
cd ~/projects/fe-fantasy
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Then edit `.env` and set `SECRET_KEY` to something random:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set `OCB_API_KEY` too if you want to sync data locally. Quote any multi-word
value: python-dotenv tolerates `NAME=Formula E Fantasy`, but `source .env`
does not.

### 3. Schema

```bash
export FLASK_APP=wsgi.py
flask db upgrade
flask db current
```

`flask db current` should report the `0006` revision as head.

### 4. Run

```bash
flask run --host 0.0.0.0
curl -s localhost:5000/health
```

A JSON `"status":"ok"` means the app is up and the database is reachable. A
500 here is almost always the database, not the app.

Every Season 12 deadline is in the past, so the lineup editor has nothing to
open against. `FANTASY_NOW` in `.env` moves the app's clock; it warns on every
request that uses it and is ignored by the worker (SPEC.md §4.3).

### 5. Tests

```bash
pytest
```

Run against `fe_fantasy_test`. The suite creates and drops the schema per
test, so never point `TEST_DATABASE_URL` at the development database. It takes
about six minutes on the Pi (SPEC.md §7).

---

## Useful commands

```bash
flask config-check          # print resolved config with secrets masked
flask set-admin you@example.com
flask set-admin you@example.com --revoke
flask sync-season           # calendar, grid and deadlines; --help for arguments
flask backfill-results      # fetch missing session results; safe to rerun
flask score-season          # rescore rounds whose results have changed
python -m worker.tick       # one worker run, exactly as cron runs it
flask db upgrade
flask db downgrade -1
```

`flask config-check` is the first thing to run when production behaves
differently from local. The usual answer is an environment variable that was
never set and quietly fell back to a default.

---

## Deployment (Railway)

Three services: web, worker, Postgres. Start commands come from the Procfile.

**Web service**

- Build: Nixpacks (automatic)
- Start command: one gunicorn process, four threads (see `Procfile`)
- Pre-deploy command: `flask db upgrade`
- Healthcheck path: `/health`
- Serverless: on. It sleeps after ten minutes without outbound traffic; the
  first request after a sleep takes a few seconds.

**Worker service**

- Start command: `python -m worker.tick`
- Cron schedule: `*/5 * * * *`, which must match `POLL_INTERVAL_SECONDS`
- Restart policy: Never
- No healthcheck, no pre-deploy command, Serverless off

Each run does whatever is due and exits. `/admin/health` is where to look
for liveness; the cron run list shows exit codes.

Railway can silently disconnect from GitHub. If a push does not deploy, check
Settings → Source before debugging anything else.

**Environment variables**

| Variable | Value |
|---|---|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | a fresh 48-byte random string, not the local one |
| `APP_BASE_URL` | `https://fe.kitsniff.com` |
| `OCB_API_KEY` | from Orange Cat Blacktop; the worker cannot run without it |
| `RESEND_API_KEY` | from Resend |
| `RESEND_FROM_EMAIL` | `noreply@fe.kitsniff.com` |
| `RESEND_FROM_NAME` | `Formula E Fantasy` |
| `DATABASE_URL` | injected automatically when Postgres is attached |

The application refuses to start in production if `SECRET_KEY` is missing or
still the development default, if `DATABASE_URL` is unset, if `APP_BASE_URL`
is not https, or if `DISPLAY_TIMEZONE` names an unknown zone. A crash loop
with `ConfigError` in the logs is that check doing its job — read the
message, it names the variable.

### Custom domain

1. Railway → service → Settings → Networking → Custom Domain → `fe.kitsniff.com`.
   Railway returns a target hostname.
2. Cloudflare → `kitsniff.com` → DNS → add:

   | Type | Name | Target | Proxy |
   |---|---|---|---|
   | CNAME | `fe` | the Railway target | Proxied |

3. Cloudflare SSL/TLS mode must be **Full (strict)**. Flexible sends plaintext
   to Railway, which breaks `SESSION_COOKIE_SECURE` in a way that looks like a
   login bug rather than a TLS setting.
4. Delete the generated `*.up.railway.app` domain once the custom domain
   works. Client IPs are read from `CF-Connecting-IP`, which is only
   trustworthy for traffic that came through Cloudflare.

Verify with `curl -sI https://fe.kitsniff.com/health`, then sign in and
reload: a session that survives proves the secure cookie is working.

---

## Layout

The full tree is in `docs/SPEC.md` §12.

```
app/
  config.py        environment and Flask only — no point values, no colours
  scoring/         rules, engine, lineups; imports nothing from Flask or SQLAlchemy
  providers/       the only code that sees a vendor payload
  ingest/          season sync, results, conflicts, checks
  meetings/        the scoring pass, stored-score reads, the weekend views
  lineups/         the roster, the draft, the editor
  leagues/         visibility, membership, standings, profiles
  pages/           how to play, about, privacy, terms
  static/          tokens.css, primitives.css, fonts, htmx, favicon
worker/            cron entrypoint, poll and sync jobs, run recording
sim/               Season 12 scoring simulation, standalone
tests/fixtures/    committed API probe JSON
```

Four constraints worth keeping:

- **`app/scoring/` must never import Flask or SQLAlchemy.** It takes plain
  result dicts and returns points, which is what lets `sim/` run without a
  database. A test asserts this.
- **Point values do not live in `config.py`.** They live in versioned
  rulesets in `app/scoring/rules.py`, because a completed round must keep
  scoring the way it scored at the time.
- **Colour does not live in Python.** Design tokens are CSS custom properties.
- **The application never imports `worker/`.** The worker may import from the
  application; anything both need lives on the application side.
