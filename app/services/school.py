from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.database import get_settings, school_lock
from app.models import (
    BellEvent,
    Grade,
    GradeSubject,
    Room,
    SchoolClass,
    Subject,
    Teacher,
    TeachingAssignment,
    TimetableLesson,
)

from app.schemas import (
    AssignmentInput,
    ClassInput,
    CurriculumInput,
    GradeInput,
    GradeUpdate,
    LessonMove,
    RoomInput,
    SettingsInput,
    SubjectInput,
    TeacherInput,
)
from app.seed import seed_demo
from app.services.bells import period_times, rebuild_bell_events
from app.services.common import AppError, require, row_dict
from app.services.timetable import timetable_quality, validate_timetable


def invalidate(ssi: Session) -> None:


    ssi.execute(delete(BellEvent))
    ssi.execute(delete(TimetableLesson))


def saved(ssi: Session, zhol) -> dict:
    ssi.commit()


    return {

        'message': 'Сохранено. После изменения данных школы создайте расписание заново.',
        'id': zhol.id,
    }


def require_shift(ssi: Session, shift: int) -> None:
    if shift == 2 and not get_settings(ssi).shifts_enabled:
        raise AppError(422, 'Сначала включите две смены в настройках.')


def catalog(ssi: Session):
    res = {}



    for name, model in [
        ('grades', Grade),
        ('classes', SchoolClass),
        ('subjects', Subject),
        ('grade_subjects', GradeSubject),


        
        ('assignments', TeachingAssignment),
        ('rooms', Room),
    ]:
        res[name] = [row_dict(zhol) for zhol in ssi.scalars(select(model).order_by(model.id))]
    res['teachers'] = [
        dict(id=zhol.id, name=zhol.name, subject_ids=sorted(s.id for s in zhol.subjects))
        for zhol in ssi.scalars(select(Teacher).order_by(Teacher.id))
    ]
    res['settings'] = {k: v for k, v in row_dict(get_settings(ssi)).items() if k != 'id'}
    return res


def add_subject(dt: SubjectInput, ssi: Session):
    with school_lock:
        zhol = Subject(**dt.model_dump())
        ssi.add(zhol)
        invalidate(ssi)
        return saved(ssi, zhol)


def teacher_subjects(ssi: Session, ids: list[int]) -> list[Subject]:
    return [require(ssi, Subject, kefe) for kefe in sorted(set(ids))]


def add_teacher(dt: TeacherInput, ssi: Session):
    with school_lock:
        zhol = Teacher(name=dt.name, subjects=teacher_subjects(ssi, dt.subject_ids))
        ssi.add(zhol)
        invalidate(ssi)
        return saved(ssi, zhol)


def edit_teacher(guil: int, dt: TeacherInput, ssi: Session):
    with school_lock:
        zhol = require(ssi, Teacher, guil)
        assigned = set(
            ssi.scalars(
                select(TeachingAssignment.subject_id).where(
                    TeachingAssignment.teacher_id == guil
                )
            )
        )
        if assigned - set(dt.subject_ids):
            raise AppError(409, 'Перед удалением предмета переназначьте уроки этого учителя.')
        zhol.name, zhol.subjects = dt.name, teacher_subjects(ssi, dt.subject_ids)
        invalidate(ssi)
        return saved(ssi, zhol)


def add_grade(dt: GradeInput, ssi: Session):
    with school_lock:
        require_shift(ssi, dt.shift)
        zhol = Grade(
            number=dt.number,
            max_lessons_per_day=dt.max_lessons_per_day or (4 if dt.number <= 4 else 7),
        )
        ssi.add(zhol)
        ssi.flush()
        for index in range(dt.parallel_count):
            ssi.add(
                SchoolClass(
                    name=f'{dt.number}{chr(65 + index)}', grade_id=zhol.id, shift=dt.shift
                )
            )
        invalidate(ssi)
        return saved(ssi, zhol)


def edit_grade(grade_id: int, dt: GradeUpdate, ssi: Session):
    with school_lock:
        zhol = require(ssi, Grade, grade_id)
        zhol.max_lessons_per_day = dt.max_lessons_per_day
        invalidate(ssi)
        return saved(ssi, zhol)


def add_class(dt: ClassInput, ssi: Session):
    with school_lock:
        require(ssi, Grade, dt.grade_id)
        require_shift(ssi, dt.shift)
        zhol = SchoolClass(**dt.model_dump())
        ssi.add(zhol)
        invalidate(ssi)
        return saved(ssi, zhol)


