from contextlib import contextmanager
from threading import Event
from time import monotonic, sleep
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from app.models import (
    Base,
    GenerationJob,
    Grade,
    GradeSubject,
    SchoolClass,
    Settings,
    Subject,
    Teacher,
    TeachingAssignment,
    TimetableLesson,
)
from app.schemas import SettingsInput
from app.services import jobs, school
from app.services.common import AppError, row_dict
from app.services.timetable import TimetableError





@pytest.fixture
def factory(tmp_path):
    engine = create_engine(
        f'sqlite:///{tmp_path / "jobs.db"}', connect_args={'check_same_thread': False}
    )

    @event.listens_for(engine, 'connect')
    def pragmas(connection, _record):
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA foreign_keys=ON')

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all(
            [
                Settings(id=1, max_lessons_per_day=3, solver_time_limit=2),
                Grade(id=1, number=1, max_lessons_per_day=3),
            ]
        )
        subject = Subject(id=1, name='Математика')
        session.add(Teacher(id=1, name='Учитель', subjects=[subject]))
        session.flush()
        session.add_all(
            [
                SchoolClass(id=1, grade_id=1, name='1А'),
                GradeSubject(grade_id=1, subject_id=1, lessons_per_week=2),
            ]
        )
        session.flush()
        session.add(TeachingAssignment(class_id=1, subject_id=1, teacher_id=1))
        session.add_all(
            TimetableLesson(class_id=1, subject_id=1, teacher_id=1, weekday=day, period=1)
            for day in (0, 1)
        )
    yield sessions
    engine.dispose()


@contextmanager
def manager(factory):
    service = jobs.JobManager(factory)
    service.start()
    try:
        yield service
    finally:
        service.shutdown()


def wait_finished(service, job_id):
    deadline = monotonic() + 8
    while monotonic() < deadline:
        result = service.get(job_id)
        if result['status'] not in {'queued', 'running'}:
            return result
        sleep(0.01)
    pytest.fail('Background job did not finish')


def lessons(factory):
    with factory() as session:
        return [
            (row.id, row.class_id, row.weekday, row.period)
            for row in session.scalars(select(TimetableLesson).order_by(TimetableLesson.id))
        ]
def blocking_solver(monkeypatch):
    entered, release = Event(), Event()
    actual = jobs.generate_timetable
    def controlled(*args, **kwargs):
        entered.set()
        if not release.wait(5):
            raise RuntimeError('test gate was not released')
        return actual(*args, **kwargs)




    monkeypatch.setattr(jobs, 'generate_timetable', controlled)
    return entered, release


def test_accepts_job_without_waiting_and_bounds_queue(factory, monkeypatch):
    entered, release = blocking_solver(monkeypatch)
    before = lessons(factory)
    with manager(factory) as service:
        try:
            accepted = service.submit(seed=123)
            assert accepted['status'] == 'queued'
            assert entered.wait(2)
            assert service.current()['id'] == accepted['id']
            assert service.get(accepted['id'])['status'] == 'running'
            assert lessons(factory) == before
            with pytest.raises(AppError) as exc:
                service.submit()
            assert exc.value.status_code == 409
        finally:
            release.set()
        result = wait_finished(service, accepted['id'])
        assert result['status'] == 'succeeded'
        assert result['result']['lesson_count'] == 2
        assert result['result']['seed'] == 123
        assert result['result']['status'] in {'feasible', 'optimal'}
        assert result['progress']['solutions'] >= 1
        assert service.current() is None
    with manager(factory) as restarted:
        assert restarted.get(accepted['id'])['result'] == result['result']






def test_cancelled_job_cannot_publish_a_solution(factory, monkeypatch):
    entered, release = blocking_solver(monkeypatch)
    before = lessons(factory)
    with manager(factory) as service:
        try:
            accepted = service.submit()
            assert entered.wait(2)

            cancelling = service.cancel(accepted['id'])
            assert cancelling['status'] == 'running'
            assert cancelling['progress']['phase'] == 'cancelling'


            assert cancelling['finished_at'] is None
            assert service.current()['id'] == accepted['id']
            assert service.cancel(accepted['id'])['progress']['phase'] == 'cancelling'


            with pytest.raises(AppError) as exc:
                service.submit()
            assert exc.value.status_code == 409
        finally:
            release.set()
        result = wait_finished(service, accepted['id'])


        assert result['status'] == 'cancelled'
        assert result['finished_at'] is not None



        assert lessons(factory) == before
        next_job = service.submit(seed=42)
        assert wait_finished(service, next_job['id'])['status'] == 'succeeded'
    assert service.get(accepted['id'])['status'] == 'cancelled'


