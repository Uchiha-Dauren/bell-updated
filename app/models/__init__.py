from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


teacher_subjects = Table(
    'teacher_subjects',
    Base.metadata,

    Column('teacher_id', ForeignKey('teachers.id', ondelete='CASCADE'), primary_key=True),


    Column('subject_id', ForeignKey('subjects.id', ondelete='CASCADE'), primary_key=True),
)


class Teacher(Base):
    __tablename__ = 'teachers'
    id: Mapped[int] = mapped_column(primary_key=True)


    name: Mapped[str] = mapped_column(String(120))
    subjects: Mapped[list['Subject']] = relationship(secondary=teacher_subjects, lazy='selectin')


class Grade(Base):
    __tablename__ = 'grades'
    __table_args__ = (
        CheckConstraint('number BETWEEN 1 AND 11'),


        CheckConstraint('max_lessons_per_day BETWEEN 1 AND 12'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(unique=True)


    max_lessons_per_day: Mapped[int] = mapped_column(default=6)


class SchoolClass(Base):
    __tablename__ = 'classes'

    __table_args__ = (CheckConstraint('shift IN (1, 2)'),)
    id: Mapped[int] = mapped_column(primary_key=True)


    grade_id: Mapped[int] = mapped_column(ForeignKey('grades.id'))
    name: Mapped[str] = mapped_column(String(40), unique=True)
    shift: Mapped[int] = mapped_column(default=1)




class Subject(Base):
    __tablename__ = 'subjects'
    id: Mapped[int] = mapped_column(primary_key=True)

    name: Mapped[str] = mapped_column(String(120), unique=True)


    is_hard: Mapped[bool] = mapped_column(Boolean, default=False)


class GradeSubject(Base):
    __tablename__ = 'grade_subjects'
    __table_args__ = (
        UniqueConstraint('grade_id', 'subject_id'),


        CheckConstraint('lessons_per_week BETWEEN 1 AND 60'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    grade_id: Mapped[int] = mapped_column(ForeignKey('grades.id'))
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))


    lessons_per_week: Mapped[int]


class Room(Base):
    __tablename__ = 'rooms'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


class TeachingAssignment(Base):
    __tablename__ = 'teaching_assignments'
    __table_args__ = (
        UniqueConstraint('class_id', 'subject_id'),
        CheckConstraint('lessons_per_week IS NULL OR lessons_per_week BETWEEN 1 AND 60'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'))
    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))

    
    teacher_id: Mapped[int] = mapped_column(ForeignKey('teachers.id'))
    room_id: Mapped[int | None] = mapped_column(ForeignKey('rooms.id'), nullable=True)
    lessons_per_week: Mapped[int | None] = mapped_column(nullable=True)




class TimetableLesson(Base):
    __tablename__ = 'timetable_lessons'
    __table_args__ = (
        UniqueConstraint('class_id', 'weekday', 'period'),
        CheckConstraint('weekday BETWEEN 0 AND 4'),
        CheckConstraint('period BETWEEN 1 AND 12'),

    )
    id: Mapped[int] = mapped_column(primary_key=True)

    class_id: Mapped[int] = mapped_column(ForeignKey('classes.id'))


    subject_id: Mapped[int] = mapped_column(ForeignKey('subjects.id'))
    teacher_id: Mapped[int] = mapped_column(ForeignKey('teachers.id'))


    room_id: Mapped[int | None] = mapped_column(ForeignKey('rooms.id'), nullable=True)
    weekday: Mapped[int]


    period: Mapped[int]


class BellEvent(Base):


    __tablename__ = 'bell_events'
    __table_args__ = (UniqueConstraint('weekday', 'time', 'event_type'),)



    id: Mapped[int] = mapped_column(primary_key=True)
    weekday: Mapped[int]
    time: Mapped[str] = mapped_column(String(8))
    event_type: Mapped[str] = mapped_column(String(30))
    period: Mapped[int]


class MusicTrack(Base):
    __tablename__ = 'music_tracks'


    id: Mapped[int] = mapped_column(primary_key=True)
    original_name: Mapped[str] = mapped_column(String(255))



    stored_name: Mapped[str] = mapped_column(String(80), unique=True)


class PlaylistEntry(Base):
    __tablename__ = 'playlist_entries'
    __table_args__ = (UniqueConstraint('event_type', 'position'),)


    id: Mapped[int] = mapped_column(primary_key=True)


    event_type: Mapped[str] = mapped_column(String(30))


    track_id: Mapped[int] = mapped_column(ForeignKey('music_tracks.id'))
    position: Mapped[int]


class PlaylistCursor(Base):
    __tablename__ = 'playlist_cursors'


    event_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    next_index: Mapped[int] = mapped_column(default=0)





class BellPlayback(Base):
    __tablename__ = 'bell_playbacks'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)


    status: Mapped[str] = mapped_column(String(255), default='claimed')


class Settings(Base):
    __tablename__ = 'settings'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)



    start_time: Mapped[str] = mapped_column(String(5), default='08:30')


    shifts_enabled: Mapped[bool] = mapped_column(default=False)

    second_shift_start_time: Mapped[str] = mapped_column(String(5), default='14:00')


    long_break_after: Mapped[int] = mapped_column(default=2)



    max_lessons_per_day: Mapped[int] = mapped_column(default=8)

    timezone: Mapped[str] = mapped_column(String(80), default='Asia/Almaty')

    playback_duration: Mapped[int] = mapped_column(default=15)

    fade_out_seconds: Mapped[int] = mapped_column(default=2)

    use_rooms: Mapped[bool] = mapped_column(default=False)

    scheduler_enabled: Mapped[bool] = mapped_column(default=False)

    audio_enabled: Mapped[bool] = mapped_column(default=False)

    solver_time_limit: Mapped[int] = mapped_column(default=20)


class AdminUser(Base):
    __tablename__ = 'admin_users'
    id: Mapped[int] = mapped_column(primary_key=True)


    username: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))

    
    created_at: Mapped[int]


class AuthSession(Base):
    __tablename__ = 'auth_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey('admin_users.id', ondelete='CASCADE'), index=True
    )
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[int] = mapped_column(index=True)


class GenerationJob(Base):
    __tablename__ = 'generation_jobs'
    __table_args__ = (
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default='queued')
    created_at: Mapped[float]
    started_at: Mapped[float | None] = mapped_column(nullable=True)
    finished_at: Mapped[float | None] = mapped_column(nullable=True)
    seed: Mapped[int | None] = mapped_column(nullable=True)
    optimize: Mapped[bool] = mapped_column(default=False)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