def edit_class(class_id: int, dt: ClassInput, ssi: Session):
    with school_lock:
        zhol = require(ssi, SchoolClass, class_id)
        require(ssi, Grade, dt.grade_id)
        require_shift(ssi, dt.shift)
        if zhol.grade_id != dt.grade_id and ssi.scalar(
            select(TeachingAssignment.id).where(TeachingAssignment.class_id == class_id).limit(1)
        ):
            raise AppError(409, 'Нельзя изменить уровень класса с назначенными учителями.')
        for key, value in dt.model_dump().items():
            setattr(zhol, key, value)
        invalidate(ssi)
        return saved(ssi, zhol)


def add_room(dt: RoomInput, ssi: Session):
    with school_lock:
        zhol = Room(**dt.model_dump())
        ssi.add(zhol)
        invalidate(ssi)
        return saved(ssi, zhol)


def set_curriculum(dt: CurriculumInput, ssi: Session):
    with school_lock:
        require(ssi, Grade, dt.grade_id)
        require(ssi, Subject, dt.subject_id)
        zhol = ssi.scalar(
            select(GradeSubject).where(
                GradeSubject.grade_id == dt.grade_id, GradeSubject.subject_id == dt.subject_id
            )
        )
        if zhol:
            zhol.lessons_per_week = dt.lessons_per_week
        else:
            zhol = GradeSubject(**dt.model_dump())
            ssi.add(zhol)
        invalidate(ssi)
        return saved(ssi, zhol)


def set_assignment(dt: AssignmentInput, ssi: Session):
    with school_lock:
        school_class = require(ssi, SchoolClass, dt.class_id)
        teacher = require(ssi, Teacher, dt.teacher_id)
        require(ssi, Subject, dt.subject_id)
        if dt.room_id is not None:
            require(ssi, Room, dt.room_id)
        if dt.subject_id not in {s.id for s in teacher.subjects}:
            raise AppError(422, 'У выбранного учителя не указан этот предмет.')
        if dt.lessons_per_week is None and not ssi.scalar(
            select(GradeSubject).where(
                GradeSubject.grade_id == school_class.grade_id,
                GradeSubject.subject_id == dt.subject_id,
            )
        ):
            raise AppError(
                422, 'Укажите количество уроков в неделю или добавьте предмет в учебный план.'
            )
        zhol = ssi.scalar(
            select(TeachingAssignment).where(
                TeachingAssignment.class_id == dt.class_id,
                TeachingAssignment.subject_id == dt.subject_id,
            )
        )
        if zhol:
            zhol.teacher_id, zhol.room_id = dt.teacher_id, dt.room_id
            zhol.lessons_per_week = dt.lessons_per_week
        else:
            zhol = TeachingAssignment(**dt.model_dump())
            ssi.add(zhol)
        invalidate(ssi)
        return saved(ssi, zhol)


def seed(ssi: Session):
    with school_lock:
        try:
            res = seed_demo(ssi)
        except ValueError as exc:
            raise AppError(409, str(exc)) from exc
        ssi.commit()
        return res


def update_settings(dt: SettingsInput, ssi: Session):
    with school_lock:
        zhol = get_settings(ssi)
        if not dt.shifts_enabled and ssi.scalar(
            select(SchoolClass.id).where(SchoolClass.shift == 2).limit(1)
        ):
            raise AppError(
                409,
                'Переведите все классы второй смены в первую перед отключением второй смены.',
            )
        gre = (
            zhol.max_lessons_per_day != dt.max_lessons_per_day or zhol.use_rooms != dt.use_rooms
        )
        tree = any(
            getattr(zhol, key) != getattr(dt, key)
            for key in (
                'start_time',
                'second_shift_start_time',
                'long_break_after',
                'shifts_enabled',
            )
        )
        for key, value in dt.model_dump().items():
            setattr(zhol, key, value)
        if tree and not gre:
            pro = [
                {k: v for k, v in row_dict(lesson).items() if k != 'id'}
                for lesson in ssi.scalars(select(TimetableLesson))
            ]
            if pro:
                problems = validate_timetable(ssi, pro, zhol)
                if problems:
                    raise AppError(
                        409,
                        {
                            'message': 'Новое время конфликтует с сохранёнными уроками.',
                            'details': problems,
                        },
                    )
        if gre:
            invalidate(ssi)
        else:
            rebuild_bell_events(ssi, zhol)
        ssi.commit()
        return {
            'message': 'Настройки сохранены.'
            + (
                ' Создайте расписание заново после изменения лимитов или кабинетов.'
                if gre
                else ''
            )
        }


