"""Global league and hidden memberships.

SPEC.md §2 states lineup visibility as one sentence — hidden until the
meeting's deadline passes, then visible to co-members — but that is two
independent predicates. The temporal half is load-bearing: it is what makes
"no pre-deadline who-picked-what view exists at all" true, and it is the only
reason copying is not a strategy. The co-membership half does no game-design
work once a deadline has passed; it is a privacy scope.

So the scope is relaxed by *data* rather than by deleting a predicate. A single
league carrying `is_global` holds every user, the co-membership clause stays
exactly as written, and it is simply true for everyone. §10 already left
"public/global table" open, so this settles it rather than diverging from it.

`league_memberships.hidden` is the opt-out. Not a deleted membership: leaving
would take the member's read access with them, and the account toggle this
backs reads as "stop showing me", not "stop showing me the table".

The invite code for the global league is the sentinel `GLOBAL`. It contains O
and L, both absent from `INVITE_CODE_ALPHABET`, so a generated code can never
collide with it.

Revision ID: 0006_global_league
Revises: 0005_participated
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_global_league"
down_revision = "0005_participated"
branch_labels = None
depends_on = None


GLOBAL_LEAGUE_NAME = "FE Fantasy"
GLOBAL_INVITE_CODE = "GLOBAL"


def upgrade():
    # ---- columns ------------------------------------------------------------
    # Added with a server default so the backfill needs no UPDATE, then the
    # default is dropped: leaving it in place is a difference between the
    # models and the database that a later autogenerate can notice.
    op.add_column(
        "leagues",
        sa.Column(
            "is_global", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column("leagues", "is_global", server_default=None)

    op.add_column(
        "league_memberships",
        sa.Column(
            "hidden", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.alter_column("league_memberships", "hidden", server_default=None)

    # At most one global league. A partial unique index rather than a check
    # constraint, because the constraint is across rows.
    op.create_index(
        "uq_league_global",
        "leagues",
        ["is_global"],
        unique=True,
        postgresql_where=sa.text("is_global"),
    )

    # ---- the league itself --------------------------------------------------
    # Raw SQL rather than an import from app.leagues: a migration that imports
    # application code stops being a description of the schema at this revision
    # and starts being a description of whatever the models say today.
    #
    # ON CONFLICT DO NOTHING makes both statements safe to re-run, which
    # matters because the test suite builds its schema with create_all() and
    # never executes this file — `ensure_global_league()` in the service is the
    # same operation for that path, and the two must be able to overlap without
    # a duplicate.
    op.execute(
        sa.text(
            """
            INSERT INTO leagues (name, invite_code, created_by_id, created_at, is_global)
            VALUES (:name, :code, NULL, now(), true)
            ON CONFLICT (invite_code) DO NOTHING
            """
        ).bindparams(name=GLOBAL_LEAGUE_NAME, code=GLOBAL_INVITE_CODE)
    )

    op.execute(
        """
        INSERT INTO league_memberships (league_id, user_id, role, joined_at, hidden)
        SELECT l.id, u.id, 'member', now(), false
        FROM leagues l CROSS JOIN users u
        WHERE l.is_global
        ON CONFLICT ON CONSTRAINT uq_league_membership DO NOTHING
        """
    )


def downgrade():
    op.execute(
        """
        DELETE FROM league_memberships
        WHERE league_id IN (SELECT id FROM leagues WHERE is_global)
        """
    )
    op.execute("DELETE FROM leagues WHERE is_global")
    op.drop_index("uq_league_global", table_name="leagues")
    op.drop_column("league_memberships", "hidden")
    op.drop_column("leagues", "is_global")