def test_late_solver_update_does_not_hide_pending_cancellation(factory, monkeypatch):



    entered, send_update, updated, release = Event(), Event(), Event(), Event()

    def delayed_callback(*_args, progress, **_kwargs):
        entered.set()
        if not send_update.wait(3):
            raise RuntimeError('test callback was not released')
        progress({'phase': 'solving', 'elapsed_seconds': 1.0, 'solutions': 1})
        updated.set()
        if not release.wait(3):
            raise RuntimeError('test solver was not released')

        
        raise TimetableError('Генерация отменена.', status='cancelled')

    monkeypatch.setattr(jobs, 'generate_timetable', delayed_callback)
    with manager(factory) as service:
        try:
            accepted = service.submit()
            assert entered.wait(2)
            service.cancel(accepted['id'])


            send_update.set()
            assert updated.wait(2)
            assert service.get(accepted['id'])['progress']['phase'] == 'cancelling'
        finally:
            send_update.set()
            release.set()
        assert wait_finished(service, accepted['id'])['status'] == 'cancelled'


def test_changed_school_is_detected_before_atomic_publish(factory, monkeypatch):
    entered, release = blocking_solver(monkeypatch)
    before = lessons(factory)
    with manager(factory) as service:


        try:
            accepted = service.submit()
            assert entered.wait(2)
            with factory.begin() as session:


                session.get(Subject, 1).name = 'Другое название'
        finally:
            release.set()
        result = wait_finished(service, accepted['id'])
        assert result['status'] == 'failed'
        assert result['error']['status'] == 'stale'


    assert lessons(factory) == before


def test_music_settings_can_change_during_generation_without_discarding_result(
    factory, monkeypatch
):
    entered, release = blocking_solver(monkeypatch)
    with manager(factory) as service:
        try:
            accepted = service.submit(seed=42)
            assert entered.wait(2)
            with factory() as session:


                settings = row_dict(session.get(Settings, 1))
                settings.pop('id')
                settings.update(audio_enabled=True, playback_duration=25, fade_out_seconds=3)


                school.update_settings(SettingsInput(**settings), session)
        finally:
            release.set()
        result = wait_finished(service, accepted['id'])


        assert result['status'] == 'succeeded'
        assert result['result']['lesson_count'] == 2
    with factory() as session:
        settings = session.get(Settings, 1)


        assert settings.audio_enabled is True
        assert settings.playback_duration == 25


        assert settings.fade_out_seconds == 3


def test_lesson_time_change_during_generation_rejects_stale_result(factory, monkeypatch):


    entered, release = blocking_solver(monkeypatch)
    before = lessons(factory)
    with manager(factory) as service:
        try:




            accepted = service.submit(seed=42)
            assert entered.wait(2)
            with factory() as session:
                settings = row_dict(session.get(Settings, 1))
                settings.pop('id')
                settings['start_time'] = '09:00'
                school.update_settings(SettingsInput(**settings), session)



        finally:
            release.set()
        result = wait_finished(service, accepted['id'])


        assert result['status'] == 'failed'
        assert result['error']['status'] == 'stale'
    assert lessons(factory) == before
    with factory() as session:
        assert session.get(Settings, 1).start_time == '09:00'





def test_solver_failure_preserves_saved_timetable(factory, monkeypatch):
    def failed(*_args, **_kwargs):
        raise TimetableError('Нет решения', ['Проверьте лимиты'], status='infeasible')

    monkeypatch.setattr(jobs, 'generate_timetable', failed)



    before = lessons(factory)
    with manager(factory) as service:
        result = wait_finished(service, service.submit()['id'])


        assert result['status'] == 'failed'
        assert result['error']['status'] == 'infeasible'
    assert lessons(factory) == before


def test_bad_solver_output_is_validated_before_any_delete(factory, monkeypatch):
    monkeypatch.setattr(
        jobs,
        'generate_timetable',
        lambda *_args, **_kwargs: {'lessons': [], 'status': 'feasible', 'seed': 1},
    )
    before = lessons(factory)
    with manager(factory) as service:
        result = wait_finished(service, service.submit()['id'])
        assert result['status'] == 'failed'
        assert result['error']['status'] == 'invalid'
    assert lessons(factory) == before


def test_restart_marks_interrupted_jobs_without_touching_schedule(factory):
    before = lessons(factory)
    with factory.begin() as session:
        session.add_all(
            GenerationJob(id=status, status=status, created_at=1.0, optimize=False)
            for status in ('queued', 'running')
        )
    with manager(factory) as service:
        for job_id in ('queued', 'running'):
            result = service.get(job_id)
            assert result['status'] == 'failed'
            assert result['error']['status'] == 'interrupted'
        assert service.current() is None
    assert lessons(factory) == before


def test_finished_job_cancellation_is_idempotent(factory):
    with manager(factory) as service:
        result = wait_finished(service, service.submit()['id'])
        assert result['status'] == 'succeeded'
        assert service.cancel(result['id'])['status'] == 'succeeded'


        
        with pytest.raises(AppError) as exc:
            service.get('missing')
        assert exc.value.status_code == 404
