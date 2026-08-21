"""game schema: lineup snapshots and picks

Revision ID: 0004_game_schema
Revises: REPLACE_WITH_CURRENT_HEAD
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_game_schema"
down_revision = "0002_ingestion_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lineup_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("transfer_cost", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "meeting_id", name="uq_lineup_snapshot_user_meeting"
        ),
    )
    op.create_index(
        "ix_lineup_snapshots_season_id", "lineup_snapshots", ["season_id"]
    )
    op.create_index(
        "ix_lineup_snapshots_user_season", "lineup_snapshots", ["user_id", "season_id"]
    )
    op.create_index(
        "ix_lineup_snapshots_meeting_user",
        "lineup_snapshots",
        ["meeting_id", "user_id"],
    )

    op.create_table(
        "lineup_picks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["lineup_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_id", "driver_id", name="uq_lineup_pick_driver"),
        sa.CheckConstraint(
            "(kind = 'driver' AND driver_id IS NOT NULL AND team_id IS NULL)"
            " OR (kind = 'team' AND team_id IS NOT NULL AND driver_id IS NULL)",
            name="ck_lineup_pick_kind",
        ),
    )
    op.create_index("ix_lineup_picks_snapshot_id", "lineup_picks", ["snapshot_id"])
    op.create_index("ix_lineup_picks_driver_id", "lineup_picks", ["driver_id"])
    op.create_index("ix_lineup_picks_team_id", "lineup_picks", ["team_id"])
    # One team pick per snapshot.
    op.create_index(
        "uq_lineup_pick_team",
        "lineup_picks",
        ["snapshot_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'team'"),
    )

    op.alter_column("lineup_snapshots", "transfer_cost", server_default=None)


def downgrade():
    op.drop_table("lineup_picks")
    op.drop_table("lineup_snapshots")
