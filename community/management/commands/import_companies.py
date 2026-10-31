"""Bulk-create or update company Tag rows from a CSV or JSON file, so listing a whole market's
worth of tickers doesn't mean adding each one by hand through admin or waiting for someone to
mention it in a post.

Usage:
    manage.py import_companies path/to/companies.csv
    manage.py import_companies path/to/companies.json
    manage.py import_companies path/to/companies.csv --dry-run

CSV needs a header row with at least "ticker" and "name" columns; "company_name" and
"description" are optional. JSON is a list of objects with the same keys. Example CSV:

    ticker,name,company_name,description
    NABIL,NABIL,Nabil Bank Limited,Nepal's first private sector commercial bank.
    HIDCL,HIDCL,Hydroelectricity Investment and Development Company Limited,

Matching is by ticker first, then by slug (derived from the ticker), so re-running the same file
is safe — it updates existing rows instead of creating duplicates.
"""
import csv
import json

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from community.models import Tag


class Command(BaseCommand):
    help = 'Bulk create/update company Tag records from a CSV or JSON file of ticker,name,company_name,description rows.'

    def add_arguments(self, parser):
        parser.add_argument('file', help='Path to a .csv or .json file of companies')
        parser.add_argument('--dry-run', action='store_true', help='Report what would change without saving anything')

    def handle(self, *args, **options):
        path = options['file']
        dry_run = options['dry_run']
        rows = self._read_rows(path)

        created = updated = unchanged = skipped = 0
        for row in rows:
            ticker = (row.get('ticker') or '').strip().upper()
            name = (row.get('name') or '').strip()
            if not ticker or not name:
                skipped += 1
                continue
            company_name = (row.get('company_name') or '').strip()
            description = (row.get('description') or '').strip()
            slug = slugify(ticker, allow_unicode=True) or slugify(name, allow_unicode=True)

            tag = Tag.objects.filter(ticker__iexact=ticker).first() or Tag.objects.filter(slug=slug).first()
            if tag:
                changed = False
                for field, value in (('name', name), ('company_name', company_name), ('description', description)):
                    if value and getattr(tag, field) != value:
                        setattr(tag, field, value)
                        changed = True
                if not tag.is_company:
                    tag.is_company = True
                    changed = True
                if changed:
                    updated += 1
                    if not dry_run:
                        tag.save()
                else:
                    unchanged += 1
            else:
                created += 1
                if not dry_run:
                    Tag.objects.create(ticker=ticker, name=name, slug=slug, company_name=company_name, description=description, is_company=True)

        prefix = 'Would ' if dry_run else ''
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}create {created}, {prefix}update {updated} ({unchanged} already up to date), skipped {skipped} row(s) missing ticker/name.'
        ))

    def _read_rows(self, path):
        try:
            if path.endswith('.json'):
                with open(path, encoding='utf-8') as f:
                    return json.load(f)
            with open(path, encoding='utf-8', newline='') as f:
                return list(csv.DictReader(f))
        except FileNotFoundError:
            raise CommandError(f'No such file: {path}')
        except (json.JSONDecodeError, csv.Error) as exc:
            raise CommandError(f'Could not parse {path}: {exc}')
