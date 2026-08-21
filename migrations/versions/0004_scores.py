"""Phase 5 schema: stored scores and worker run history.

Revision ID: 0004_scores
Revises: 0003_game_schema
Create Date: 2026-08-21

Three tables and two columns.

  round_scores    what each driver and team scored in each round, with the
                  breakdown and the ruleset version. User-independent.
  pick_scores     the projection of those onto players' five slots.
  worker_runs     background job history, and the home of the monthly API
                  call count the poller's ceiling checks.

  rounds.scored_at            when the scoring pass last wrote this round
  rounds.scoring_provisional  whether it did so from a partial session set

`scoring_provisional` is a cache of something derivable — a round is
provisional while any expected scoring session is missing its results. It is
stored because the alternative is joining sessions on every listing, and it is
rewritten by the same pass that writes `scored_at`, so the two cannot disagree.
A test asserts it equals a recomputation, the same guard `transfer_cost`
carries in `0003`.

NOTE: there are no `use_alter` foreign keys here, so autogenerate sees this
schema honestly. Verify per SPEC.md §11 — run `flask db upgrade`, then
`flask db migrate`, and confirm the second pass reports no changes.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004_scores"
down_revision = "0003_game_schema"
branch_labels = None
depends_on = None


def upgrade():
    # ----- rounds ------------------------------------------------------------
    op.add_column(
        "rounds",
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rounds",
        sa.Column(
            "scoring_provisional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    # ----- round_scores ------------------------------------------------------
    op.create_table(
        "round_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("points", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column(
            "breakdown",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ruleset_version", sa.String(length=32), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind = 'driver' AND driver_id IS NOT NULL AND team_id IS NULL)"
            " OR (kind = 'team' AND team_id IS NOT NULL AND driver_id IS NULL)",
            name="ck_round_score_kind",
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["round_id"], ["rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("round_id", "driver_id", name="uq_round_score_driver"),
        sa.UniqueConstraint("round_id", "team_id", name="uq_round_score_team"),
    )
    op.create_index("ix_round_scores_season_id", "round_scores", ["season_id"])
    op.create_index("ix_round_scores_round_id", "round_scores", ["round_id"])
    op.create_index(
        "ix_round_scores_season_driver", "round_scores", ["season_id", "driver_id"]
    )
    op.create_index(
        "ix_round_scores_season_team", "round_scores", ["season_id", "team_id"]
    )

    # ----- pick_scores -------------------------------------------------------
    op.create_table(
        "pick_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("round_score_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("driver_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("points", sa.Numeric(precision=7, scale=2), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(kind = 'driver' AND driver_id IS NOT NULL AND team_id IS NULL)"
            " OR (kind = 'team' AND team_id IS NOT NULL AND driver_id IS NULL)",
            name="ck_pick_score_kind",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meeting_id"], ["meetings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["round_id"], ["rounds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_id"], ["lineup_snapshots.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["round_score_id"], ["round_scores.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["driver_id"], ["drivers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "round_id", "driver_id", name="uq_pick_score_driver"
        ),
        sa.UniqueConstraint(
            "user_id", "round_id", "team_id", name="uq_pick_score_team"
        ),
    )
    op.create_index("ix_pick_scores_season_id", "pick_scores", ["season_id"])
    op.create_index("ix_pick_scores_round_id", "pick_scores", ["round_id"])
    op.create_index("ix_pick_scores_snapshot_id", "pick_scores", ["snapshot_id"])
    op.create_index("ix_pick_scores_round_score_id", "pick_scores", ["round_score_id"])
    op.create_index(
        "ix_pick_scores_user_season", "pick_scores", ["user_id", "season_id"]
    )
    op.create_index(
        "ix_pick_scores_meeting_user", "pick_scores", ["meeting_id", "user_id"]
    )

    # ----- worker_runs -------------------------------------------------------
    op.create_table(
        "worker_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=True),
        sa.Column("api_calls", sa.Integer(), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=True),
        sa.Column(
            "detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_worker_runs_job_started", "worker_runs", ["job", "started_at"])
    op.create_index("ix_worker_runs_started", "worker_runs", ["started_at"])


def downgrade():
    op.drop_index("ix_worker_runs_started", table_name="worker_runs")
    op.drop_index("ix_worker_runs_job_started", table_name="worker_runs")
    op.drop_table("worker_runs")

    op.drop_index("ix_pick_scores_meeting_user", table_name="pick_scores")
    op.drop_index("ix_pick_scores_user_season", table_name="pick_scores")
    op.drop_index("ix_pick_scores_round_score_id", table_name="pick_scores")
    op.drop_index("ix_pick_scores_snapshot_id", table_name="pick_scores")
    op.drop_index("ix_pick_scores_round_id", table_name="pick_scores")
    op.drop_index("ix_pick_scores_season_id", table_name="pick_scores")
    op.drop_table("pick_scores")

    op.drop_index("ix_round_scores_season_team", table_name="round_scores")
    op.drop_index("ix_round_scores_season_driver", table_name="round_scores")
    op.drop_index("ix_round_scores_round_id", table_name="round_scores")
    op.drop_index("ix_round_scores_season_id", table_name="round_scores")
    op.drop_table("round_scores")

    op.drop_column("rounds", "scoring_provisional")
    op.drop_column("rounds", "scored_at")
