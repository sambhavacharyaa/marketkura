# Deployment guide

MarketKuraa supports two deployment paths, both already set up in this repo:

- **[Path A — cPanel](#path-a-cpanel-git-deploy)**: push to `main`, click "Deploy HEAD Commit" in cPanel. Fully automated via [`.cpanel.yml`](.cpanel.yml) + [`deploy/cpanel_deploy.py`](deploy/cpanel_deploy.py). This is the path actually in use for marketkuraa.com.
- **[Path B — your own VPS](#path-b-vps-gunicorn--nginx--systemd)**: gunicorn + nginx + systemd, using the sample configs in [`deploy/`](deploy/).

Either way, read [Environment variables](#environment-variables) first — nothing deploys without those set.

## Environment variables

Copy `.env.example` to `.env` and fill it in. Nothing here is committed to git (`.env` is in `.gitignore`); production reads these from the host's own env-var config (cPanel's "Setup Python App" UI, or a systemd `EnvironmentFile` — see each path below), not from a checked-in `.env` file.

| Variable | Required | Notes |
|---|---|---|
| `DJANGO_SECRET_KEY` | **Yes** | Long random string. Generate one: `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"` |
| `ALLOWED_HOSTS` | **Yes** | Comma-separated, e.g. `marketkuraa.com,www.marketkuraa.com` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD` | **Yes** | PostgreSQL only — `prod` settings hardcode the `postgresql` engine, SQLite is dev-only |
| `DB_HOST`, `DB_PORT` | No | Default `localhost` / `5432` |
| `CSRF_TRUSTED_ORIGINS` | **Yes** | Comma-separated, e.g. `https://marketkuraa.com,https://www.marketkuraa.com` |
| `SECURE_SSL_REDIRECT` | No | Default `True` — set `False` only if TLS terminates somewhere this app can't see |
| `SECURE_HSTS_SECONDS` | No | Default `31536000` (1 year) |
| `BEHIND_PROXY` | If behind nginx/a load balancer | `True` makes Django trust `X-Forwarded-Proto` for HTTPS detection |
| `USE_X_FORWARDED_FOR` | If behind nginx/a load balancer | `True` so rate-limiting keys off the real client IP, not the proxy's |
| `REDIS_URL` | No | If unset, falls back to a DB-backed cache table (`manage.py createcachetable`) |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | No | Google sign-in; see [Local setup](README.md#google-login) in the README for how to create them. Omit both and the Google button just doesn't appear. |
| `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` | No | Cloudflare Turnstile on signup/contact. Omit both and those forms skip the widget. |
| `FINNHUB_API_KEY` | No | Live price/news on company pages (global tickers only). Free tier at [finnhub.io](https://finnhub.io). Omit it and `refresh_market_data` is a no-op — pages just show "no data yet," nothing breaks. |
| `SHOW_COMING_SOON_WIDGETS` | No | Default `False`. Leave off until a real data source backs the home-feed placeholder widgets. |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | For password reset | Without real SMTP config, password-reset emails go nowhere |

## Path A: cPanel git deploy

This is what's actually wired up for production right now.

### One-time setup

1. **Setup Python App** (cPanel): create a Python 3.10 app at the domain, note the app's virtualenv path (`~/virtualenv/marketkura_app/3.10/`, matching the hardcoded path in [`.cpanel.yml`](.cpanel.yml) — update that path if your app name or Python version differs).
2. In that same screen, add every environment variable from the table above under "Environment variables." This is the *only* place secrets live — never in the repo, never in a committed `.env`.
3. **Git Version Control** (cPanel): add this repo (`https://github.com/sambhavacharyaa/marketkura.git`), pull branch `main`, deployment path matching the Python app's root.
4. Create the PostgreSQL database and user (cPanel → PostgreSQL Databases), matching the `DB_*` env vars.
5. First deploy only — SSH in and run once by hand, since the automated deploy assumes the app already exists:
   ```bash
   cd ~/marketkura_app
   ~/virtualenv/marketkura_app/3.10/bin/pip install -r requirements.txt
   DJANGO_SETTINGS_MODULE=marketkura.settings.prod ~/virtualenv/marketkura_app/3.10/bin/python manage.py migrate
   DJANGO_SETTINGS_MODULE=marketkura.settings.prod ~/virtualenv/marketkura_app/3.10/bin/python manage.py createsuperuser
   ```
6. Point the app's static/media file serving at `staticfiles/` and `media/` under the app root (cPanel Python App's own static file mapping, or your `passenger_wsgi.py`/`link_static.py` if you use one — `deploy/cpanel_deploy.py` deliberately never touches either file, see below).
7. Set up the [market-data refresh cron job](#scheduled-jobs) if you're using `FINNHUB_API_KEY`.

### Every deploy after that

Push to `main`, then in cPanel → Git Version Control → **Deploy HEAD Commit**. [`deploy/cpanel_deploy.py`](deploy/cpanel_deploy.py) runs automatically and:

1. Copies changed files from the git checkout into the live Passenger app folder (never touches `media/`, `staticfiles/`, `tmp/`, `public/`, `passenger_wsgi.py`, `link_static.py`, `.env`, or the virtualenv — those are server-only state, not part of the repo).
2. Installs `requirements.txt` only if it changed since the last deploy (sha256-stamped, so this is fast on most deploys).
3. **Backs up the database automatically** before running any pending migration (`pg_dump`, gzipped, into `~/backups/db/`, keeping the last 5). If `pg_dump` isn't found, the deploy stops *before* migrating rather than risk an unbacked-up schema change.
4. Runs `migrate`, `createcachetable`, `collectstatic`.
5. Touches `tmp/restart.txt` to restart the Passenger app.

If any step fails, the deploy stops and the app is **not** restarted — the live app keeps running the previous version. Check `~/marketkura_deploy.log` for what failed.

## Path B: VPS (gunicorn + nginx + systemd)

Sample configs: [`deploy/marketkura.service`](deploy/marketkura.service), [`deploy/nginx.conf`](deploy/nginx.conf).

1. Provision Postgres, create the database/user, set the `DB_*` env vars.
2. Clone the repo to `/srv/marketkura`, create a venv there, `pip install -r requirements.txt`.
3. Copy `.env.example` to `/srv/marketkura/.env`, fill it in (this is what `marketkura.service`'s `EnvironmentFile=` reads).
4. Run once:
   ```bash
   cd /srv/marketkura
   export DJANGO_SETTINGS_MODULE=marketkura.settings.prod
   .venv/bin/python manage.py migrate
   .venv/bin/python manage.py createcachetable    # skip this if REDIS_URL is set instead
   .venv/bin/python manage.py collectstatic --noinput
   .venv/bin/python manage.py createsuperuser
   ```
5. Install the systemd unit and nginx site:
   ```bash
   sudo cp deploy/marketkura.service /etc/systemd/system/
   sudo systemctl daemon-reload && sudo systemctl enable --now marketkura
   sudo cp deploy/nginx.conf /etc/nginx/sites-available/marketkuraa.com
   sudo ln -s /etc/nginx/sites-available/marketkuraa.com /etc/nginx/sites-enabled/
   sudo certbot --nginx -d marketkuraa.com -d www.marketkuraa.com   # or your own TLS setup
   sudo nginx -t && sudo systemctl reload nginx
   ```
6. Every later deploy: `git pull`, re-run `pip install -r requirements.txt` if it changed, `migrate`, `collectstatic`, then `sudo systemctl restart marketkura`. (Nothing here auto-backs-up the DB the way the cPanel path does — take your own `pg_dump` before migrating if you're scripting this.)
7. Set up the [market-data refresh cron job](#scheduled-jobs) if you're using `FINNHUB_API_KEY`.

## Scheduled jobs

**Company price/news refresh** — only needed if `FINNHUB_API_KEY` is set:

```cron
*/5 * * * * cd /path/to/marketkura.com && .venv/bin/python manage.py refresh_market_data >> /path/to/logs/refresh_market_data.log 2>&1
```

(On cPanel: Cron Jobs UI, same command but using the app's own venv path, e.g. `~/virtualenv/marketkura_app/3.10/bin/python`.) This covers global (non-NEPSE) tickers only — NEPSE-listed companies are refreshed by a separate command. Without the key set, the command is a clean no-op.

## Post-deploy checklist

- `python manage.py check --deploy --settings=marketkura.settings.prod` — should report no issues.
- Load the homepage and confirm no mixed-content warnings (HTTP/HTTPS) in the browser console.
- Log in as the superuser, confirm the admin at `/admin/` works.
- If `GOOGLE_CLIENT_ID` is set: confirm the OAuth redirect URI in Google Cloud Console exactly matches `https://<domain>/auth/google/login/callback/`.
- Confirm `/robots.txt` and `/sitemap.xml` resolve.
- Nepali translations are already compiled and committed (`locale/ne/LC_MESSAGES/django.mo`) — no gettext needed on the server, but re-run `compilemessages` locally and commit if you've changed any translatable string.
- The CSP header ships **report-only** in production (`ContentSecurityPolicyReportOnlyMiddleware` in `prod.py`) — it logs violations to the browser console without blocking anything. Watch the console on a few real pages before ever switching it to an enforcing policy.

## Before public launch

These need people, not more code:

- Seed 20–30 real threads — an empty platform reads as abandoned to a first-time visitor.
- Have a native speaker review the Nepali translations, especially the legal/compliance wording (guidelines, disclaimer, privacy policy).
- Create the Google OAuth credentials and configure real SMTP (password-reset emails are silently dropped without it).
- Decide which categories, if any, should be high-trust (`min_karma` / `requires_verified` in the admin).
- Load-test on the actual target host — not done as part of this repo.

## Rollback

- **cPanel path**: `git revert` the bad commit (or `git reset --hard` to the last good one, force-push), then Deploy HEAD Commit again. The automated DB backup in `~/backups/db/` covers the schema side if a migration needs undoing — restore with `pg_restore`/`psql` before re-deploying.
- **VPS path**: same `git revert`/reset, re-run the deploy steps, `sudo systemctl restart marketkura`. Restore from whatever `pg_dump` you took before the migration that needs undoing.