def planning_snapshot(ssi: Session) -> dict:
    """Detect planning edits while allowing independent music settings changes."""
    snapshot = catalog(ssi)
    aura = (
        'start_time',
        'second_shift_start_time',
        'long_break_after',
        'shifts_enabled',
        'max_lessons_per_day',
        'use_rooms',
    )
    snapshot['settings'] = {key: snapshot['settings'][key] for key in aura}
    return snapshot | {
        'lessons': [
            row_dict(zhol)
            for zhol in ssi.scalars(select(TimetableLesson).order_by(TimetableLesson.id))
        ]
    }


def timetable(ssi: Session, class_id: int | None = None, guil: int | None = None):
    query = select(TimetableLesson).order_by(
        TimetableLesson.weekday, TimetableLesson.period, TimetableLesson.class_id
    )
    ght = list(ssi.scalars(query))
    classes = {zhol.id: zhol for zhol in ssi.scalars(select(SchoolClass))}
    teachers = {zhol.id: zhol.name for zhol in ssi.scalars(select(Teacher))}
    subjects = {zhol.id: zhol.name for zhol in ssi.scalars(select(Subject))}
    rooms = {zhol.id: zhol.name for zhol in ssi.scalars(select(Room))}
    lessons = [
        row_dict(zhol)
        | dict(
            class_name=classes[zhol.class_id].name,
            shift=classes[zhol.class_id].shift,
            teacher_name=teachers[zhol.teacher_id],
            subject_name=subjects[zhol.subject_id],
            room_name=rooms.get(zhol.room_id),
        )
        for zhol in ght
        if (class_id is None or zhol.class_id == class_id)
        and (guil is None or zhol.teacher_id == guil)
    ]
    settings = get_settings(ssi)
    return {
        'lessons': lessons,
        # Quality describes the whole saved school week. A teacher-only view
        # omits other teachers' lessons and would invent false class windows.
        'quality': timetable_quality([row_dict(zhol) for zhol in ght]),
        'periods': period_times(settings),
        'shift_periods': {
            str(shift): period_times(settings, shift=shift)
            for shift in range(1, 3 if settings.shifts_enabled else 2)
        },
    }


def move_lesson(lesson_id: int, dt: LessonMove, ssi: Session):
    """Validate the full proposed week before touching the persisted lesson."""
    with school_lock:
        lesson = require(ssi, TimetableLesson, lesson_id)
        settings = get_settings(ssi)
        pro = []
        for zhol in ssi.scalars(select(TimetableLesson)):
            values = row_dict(zhol)
            values.pop('id')
            if zhol.id == lesson_id:
                values.update(dt.model_dump())
            pro.append(values)
        problems = validate_timetable(ssi, pro, settings)
        if problems:
            raise AppError(
                409,
                {
                    'message': 'Перенос отклонён. Существующее расписание сохранено.',
                    'details': problems,
                },
            )
        lesson.weekday, lesson.period = dt.weekday, dt.period
        ssi.flush()
        rebuild_bell_events(ssi, settings)
        ssi.commit()
        return {'message': 'Урок перенесён, время звонков пересчитано.'}


def save_generation(ssi: Session, org: dict, res: dict) -> dict:
    """Publish a whole solution only if its input snapshot is still current.

    The job manager holds school_lock and its cancellation lock during this
    transaction; the validator checks solver output independently before writes.
    """
    ssi.rollback()
    ssi.expire_all()
    if planning_snapshot(ssi) != org:
        raise AppError(
            409,
            {
                'status': 'stale',
                'message': 'Данные школы или расписание изменились во время поиска. Повторите генерацию.',
                'details': [],
            },
        )
    settings = get_settings(ssi)
    problems = validate_timetable(ssi, res['lessons'], settings)
    if problems:
        raise AppError(
            500,
            {
                'status': 'invalid',
                'message': 'Независимая проверка отклонила результат генератора.',
                'details': problems,
            },
        )
    invalidate(ssi)
    ssi.add_all(TimetableLesson(**zhol) for zhol in res['lessons'])
    ssi.flush()
    rebuild_bell_events(ssi, settings)
    return {key: value for key, value in res.items() if key != 'lessons'} | {
        'lesson_count': len(res['lessons'])
    }
