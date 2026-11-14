import sqlalchemy as sa

from alembic import op

revision = "0002_accounts_jobs"
down_revision = "0001_legacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    classes = sa.Table("classes", sa.MetaData(), autoload_with=bind)
    removed = {"language", "student_count"} & set(classes.columns.keys())
    for constraint in list(classes.constraints):
        if isinstance(constraint, sa.CheckConstraint) and any(
            name in str(constraint.sqltext) for name in removed
        ):
            classes.constraints.remove(constraint)
    if removed:
        with op.batch_alter_table(
            "classes", copy_from=classes, recreate="always"
        ) as batch:
            for name in sorted(removed):
                batch.drop_column(name)

    op.create_table(
        "admin_users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(120), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.Integer, nullable=False),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("admin_users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.Integer, nullable=False),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("started_at", sa.Float, nullable=True),
        sa.Column("finished_at", sa.Float, nullable=True),
        sa.Column("seed", sa.Integer, nullable=True),
        sa.Column("optimize", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("result_json", sa.Text, nullable=True),
        sa.Column("error_json", sa.Text, nullable=True),
        sa.Column("progress_json", sa.Text, nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"
        ),
    )


def downgrade() -> None:

    raise RuntimeError(
        "This revision removes language data. Restore the pre-upgrade database backup."
    )
