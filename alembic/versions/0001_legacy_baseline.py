import sqlalchemy as sa

from alembic import op

revision = "0001_legacy"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    def create(name, *columns):

        if name not in existing:
            op.create_table(name, *columns)

    create(
        "teachers",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
    )
    create(
        "subjects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("is_hard", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    create(
        "teacher_subjects",
        sa.Column(
            "teacher_id",
            sa.Integer,
            sa.ForeignKey("teachers.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "subject_id",
            sa.Integer,
            sa.ForeignKey("subjects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    create(
        "grades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("number", sa.Integer, nullable=False, unique=True),
        sa.Column(
            "max_lessons_per_day", sa.Integer, nullable=False, server_default="6"
        ),
        sa.CheckConstraint("number BETWEEN 1 AND 11"),
        sa.CheckConstraint("max_lessons_per_day BETWEEN 1 AND 12"),
    )
    create(
        "classes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("grade_id", sa.Integer, sa.ForeignKey("grades.id"), nullable=False),
        sa.Column("name", sa.String(40), nullable=False, unique=True),
        sa.Column("language", sa.String(2), nullable=False, server_default="kk"),
        sa.Column("shift", sa.Integer, nullable=False, server_default="1"),
        sa.CheckConstraint("language IN ('kk', 'ru')"),
        sa.CheckConstraint("shift IN (1, 2)"),
    )
    create(
        "grade_subjects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("grade_id", sa.Integer, sa.ForeignKey("grades.id"), nullable=False),
        sa.Column(
            "subject_id", sa.Integer, sa.ForeignKey("subjects.id"), nullable=False
        ),
        sa.Column("lessons_per_week", sa.Integer, nullable=False),
        sa.UniqueConstraint("grade_id", "subject_id"),
        sa.CheckConstraint("lessons_per_week BETWEEN 1 AND 60"),
    )
    create(
        "rooms",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
    )
    create(
        "teaching_assignments",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("class_id", sa.Integer, sa.ForeignKey("classes.id"), nullable=False),
        sa.Column(
            "subject_id", sa.Integer, sa.ForeignKey("subjects.id"), nullable=False
        ),
        sa.Column(
            "teacher_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False
        ),
        sa.Column("room_id", sa.Integer, sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("lessons_per_week", sa.Integer, nullable=True),
        sa.UniqueConstraint("class_id", "subject_id"),
        sa.CheckConstraint(
            "lessons_per_week IS NULL OR lessons_per_week BETWEEN 1 AND 60"
        ),
    )
    create(
        "timetable_lessons",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("class_id", sa.Integer, sa.ForeignKey("classes.id"), nullable=False),
        sa.Column(
            "subject_id", sa.Integer, sa.ForeignKey("subjects.id"), nullable=False
        ),
        sa.Column(
            "teacher_id", sa.Integer, sa.ForeignKey("teachers.id"), nullable=False
        ),
        sa.Column("room_id", sa.Integer, sa.ForeignKey("rooms.id"), nullable=True),
        sa.Column("weekday", sa.Integer, nullable=False),
        sa.Column("period", sa.Integer, nullable=False),
        sa.UniqueConstraint("class_id", "weekday", "period"),
        sa.CheckConstraint("weekday BETWEEN 0 AND 4"),
        sa.CheckConstraint("period BETWEEN 1 AND 12"),
    )
    create(
        "bell_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("weekday", sa.Integer, nullable=False),
        sa.Column("time", sa.String(8), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("period", sa.Integer, nullable=False),
        sa.UniqueConstraint("weekday", "time", "event_type"),
    )
    create(
        "music_tracks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("stored_name", sa.String(80), nullable=False, unique=True),
    )
    create(
        "playlist_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column(
            "track_id", sa.Integer, sa.ForeignKey("music_tracks.id"), nullable=False
        ),
        sa.Column("position", sa.Integer, nullable=False),
        sa.UniqueConstraint("event_type", "position"),
    )
    create(
        "playlist_cursors",
        sa.Column("event_type", sa.String(30), primary_key=True),
        sa.Column("next_index", sa.Integer, nullable=False, server_default="0"),
    )

    create(
        "bell_playbacks",
        sa.Column("key", sa.String(80), primary_key=True),
        sa.Column("status", sa.String(255), nullable=False, server_default="claimed"),
    )
    settings_columns = [
        sa.Column("start_time", sa.String(5), nullable=False, server_default="08:30"),
        sa.Column(
            "shifts_enabled", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "second_shift_start_time",
            sa.String(5),
            nullable=False,
            server_default="14:00",
        ),
        sa.Column("long_break_after", sa.Integer, nullable=False, server_default="2"),
        sa.Column(
            "max_lessons_per_day", sa.Integer, nullable=False, server_default="8"
        ),
        sa.Column(
            "timezone", sa.String(80), nullable=False, server_default="Asia/Almaty"
        ),
        sa.Column("playback_duration", sa.Integer, nullable=False, server_default="15"),
        sa.Column("fade_out_seconds", sa.Integer, nullable=False, server_default="2"),
        sa.Column("use_rooms", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "scheduler_enabled", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "audio_enabled", sa.Boolean, nullable=False, server_default=sa.false()
        ),
        sa.Column("solver_time_limit", sa.Integer, nullable=False, server_default="20"),
    ]
    create("settings", sa.Column("id", sa.Integer, primary_key=True), *settings_columns)
    additions = {
        "classes": [
            sa.Column("language", sa.String(2), nullable=False, server_default="kk"),
            sa.Column("shift", sa.Integer, nullable=False, server_default="1"),
        ],
        "teaching_assignments": [
            sa.Column("lessons_per_week", sa.Integer, nullable=True)
        ],
        "settings": settings_columns,
    }
    for table, columns in additions.items():
        present = {column["name"] for column in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in present:
                op.add_column(table, column)

    obsolete = {("teacher_id", "weekday", "period"), ("room_id", "weekday", "period")}
    constraints = sa.inspect(bind).get_unique_constraints("timetable_lessons")
    to_remove = [c for c in constraints if tuple(c["column_names"]) in obsolete]
    if to_remove:
        with op.batch_alter_table(
            "timetable_lessons",
            naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"},
        ) as batch:
            for constraint in to_remove:
                name = (
                    constraint["name"]
                    or f"uq_timetable_lessons_{constraint['column_names'][0]}"
                )
                batch.drop_constraint(name, type_="unique")


def downgrade() -> None:

    raise RuntimeError(
        "Legacy adoption is irreversible. Restore a database backup to return to 1.x."
    )
