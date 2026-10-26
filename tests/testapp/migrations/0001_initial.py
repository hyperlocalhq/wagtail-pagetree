# Hand-written to stay compatible with every Wagtail version in the tox
# matrix: depends on the latest wagtailcore migration Wagtail 6.3 ships and
# points at "wagtailcore.page" directly (settings.WAGTAIL_PAGE_MODEL only
# exists from Wagtail 7.1).

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("wagtailcore", "0094_alter_page_locale"),
    ]

    operations = [
        migrations.CreateModel(
            name="ArticlePage",
            fields=[
                (
                    "page_ptr",
                    models.OneToOneField(
                        auto_created=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        parent_link=True,
                        primary_key=True,
                        serialize=False,
                        to="wagtailcore.page",
                    ),
                ),
            ],
            options={"abstract": False},
            bases=("wagtailcore.page",),
        ),
    ]
