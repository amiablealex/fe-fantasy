"""Record whether a subject took part in the round it was scored for.

Revision ID: 0005_participated
Revises: 0004_scores
Create Date: 2026-08-21

A driver who raced and scored nothing and a driver who was not on the grid both
end up with a zero and an empty breakdown, and the profile table has to tell
them apart — SPEC.md §4.2 suppresses zeros precisely so that the cells which
fired stay legible, which only works if "did not take part" renders as a blank
rather than as a nought.

This should have been in `0004`. It is a second migration rather than a flag
tucked into `detail` because it is part of what a score row means, not
incidental evidence about it, and because the tables are empty in production —
Season 13 is the first sync — so the cost of splitting it out is nothing.

`server_default` is true so existing local rows keep the common case, but they
are wrong for any driver who missed a round. Rescore after upgrading:

    flask score-season 2026 --force
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_participated"
down_revision = "0004_scores"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "round_scores",
        sa.Column(
            "participated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )


def downgrade():
    op.drop_column("round_scores", "participated")
