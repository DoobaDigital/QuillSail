"""Let an article's body be Markdown, HTML or both, and keep old addresses for imported posts."""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("articles", sa.Column("body_format", sa.String(20), nullable=False, server_default="markdown"))
    op.add_column("article_revisions", sa.Column("body_format", sa.String(20), nullable=False, server_default="markdown"))
    op.create_table(
        "article_redirects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("old_path", sa.String(512), nullable=False),
        sa.Column("article_id", sa.Integer(), sa.ForeignKey("articles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("old_path", name="uq_article_redirects_old_path"),
    )
    op.create_index("ix_article_redirects_article_id", "article_redirects", ["article_id"])


def downgrade():
    op.drop_index("ix_article_redirects_article_id", table_name="article_redirects")
    op.drop_table("article_redirects")
    with op.batch_alter_table("article_revisions") as batch:
        batch.drop_column("body_format")
    with op.batch_alter_table("articles") as batch:
        batch.drop_column("body_format")
