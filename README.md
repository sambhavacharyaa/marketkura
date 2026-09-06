# MarketKuraa

MarketKuraa is a Django-based investor community and discussion platform inspired by the blueprint in `marketkuraa-blueprint.md`. The project focuses on building a local-first, public forum where users can discuss markets, investing, startups, and finance topics in a structured and searchable way.

This repository is the foundation for the MVP: a forum with categories, posts, comments, user profiles, and moderation primitives.

## Project vision

MarketKuraa aims to become a Nepal-and-beyond investor community with a global lens. The MVP is intentionally narrow and practical:

- public reading access
- category-based discussion threads
- post and comment system
- user profiles and reputation fields
- moderation and reporting capabilities
- search-friendly content structure
- scalable Django foundations for future V1/V2 growth

## Current status

This codebase already includes the core backend models and template views for an MVP forum:

- custom user model
- categories
- posts with discussion/thesis types
- threaded comments
- tags and company-style associations
- watchlists and verification requests
- admin moderation/report models
- base homepage, category pages, and post detail views

## Tech stack

- Django 5.1
- Django REST Framework
- django-htmx
- PostgreSQL-ready configuration (with SQLite for local development)
- Python-dotenv
- Pillow
- Template-based frontend with Django templates

## Project structure

```text
marketkura/
├── asgi.py
├── settings/
│   ├── __init__.py
│   ├── base.py
│   ├── dev.py
│   └── prod.py
├── urls.py
├── wsgi.py
├── __init__.py
community/
├── admin.py
├── apps.py
├── migrations/
├── models.py
├── tests.py
├── urls.py
├── views.py
├── __init__.py
templates/
├── base.html
├── home.html
├── category_detail.html
├── post_detail.html
static/
README.md
marketkuraa-blueprint.md
requirements.txt
manage.py
db.sqlite3
```

## Key features in the codebase

### Community model
The main app models include:

- `User` — custom user model with bio, avatar, reputation, verification status
- `Category` — forum/category grouping
- `Post` — discussion or thesis posts
- `Comment` — nested comment support with parent-child threading
- `Tag` and `PostTag` — topic/company tagging
- `Watchlist` — future V1 feature foundation
- `VerificationRequest` — verification application flow
- `Report` — moderation/reporting capability

### Views and pages
The app currently serves:

- home feed
- category-specific listing pages
- post detail page

These live in `community/views.py` and the templates under `templates/`.

## Local development setup

### 1) Clone the repo

```bash
git clone <your-repo-url>
cd marketkura
```

### 2) Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3) Install dependencies

```bash
pip install -r requirements.txt
```

### 4) Configure environment variables

Create a `.env` file in the project root:

```env
DJANGO_SECRET_KEY=your-secret-key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
```

The project loads environment variables automatically via `python-dotenv` in `marketkura/settings/base.py`.

### 5) Run migrations

```bash
python manage.py migrate --settings=marketkura.settings.dev
```

### 6) Create a superuser

```bash
python manage.py createsuperuser --settings=marketkura.settings.dev
```

### 7) Start the development server

```bash
python manage.py runserver --settings=marketkura.settings.dev
```

Then open:

```text
http://127.0.0.1:8000/
```

For production, set the variables from `.env.example` in the deployment environment, then run:

```bash
python manage.py migrate --settings=marketkura.settings.prod
gunicorn marketkura.wsgi:application
```

## Admin panel

Once you create a superuser, you can access the Django admin interface at:

```text
http://127.0.0.1:8000/admin/
```

This is useful for managing categories, users, posts, reports, and verification items during the MVP stage.

## Running tests

```bash
python manage.py test --settings=marketkura.settings.dev
```

## Database notes

The default configuration uses SQLite for local development:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}
```

For production, the project is intended to be upgraded to PostgreSQL as described in the blueprint.

## Important blueprint alignment

This repository follows the product direction in `marketkuraa-blueprint.md`:

- forum-first MVP
- categories and discussion threads as central product
- ban on overengineering for the initial weeks
- preparation for later investor features like thesis posts, verification, company pages, and watchlists
- use of Django + HTMX rather than a large separate frontend stack for the first build

## Roadmap direction

### MVP now
- user authentication and profiles
- categories and feed
- post/comment features
- moderation and reporting
- simple search-friendly structure

### Planned next phases
- thesis posts and structured investor content
- tags/company pages
- verification requests and reputation system
- notifications and improved search
- live market data and more advanced product surfaces later

## License

This project does not currently define a license file. Add one if you intend to distribute it publicly or commercially.

## Notes

This project is intentionally built as a practical, lightweight Django community app rather than a heavy frontend architecture. It is designed to support rapid implementation and iteration while leaving space for the wider MarketKuraa vision to evolve.

If you want, the next step could be adding:

- real authentication UI
- post creation forms
- comment creation flow
- admin moderation dashboard polish
- API endpoints for mobile or frontend clients
