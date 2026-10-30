# MarketKuraa

MarketKuraa is a public, global investor community: a Django + HTMX forum with company pages, self-reported theses, verified badges and moderation. The product plan lives in [marketkuraa-blueprint.md](marketkuraa-blueprint.md).

## Blueprint coverage

| Blueprint | Status |
|---|---|
| **MVP (Phase 1)** | |
| Email + Google login | Done. Log in with username or email. Google appears once `GOOGLE_CLIENT_ID/SECRET` are set. |
| Categories, posts, threaded comments, upvotes | Done. Comments nest to any depth, have votes, edit/delete, and report. The six blueprint categories are seeded. |
| Profiles, reputation, follow | Done. Karma is upvotes received from others (self-votes are blocked). Follow members and categories; "Following" feed tab. |
| Search | Done. PostgreSQL full-text (ranked, `"phrase"` and `-exclude` syntax) plus substring matching for tickers and Nepali text. SQLite falls back to substring. |
| Moderation | Done. Report post/comment, staff queue sorted by report count, remove/restore/lock, shadow-ban, pump-and-dump watch. |
| Settings, mobile-responsive UI | Done. Profile, avatar, email, password change/reset. |
| **V1 (Phase 2)** | |
| Thesis posts, watchlists, verification flow, company pages, notifications, filters | Done. Verification asks for a badge type (analyst, professional, fund manager, contributor). |
| **V2 (Phase 3)** | |
| AMA / structured Q&A | Done. Verified members host; questions vs. host answers; closes on schedule. |
| Founder/startup profiles + discovery | Done. Moderator-approved directory with stage/sector filters. |
| Reputation-based unlocks | Done. Startup profiles need karma or a badge. Categories can require karma or verification (set in admin). |
| Live market data | **Not built, by design.** Blueprint §19 says to vet data licensing/ToS first. |
| **Phase 4 (premium, public API, events, jobs)** | **Not built.** The blueprint says not to spec it yet. A first-party REST API (§12) is built. |
| **Cross-cutting** | |
| Trust and safety | New accounts: 3 posts/day and 20 comments/day for 7 days. Login lockout after 5 failures. Sign-up and password-reset throttles. Markdown sanitised with an allow-list. Open redirects closed. |
| SEO | Clean URLs (`/post/<title>-<id>/`, `/company/<slug>/`, `/category/<slug>/`), sitemap, robots.txt, canonical + Open Graph, schema.org `DiscussionForumPosting` / `QAPage`. Public read, gated write. |
| Legal (§19) | Site-wide disclaimer, community guidelines (bans coordinated hype), verification framed as identity-only. |
| Bilingual | English and Nepali (see below). |

## Stack

Django 5.2, Django REST Framework, HTMX (vendored in `static/js`), django-allauth (Google only), PostgreSQL in production, SQLite for local development.

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # edit values
python manage.py migrate --settings=marketkura.settings.dev
python manage.py createsuperuser --settings=marketkura.settings.dev
python manage.py runserver --settings=marketkura.settings.dev
```

Migrations seed the six categories. Add companies by mentioning a ticker in a post, or in the admin.

### Google login

Create an OAuth client in Google Cloud Console with the authorised redirect URI `https://<domain>/auth/google/login/callback/` (`http://localhost:8000/auth/google/login/callback/` locally), then set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.

### Languages

The UI is translated to Nepali in `locale/ne/`. After editing translatable strings:

```bash
python manage.py makemessages -l ne --no-location
# edit locale/ne/LC_MESSAGES/django.po
python manage.py compilemessages
```

The compiled `.mo` file is committed so production needs no gettext. The Nepali text should be reviewed by a native speaker before launch, especially the legal wording.

## Tests

```bash
python manage.py test --settings=marketkura.settings.dev
```

Run against PostgreSQL to exercise ranked full-text search (two tests are skipped on SQLite):

```bash
DB_NAME=marketkura DB_USER=postgres python manage.py test --settings=marketkura.settings.dev_postgres
```

## Moderation guide

- **Queue:** `/moderation/` (staff). Reports are grouped per item, most-reported first.
- **Shadow-ban:** the member keeps posting normally but nobody else sees their posts or comments, and they are not notified. Lift it from any of their posts, or in the admin.
- **High-trust categories:** in the admin, set `min_karma` or `requires_verified` on a category.
- **Tuning:** limits live in `marketkura/settings/base.py` (`NEW_ACCOUNT_*`, `PUMP_WATCH_*`, `LOGIN_*`, `REPUTATION_UNLOCKS`).

## REST API

Token auth (`Authorization: Token <key>`) or session. Reads are public; writes need a token. Rules are the same as on the website.

```
POST /api/auth/signup            POST /api/auth/login
GET  /api/categories/
GET  /api/posts/?category=&tag=&type=&q=      POST /api/posts/
GET  /api/posts/{id}/
GET  /api/posts/{id}/comments/   POST /api/posts/{id}/comments/   (body, optional parent)
POST /api/posts/{id}/upvote      (toggles)
GET  /api/users/{username}/
POST /api/verification/apply
GET  /api/tags/{slug}/posts      (company page data)
POST /api/reports/               (post or comment, category, reason)
```

## Production deployment

1. Set the variables from `.env.example` (at minimum `DJANGO_SECRET_KEY`, `ALLOWED_HOSTS`, `DB_*`, `CSRF_TRUSTED_ORIGINS`; add `BEHIND_PROXY=True` and `USE_X_FORWARDED_FOR=True` behind nginx).
2. Run:
   ```bash
   export DJANGO_SETTINGS_MODULE=marketkura.settings.prod
   python manage.py migrate
   python manage.py createcachetable    # shared cache for rate limiting; or set REDIS_URL instead
   python manage.py collectstatic --noinput
   ```
3. Serve with gunicorn behind nginx. Samples are in [deploy/](deploy/).

`python manage.py check --deploy --settings=marketkura.settings.prod` reports no issues.

## Before public launch

These need people, not code:

- Seed 20 to 30 real threads (blueprint §19, empty-platform risk).
- Have a native speaker review the Nepali translations.
- Create the Google OAuth credentials and configure email sending (password reset).
- Decide which categories, if any, should be high-trust.
- Run load testing on the target VPS (not done here).
