from __future__ import annotations
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event, RLock
from time import time
from typing import Any, Callable
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_settings, school_lock
from app.models import GenerationJob
from app.services.common import AppError
from app.services.school import planning_snapshot, save_generation
from app.services.timetable import TimetableError, generate_timetable






logger = logging.getLogger(__name__)
ACTIVE = ('queued', 'running')
SessionFactory = Callable[[], Session]






def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _job_dict(row: GenerationJob) -> dict[str, Any]:
    progress = json.loads(row.progress_json) if row.progress_json else {}
    if row.status == 'running' and row.started_at is not None:
        progress['elapsed_seconds'] = round(max(0, time() - row.started_at), 3)
    return {
        'id': row.id,
        'status': row.status,
        'created_at': row.created_at,
        'started_at': row.started_at,
        'finished_at': row.finished_at,
        'seed': row.seed,
        'optimize': row.optimize,
        'result': json.loads(row.result_json) if row.result_json else None,
        'error': json.loads(row.error_json) if row.error_json else None,
        'progress': progress,
    }


class JobManager:
    """Persist job state and publish a solution atomically with terminal status."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self.session_factory = session_factory
        self._lock = RLock()
        self._executor: ThreadPoolExecutor | None = None
        self._active_id: str | None = None
        self._cancelled: dict[str, Event] = {}
        self._closing = False

    def start(self) -> None:
        with self._lock, school_lock:
            if self._executor is not None:
                return
            with self.session_factory() as session, session.begin():
                for row in session.scalars(
                    select(GenerationJob).where(GenerationJob.status.in_(ACTIVE))
                ):
                    row.status = 'failed'
                    row.finished_at = time()
                    row.error_json = _json(
                        {
                            'status': 'interrupted',
                            'message': 'Сервер перезапустился во время генерации. Повторите поиск.',
                            'details': [],
                        }
                    )
            self._closing = False
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='timetable')

    def shutdown(self) -> None:
        with self._lock:
            self._closing = True
            for cancelled in self._cancelled.values():
                cancelled.set()
            executor = self._executor
        if executor is not None:
            executor.shutdown(wait=True)
        with self._lock:
            self._executor = None

    def submit(self, *, seed: int | None = None, optimize: bool = False) -> dict[str, Any]:
        with self._lock, school_lock:
            if self._executor is None or self._closing:
                raise AppError(503, 'Сервис генерации останавливается. Повторите позже.')
            if self._active_id is not None:
                raise AppError(
                    409, {'message': 'Генерация уже выполняется.', 'job_id': self._active_id}
                )
            job_id = str(uuid4())
            with self.session_factory() as session, session.begin():
                row = GenerationJob(
                    id=job_id,
                    status='queued',
                    created_at=time(),
                    seed=seed,
                    optimize=optimize,
                    progress_json=_json(
                        {'phase': 'queued', 'elapsed_seconds': 0.0, 'solutions': 0}
                    ),
                )
                session.add(row)
                session.flush()
                accepted = _job_dict(row)
            self._active_id = job_id
            self._cancelled[job_id] = Event()
            self._executor.submit(self._run, job_id, seed, optimize, self._cancelled[job_id])
            return accepted

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock, self.session_factory() as session:
            row = session.get(GenerationJob, job_id)
            if row is None:
                raise AppError(404, 'Задача генерации не найдена.')
            return _job_dict(row)

    def current(self) -> dict[str, Any] | None:
        with self._lock, self.session_factory() as session:
            row = session.scalar(
                select(GenerationJob)
                .where(GenerationJob.status.in_(ACTIVE))
                .order_by(GenerationJob.created_at.desc())
                .limit(1)
            )
            return _job_dict(row) if row is not None else None

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock, school_lock, self.session_factory() as session, session.begin():
            row = session.get(GenerationJob, job_id)
            if row is None:
                raise AppError(404, 'Задача генерации не найдена.')
            if row.status in ACTIVE:
                cancelled = self._cancelled.get(job_id)
                if cancelled is not None:
                    cancelled.set()
                progress = json.loads(row.progress_json) if row.progress_json else {}
                progress['phase'] = 'cancelling'
                row.progress_json = _json(progress)
            return _job_dict(row)

    def _progress(self, job_id: str, progress: dict[str, Any]) -> None:
        with self._lock, school_lock, self.session_factory() as session, session.begin():
            row = session.get(GenerationJob, job_id)
            cancelled = self._cancelled.get(job_id)
            if (
                row is not None
                and row.status == 'running'
                and not (cancelled is not None and cancelled.is_set())
            ):
                row.progress_json = _json(progress)

    def _release_slot(self, job_id: str) -> None:
        self._cancelled.pop(job_id, None)
        if self._active_id == job_id:
            self._active_id = None

    def _finish_error(self, job_id: str, error: dict[str, Any], cancelled: Event) -> None:
        with self._lock, school_lock:
            with self.session_factory() as session, session.begin():
                row = session.get(GenerationJob, job_id)
                if row is not None and row.status in ACTIVE:
                    row.status = 'cancelled' if cancelled.is_set() else 'failed'
                    row.finished_at = time()
                    if row.status == 'failed':
                        row.error_json = _json(error)
            self._release_slot(job_id)

    def _run(self, job_id: str, seed: int | None, optimize: bool, cancelled: Event) -> None:
        try:
            with self._lock, school_lock, self.session_factory() as session, session.begin():
                row = session.get(GenerationJob, job_id)
                if row is None or row.status != 'queued':
                    return
                if cancelled.is_set():
                    row.status = 'cancelled'
                    row.finished_at = time()
                    self._release_slot(job_id)
                    return
                row.status = 'running'
                row.started_at = time()
            with self.session_factory() as session:
                with school_lock:
                    original = planning_snapshot(session)
                    settings = get_settings(session)
                result = generate_timetable(
                    session,
                    settings,
                    seed=seed,
                    optimize=optimize,
                    cancelled=cancelled,
                    progress=lambda value: self._progress(job_id, value),
                )
                with self._lock, school_lock:
                    if cancelled.is_set():
                        raise TimetableError('Генерация отменена.', status='cancelled')
                    published = save_generation(session, original, result)
                    row = session.get(GenerationJob, job_id)
                    if row is None or row.status != 'running':
                        session.rollback()
                        return
                    row.status = 'succeeded'
                    row.finished_at = time()
                    row.seed = result['seed']
                    row.result_json = _json(published)
                    row.progress_json = _json(
                        {
                            'phase': 'complete',
                            'elapsed_seconds': result.get('elapsed_seconds', 0),
                            'solutions': result.get('solutions', 1),
                        }
                    )
                    session.commit()
                    self._release_slot(job_id)
        except TimetableError as exc:
            self._finish_error(
                job_id,
                {'status': exc.status, 'message': exc.message, 'details': exc.details},
                cancelled,
            )
        except AppError as exc:
            error = (
                exc.detail
                if isinstance(exc.detail, dict)
                else {'message': exc.detail, 'details': []}
            )
            self._finish_error(job_id, error, cancelled)
        except Exception:
            logger.exception('Background timetable generation failed: %s', job_id)
            self._finish_error(
                job_id,
                {
                    'status': 'internal',
                    'message': 'Внутренняя ошибка генерации. Предыдущее расписание сохранено.',
                    'details': [],
                },
                cancelled,
            )
        finally:
            with self._lock:
                self._release_slot(job_id)
