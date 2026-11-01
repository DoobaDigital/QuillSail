"""Make QuillSail's own style the default look, and keep designs people already changed.

Installations still on the untouched defaults move to the new defaults on the
website, dashboard and newsletter emails. Installations that changed their look
keep it: the previous defaults are stored for them, and their dashboard keeps
matching the publication. Logos, homepage copy and other branding never count
as a changed look and are left alone.
"""
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

# Look settings whose defaults change in this release, with their previous defaults.
PREVIOUS = {
    'appearance.style': 'classic', 'appearance.accent_color': '#1F5BD8', 'appearance.article_font': 'serif',
    'appearance.heading_font': 'inherit', 'appearance.text_color': '#16181d', 'appearance.muted_color': '#525866',
    'appearance.border_color': '#e1e4e9', 'appearance.dark_background': '', 'appearance.dark_surface': '',
    'appearance.dark_text': '', 'appearance.corner_radius': 10, 'appearance.color_mode': 'auto',
}
# Other look settings. Changing any of these also counts as a changed look.
UNCHANGED = {
    'appearance.theme': 'default', 'appearance.custom_css': '', 'appearance.email_css': '',
    'appearance.custom_body_font': '', 'appearance.custom_heading_font': '',
    'appearance.background': '#ffffff', 'appearance.surface': '#ffffff', 'appearance.content_width': 1152,
    'appearance.reading_width': 640, 'appearance.body_size': 18, 'appearance.line_height': 170,
    'appearance.email_width': 600, 'appearance.email_size': 16, 'appearance.email_padding': 32,
    'appearance.masthead': 'left', 'appearance.density': 'comfortable', 'appearance.issue_layout': 'stacked',
    'appearance.email_layout': 'classic',
}


def _unchanged(value, default) -> bool:
    return value is None or str(value).strip().lower() == str(default).lower()


def upgrade():
    settings = sa.table('settings', sa.column('key', sa.String()), sa.column('value', sa.JSON()),
                        sa.column('updated_at', sa.DateTime()))
    connection = op.get_bind()
    defaults = PREVIOUS | UNCHANGED
    stored = dict(connection.execute(
        sa.select(settings.c.key, settings.c.value).where(settings.c.key.in_(list(defaults)))).all())
    if all(_unchanged(stored.get(key), default) for key, default in defaults.items()):
        # Untouched: the new defaults apply.
        connection.execute(settings.delete().where(settings.c.key.in_(list(PREVIOUS))))
        return
    now = datetime.now(UTC).replace(tzinfo=None)
    keep = {key: default for key, default in PREVIOUS.items() if stored.get(key) is None}
    # Sites that never saved a design in the designer keep the built-in styles.
    keep['appearance.core_styles'] = stored.get('appearance.style') is None
    keep['appearance.dashboard_theme'] = 'publication'
    keep['onboarding.appearance'] = 'done'
    for key, value in keep.items():
        if key in stored:
            connection.execute(settings.update().where(settings.c.key == key).values(value=value, updated_at=now))
        else:
            connection.execute(settings.insert().values(key=key, value=value, updated_at=now))


def downgrade():
    pass
