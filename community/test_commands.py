import csv
import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.test import TestCase

from .models import Tag


class ImportCompaniesTests(TestCase):
    def write_csv(self, rows):
        path = Path(tempfile.mkstemp(suffix='.csv')[1])
        with path.open('w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['ticker', 'name', 'company_name', 'description'])
            writer.writeheader()
            writer.writerows(rows)
        return path

    def write_json(self, rows):
        path = Path(tempfile.mkstemp(suffix='.json')[1])
        path.write_text(json.dumps(rows), encoding='utf-8')
        return path

    def call(self, path, *args):
        out = StringIO()
        call_command('import_companies', str(path), *args, stdout=out)
        return out.getvalue()

    def test_creates_new_companies_from_csv(self):
        path = self.write_csv([
            {'ticker': 'nabil', 'name': 'NABIL', 'company_name': 'Nabil Bank Limited', 'description': ''},
            {'ticker': 'HIDCL', 'name': 'HIDCL', 'company_name': '', 'description': ''},
        ])
        output = self.call(path)
        self.assertIn('create 2', output)
        nabil = Tag.objects.get(ticker='NABIL')
        self.assertEqual((nabil.company_name, nabil.is_company), ('Nabil Bank Limited', True))
        self.assertTrue(Tag.objects.filter(ticker='HIDCL', is_company=True).exists())

    def test_rerunning_the_same_file_is_a_no_op(self):
        path = self.write_csv([{'ticker': 'NABIL', 'name': 'NABIL', 'company_name': 'Nabil Bank Limited', 'description': ''}])
        self.call(path)
        second = self.call(path)
        self.assertIn('create 0', second)
        self.assertIn('1 already up to date', second)
        self.assertEqual(Tag.objects.filter(ticker='NABIL').count(), 1)

    def test_rerunning_with_changed_fields_updates_not_duplicates(self):
        path = self.write_csv([{'ticker': 'NABIL', 'name': 'NABIL', 'company_name': 'Old name', 'description': ''}])
        self.call(path)
        updated_path = self.write_csv([{'ticker': 'NABIL', 'name': 'NABIL', 'company_name': 'Nabil Bank Limited', 'description': ''}])
        output = self.call(updated_path)
        self.assertIn('update 1', output)
        self.assertEqual(Tag.objects.filter(ticker='NABIL').count(), 1)
        self.assertEqual(Tag.objects.get(ticker='NABIL').company_name, 'Nabil Bank Limited')

    def test_matches_an_existing_tag_by_slug_even_if_it_was_not_flagged_as_a_company(self):
        # A topic tag created from a post's #hashtag field (is_company=False) with a slug that
        # happens to match an imported ticker should be promoted, not duplicated.
        Tag.objects.create(name='NABIL', slug='nabil', is_company=False)
        self.call(self.write_csv([{'ticker': 'NABIL', 'name': 'NABIL', 'company_name': 'Nabil Bank Limited', 'description': ''}]))
        self.assertEqual(Tag.objects.filter(slug='nabil').count(), 1)
        self.assertTrue(Tag.objects.get(slug='nabil').is_company)

    def test_rows_missing_ticker_or_name_are_skipped_not_crashed_on(self):
        path = self.write_csv([
            {'ticker': '', 'name': 'No ticker', 'company_name': '', 'description': ''},
            {'ticker': 'OK', 'name': '', 'company_name': '', 'description': ''},
        ])
        output = self.call(path)
        self.assertIn('skipped 2', output)
        self.assertEqual(Tag.objects.count(), 0)

    def test_dry_run_reports_without_writing_anything(self):
        path = self.write_csv([{'ticker': 'NABIL', 'name': 'NABIL', 'company_name': '', 'description': ''}])
        output = self.call(path, '--dry-run')
        self.assertIn('Would create 1', output)
        self.assertEqual(Tag.objects.count(), 0)

    def test_json_input_works_the_same_as_csv(self):
        path = self.write_json([{'ticker': 'NABIL', 'name': 'NABIL', 'company_name': 'Nabil Bank Limited'}])
        output = self.call(path)
        self.assertIn('create 1', output)
        self.assertTrue(Tag.objects.filter(ticker='NABIL', is_company=True).exists())

    def test_missing_file_raises_a_clean_command_error(self):
        with self.assertRaises(CommandError):
            self.call('/no/such/file.csv')
