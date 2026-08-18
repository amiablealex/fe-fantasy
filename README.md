# Formula E Fantasy

A fantasy team game for the ABB FIA Formula E World Championship. Pick four
drivers and one team; score from real race weekend performance.

`docs/SPEC.md` is the single source of truth for game rules, scoring, domain
model, API quirks and roadmap. Read it before changing anything structural.

**Status: Phase 0 — foundations.** Auth, config, admin skeleton and deployment.
No game logic, no data ingestion, and no design language yet. The templates here
are deliberately unstyled and will be replaced wholesale in Phase 3.

---

## Local setup (Raspberry Pi, Debian 12)

Runtime is Python 3.11.2 and PostgreSQL 18.4, matching production exactly.

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
pip install -r requirements.txt
cp .env.example .env
```

Then edit `.env` and set `SECRET_KEY` to something random:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 3. Schema

```bash
export FLASK_APP=wsgi.py
flask db upgrade
```

Verify:

```bash
psql -U fe_user -h localhost -d fe_fantasy -c '\dt'
```

Expect five tables: `alembic_version`, `users`, `password_reset_tokens`,
`leagues`, `league_memberships`.

### 4. Run

```bash
flask run --host 0.0.0.0
curl -s localhost:5000/health
```

`{"status":"ok","version":"0.1.0"}` means the app is up and the database is
reachable. A 500 here is almost always the database, not the app.

### 5. Tests

```bash
pytest
```

Twenty-five tests, run against `fe_fantasy_test`. They create and drop the
schema per test, so never point `TEST_DATABASE_URL` at the development database.

---

## Useful commands

```bash
flask config-check          # print resolved config with secrets masked
flask set-admin you@example.com
flask set-admin you@example.com --revoke
flask db upgrade
flask db downgrade -1
```

`flask config-check` is the first thing to run when production behaves
differently from local. The usual answer is an environment variable that was
never set and quietly fell back to a default.

---

## Deployment (Railway)

One service in Phase 0. The worker service is added in Phase 1, when there is
something to poll.

**Service settings**

- Build: Nixpacks (automatic)
- Start command:
  `gunicorn wsgi:app --workers 2 --timeout 60 --bind 0.0.0.0:$PORT`
- Pre-deploy command: `flask db upgrade`

**Environment variables**

| Variable | Value |
|---|---|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | a fresh 48-byte random string, not the local one |
| `APP_BASE_URL` | `https://fe.kitsniff.com` |
| `RESEND_API_KEY` | from Resend |
| `RESEND_FROM_EMAIL` | `noreply@fe.kitsniff.com` |
| `RESEND_FROM_NAME` | `Formula E Fantasy` |
| `DATABASE_URL` | injected automatically when Postgres is attached |

The application refuses to start in production if `SECRET_KEY` is missing or
still the development default, if `DATABASE_URL` is unset, or if `APP_BASE_URL`
is not https. A crash loop on first deploy with `ConfigError` in the logs is
that check doing its job — read the message, it names the variable.

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

Verify with `curl -sI https://fe.kitsniff.com/health`, then sign in and reload:
a session that survives proves both the secure cookie and `ProxyFix` are working.

---

## Layout

```
app/
  config.py        environment and Flask only — no point values, no colours
  extensions.py    db, migrate, login_manager, csrf
  auth/            register, login, reset, account; forms, email, rate limiting
  admin/           read-mostly admin surface
  models/          user, league (calendar/grid/result arrive in Phase 1)
  providers/       data provider abstraction — errors only until Phase 1
  scoring/         versioned rulesets; imports nothing from Flask or SQLAlchemy
  static/css/      base.css now; tokens.css and the design system in Phase 3
worker/            Phase 1
sim/               Phase 2 — Season 12 scoring simulation, standalone
tests/fixtures/    committed API probe JSON
```

Three constraints worth keeping:

- **`app/scoring/` must never import Flask or SQLAlchemy.** It takes plain
  result dicts and returns points, which is what lets `sim/` run the Season 12
  simulation without a database. A test asserts this.
- **Point values do not live in `config.py`.** Config holds values where only
  the current one matters; scoring values need every past value to stay
  retrievable, because a completed round must keep scoring the way it scored at
  the time.
- **Colour does not live in Python.** Design tokens are CSS custom properties.
