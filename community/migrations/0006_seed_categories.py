from django.db import migrations

# The six sections named in the product blueprint (section 4).
CATEGORIES = [
    ('NEPSE', 'nepse', 'Nepal Stock Exchange: listed companies, IPOs, sector talk and market sentiment.'),
    ('Global Markets', 'global-markets', 'US, Indian and other international markets, earnings and macro.'),
    ('Startups & Founders', 'startups-founders', 'Building companies, fundraising and early-stage investing.'),
    ('Personal Finance', 'personal-finance', 'Saving, budgeting, retirement and everyday money decisions.'),
    ('Trading Strategy', 'trading-strategy', 'Technical analysis, risk management and trading approaches.'),
    ('Market News', 'market-news', 'News and announcements that move markets, with discussion.'),
]


def seed(apps, schema_editor):
    Category = apps.get_model('community', 'Category')
    for name, slug, description in CATEGORIES:
        Category.objects.get_or_create(slug=slug, defaults={'name': name, 'description': description})


class Migration(migrations.Migration):
    dependencies = [('community', '0005_phase3_moderation_ama_startups')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
