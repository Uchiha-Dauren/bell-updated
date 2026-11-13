from __future__ import annotations
import random
import secrets
from collections import Counter, defaultdict
from dataclasses import dataclass
from threading import Event, Thread
from time import monotonic
from typing import Any, Callable
from ortools.sat.python import cp_model
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import (
    Grade,
    GradeSubject,
    Room,
    SchoolClass,
    Settings,
    Subject,
    Teacher,
    TeachingAssignment,
)
from app.services.bells import period_times

DAYS = range(5)
Lesson = dict[str, Any]


class TimetableError(ValueError):
    """A helpful configuration, infeasibility, or search-timeout diagnostic."""

    def __init__(
        self, message: str, details: list[str] | None = None, status: str = 'invalid'
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.status = status


@dataclass(frozen=True)
class Requirement:
    class_id: int
    subject_id: int
    teacher_id: int
    room_id: int | None
    count: int
    cap: int
    label: str
    is_hard: bool
    shift: int




@dataclass
class Problem:
    classes: dict[int, SchoolClass]
    teachers: dict[int, Teacher]


    rooms: dict[int, Room]


    requirements: list[Requirement]
    caps: dict[int, int]


    times: dict[tuple[int, int], tuple[int, int]]


def _minutes(value: str) -> int:

    hour, minute = map(int, value.split(':'))
    return hour * 60 + minute



def _load_problem(session: Session, settings: Settings) -> Problem:
    classes = {x.id: x for x in session.scalars(select(SchoolClass))}
    grades = {x.id: x for x in session.scalars(select(Grade))}
    subjects = {x.id: x for x in session.scalars(select(Subject))}
    teachers = {x.id: x for x in session.scalars(select(Teacher))}
    rooms = {x.id: x for x in session.scalars(select(Room))}




    assignments = {
        (x.class_id, x.subject_id): x for x in session.scalars(select(TeachingAssignment))
    }


    curriculum: dict[int, list[GradeSubject]] = defaultdict(list)




    for item in session.scalars(select(GradeSubject)):


        curriculum[item.grade_id].append(item)
    errors: list[str] = []
    if not classes:



        errors.append('Добавьте хотя бы один класс перед генерацией.')
    if (
        not isinstance(settings.max_lessons_per_day, int)
        or not 1 <= settings.max_lessons_per_day <= 12
    ):


        
        errors.append('Количество уроков в день должно быть от 1 до 12.')
    if errors:



        raise TimetableError('Не заполнены данные школы.', errors)
    requirements: list[Requirement] = []
    caps: dict[int, int] = {}
    times: dict[tuple[int, int], tuple[int, int]] = {}
    for shift in {c.shift for c in classes.values()}:




        if shift not in (1, 2) or (shift == 2 and not settings.shifts_enabled):
            errors.append('Для классов второй смены включите две смены в настройках.')
            continue




        try:
            for slot in period_times(settings, shift=shift):
                times[shift, slot['period']] = (_minutes(slot['start']), _minutes(slot['end']))
        except ValueError as exc:





            errors.append(str(exc))
    for grade in grades.values():




        if not any(c.grade_id == grade.id for c in classes.values()):
            errors.append(f'Уровень {grade.number}: не добавлены классы.')
    for school_class in classes.values():





        grade = grades.get(school_class.grade_id)
        if grade is None:



            errors.append(f'{school_class.name}: уровень класса не существует.')
            continue
        cap = min(settings.max_lessons_per_day, grade.max_lessons_per_day)
        caps[school_class.id] = cap
        if not 1 <= cap <= 12:




            errors.append(f'{school_class.name}: дневной лимит должен быть от 1 до 12.')
        quotas = {item.subject_id: item.lessons_per_week for item in curriculum[grade.id]}
        for (assigned_class, subject_id), assignment in assignments.items():
            if assigned_class == school_class.id and assignment.lessons_per_week is not None:
                quotas[subject_id] = assignment.lessons_per_week
        if not quotas:
            errors.append(
                f'{school_class.name}: добавьте учебный план для уровня {grade.number} или укажите часы в назначениях.'
            )
        for subject_id, lessons_per_week in quotas.items():
            subject = subjects.get(subject_id)
            if subject is None:
                errors.append(f'{school_class.name}: предмет {subject_id} не существует.')
                continue
            label = f'{school_class.name} / {subject.name} ({lessons_per_week} уроков в неделю)'
            if lessons_per_week < 1:
                errors.append(f'{label}: недельное количество уроков должно быть положительным.')
                continue
            assignment = assignments.get((school_class.id, subject_id))
            if assignment is None:
                errors.append(f'{label}: не назначен учитель.')
                continue
            teacher = teachers.get(assignment.teacher_id)
            if teacher is None:



                errors.append(f'{label}: назначенный учитель не существует.')
                continue
            if subject_id not in {x.id for x in teacher.subjects}:
                errors.append(f'{label}: у учителя {teacher.name} не указан этот предмет.')
                continue
            room_id = assignment.room_id if settings.use_rooms else None
            if settings.use_rooms and room_id not in rooms:
                errors.append(f'{label}: назначьте кабинет или отключите проверку кабинетов.')
                continue
            requirements.append(



                Requirement(
                    school_class.id,
                    subject.id,
                    teacher.id,
                    room_id,
                    lessons_per_week,
                    cap,
                    label,
                    subject.is_hard,
                    school_class.shift,
                )
            )
    if errors:
        raise TimetableError(
            'Данные школы заполнены не полностью или противоречат друг другу.', errors
        )
    overloads: list[str] = []
    for class_id, school_class in classes.items():
        required = sum(r.count for r in requirements if r.class_id == class_id)
        capacity = 5 * caps[class_id]
        if required > capacity:
            overloads.append(
                f'{school_class.name}: нужно {required} уроков в неделю, доступно только {capacity} '
                f'(5 дней × {caps[class_id]} уроков). Уменьшите план или увеличьте дневной лимит.'
            )


            
    for kind, resources, field in [
        ('Учитель', teachers, 'teacher_id'),
        ('Кабинет', rooms, 'room_id'),
    ]:
        if kind == 'Кабинет' and not settings.use_rooms:



            continue
        for resource_id, resource in resources.items():
            jobs = [r for r in requirements if getattr(r, field) == resource_id]
            for shift in {r.shift for r in jobs}:



                shift_jobs = [r for r in jobs if r.shift == shift]
                for cap in sorted({r.cap for r in shift_jobs}):


                    needed = sum(r.count for r in shift_jobs if r.cap <= cap)
                    if needed > 5 * cap:


                        overloads.append(
                            f'{kind} {resource.name}: нужно {needed} уроков в смене {shift}, уроки 1–{cap}, '
                            f'но доступно только {5 * cap} мест в неделю. '
                            f'Переназначьте учителя/кабинет или увеличьте дневные лимиты.'
                        )
    if overloads:



        raise TimetableError(
            'С указанными ограничениями расписание невозможно.', overloads, status='infeasible'
        )
    return Problem(classes, teachers, rooms, requirements, caps, times)


def _gap_costs(model: cp_model.CpModel, occupied: list[Any], name: str) -> list[Any]:

    penalties = []
    for p in range(1, len(occupied) - 1):
        before = model.new_bool_var(f'{name}_before_{p}')
        after = model.new_bool_var(f'{name}_after_{p}')
        gap = model.new_bool_var(f'{name}_gap_{p}')


        model.add_max_equality(before, occupied[:p])
        model.add_max_equality(after, occupied[p + 1 :])
        model.add(gap <= before)
        model.add(gap <= after)
        model.add(gap + occupied[p] <= 1)
        model.add(gap >= before + after - occupied[p] - 1)
        penalties.append(gap)
    return penalties


class SearchProgress(cp_model.CpSolverSolutionCallback):

    def __init__(
        self, started: float, cancelled: Event, publish: Callable[[dict[str, Any]], None] | None
    ) -> None:
        super().__init__()
        self.started = started
        self.cancelled = cancelled
        self.publish = publish



        self.solutions = 0
        self.last_publish = 0.0

    def on_solution_callback(self) -> None:
        self.solutions += 1
        if self.cancelled.is_set():
            self.stop_search()
            return

        
        now = monotonic()
        if self.publish is not None and (self.solutions == 1 or now - self.last_publish >= 0.5):
            self.publish(
                {
                    'phase': 'solving',
                    'elapsed_seconds': round(now - self.started, 3),
                    'solutions': self.solutions,
                }
            )
            self.last_publish = now


def timetable_quality(lessons: list[Lesson]) -> dict[str, int]:
    occupied: dict[tuple[int, int], set[int]] = defaultdict(set)
    for lesson in lessons:
        occupied[lesson['class_id'], lesson['weekday']].add(lesson['period'])
    return {
        'class_windows': sum(
            max(periods) - min(periods) + 1 - len(periods) for periods in occupied.values()
        ),
        'max_daily_load': max((len(periods) for periods in occupied.values()), default=0),
    }


def generate_timetable(



        
    session: Session,
    settings: Settings,
    *,
    seed: int | None = None,
    optimize: bool = False,
    cancelled: Event | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    
    started = monotonic()
    cancelled = cancelled if cancelled is not None else Event()
    if cancelled.is_set():
        raise TimetableError('Генерация отменена.', status='cancelled')
    if progress is not None:
        progress({'phase': 'modeling', 'elapsed_seconds': 0.0, 'solutions': 0})
    if seed is None:
        seed = secrets.randbelow(2**31)
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise TimetableError('Seed должен быть целым числом от 0 до 2147483647.')
    rng = random.Random(seed)


    problem = _load_problem(session, settings)
    model = cp_model.CpModel()

    variables: dict[tuple[int, int, int], Any] = {}
    by_class: dict[tuple[int, int, int], list[Any]] = defaultdict(list)


    by_teacher: dict[tuple[int, int, int, int], list[Any]] = defaultdict(list)
    teacher_intervals: dict[tuple[int, int], list[Any]] = defaultdict(list)


    room_intervals: dict[tuple[int, int], list[Any]] = defaultdict(list)
    assumption_labels: dict[int, str] = {}
    objective: list[Any] = []
    for index, requirement in enumerate(problem.requirements):


        if cancelled.is_set():
            raise TimetableError('Генерация отменена.', status='cancelled')
        week = []
        for day in DAYS:
            daily = []
            for period in range(1, requirement.cap + 1):
                variable = model.new_bool_var(f'r{index}_d{day}_p{period}')
                variables[index, day, period] = variable
                by_class[requirement.class_id, day, period].append(variable)
                by_teacher[requirement.teacher_id, day, requirement.shift, period].append(variable)
                start, end = problem.times[requirement.shift, period]


                interval = model.new_optional_fixed_size_interval_var(
                    start,
                    end - start,
                    variable,
                    f'r{index}_d{day}_p{period}_time',
                )
                teacher_intervals[requirement.teacher_id, day].append(interval)
                if requirement.room_id is not None:
                    room_intervals[requirement.room_id, day].append(interval)
                daily.append(variable)
                objective.append((period - 1) * (4 if requirement.is_hard else 1) * variable)
            used_day = model.new_bool_var(f'r{index}_d{day}_used')
            model.add(sum(daily) >= used_day)
            model.add(sum(daily) <= requirement.cap * used_day)
            objective.append(-8 * used_day)


            excess = model.new_int_var(0, requirement.cap, f'r{index}_d{day}_over_two')
            model.add(excess >= sum(daily) - 2)
            objective.append(30 * excess)


            week.extend(daily)
        quota = model.new_bool_var(f'required_{index}')
        model.add(sum(week) == requirement.count).only_enforce_if(quota)
        model.add_assumption(quota)


        assumption_labels[quota.index] = requirement.label
    for groups in (by_class, by_teacher):


        for group in groups.values():
            model.add(sum(group) <= 1)



    for groups in (teacher_intervals, room_intervals):
        for intervals in groups.values():
            model.add_no_overlap(intervals)
    for class_id in problem.classes:
        total = sum(r.count for r in problem.requirements if r.class_id == class_id)
        cap = problem.caps[class_id]
        for day in DAYS:


            occupied = []
            for period in range(1, cap + 1):


                busy = model.new_bool_var(f'class{class_id}_d{day}_p{period}')
                model.add(busy == sum(by_class[class_id, day, period]))
                occupied.append(busy)
            objective.extend(
                30 * gap for gap in _gap_costs(model, occupied, f'class{class_id}_d{day}')
            )
            deviation = model.new_int_var(0, 5 * cap, f'class{class_id}_d{day}_deviation')


            model.add_abs_equality(deviation, 5 * sum(occupied) - total)
            objective.append(2 * deviation)
    for teacher_id in {r.teacher_id for r in problem.requirements}:
        for shift in {r.shift for r in problem.requirements if r.teacher_id == teacher_id}:
            for day in DAYS:
                occupied = []


                for period in range(1, settings.max_lessons_per_day + 1):
                    busy = model.new_bool_var(f'teacher{teacher_id}_s{shift}_d{day}_p{period}')
                    model.add(busy == sum(by_teacher[teacher_id, day, shift, period]))
                    occupied.append(busy)
                objective.extend(
                    8 * gap



                    for gap in _gap_costs(model, occupied, f'teacher{teacher_id}_s{shift}_d{day}')
                )
    tie_break = sum(rng.randrange(10) * variable for variable in variables.values())
    model.minimize((9 * len(variables) + 1) * sum(objective) + tie_break)
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = settings.solver_time_limit
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.stop_after_first_solution = not optimize
    if progress is not None:
        progress(
            {'phase': 'solving', 'elapsed_seconds': round(monotonic() - started, 3), 'solutions': 0}
        )
    callback = SearchProgress(started, cancelled, progress)
    finished = Event()

    def watch_cancellation() -> None:
        while not finished.wait(0.05):
            if cancelled.is_set():
                solver.stop_search()

    watcher = Thread(target=watch_cancellation, name='solver-cancellation', daemon=True)
    watcher.start()
    try:
        status = solver.solve(model, callback)
    finally:
        finished.set()
        watcher.join()
    if cancelled.is_set():
        raise TimetableError('Генерация отменена.', status='cancelled')
    if status == cp_model.INFEASIBLE:
        core = solver.sufficient_assumptions_for_infeasibility()
        labels = [assumption_labels[i] for i in core if i in assumption_labels]
        details = [
            'Эти обязательные часы по классам и предметам не помещаются с учётом '
            'занятости классов, учителей, кабинетов и дневных лимитов. Набор конфликтов может быть не минимальным.'
        ] + labels
        if not labels:
            details.append('Проверьте дневные лимиты и назначения общих учителей/кабинетов.')
        raise TimetableError(
            'Для текущих данных расписание без конфликтов невозможно.', details, 'infeasible'
        )
    if status == cp_model.UNKNOWN:
        raise TimetableError(
            'Лимит времени истёк до нахождения расписания. Это не означает, что расписание невозможно.',
            ['Увеличьте лимит поиска и повторите. Предыдущее расписание сохранено.'],
            'timeout',
        )
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise TimetableError(
            'Не удалось обработать модель расписания.', [solver.status_name(status)]
        )
    lessons: list[Lesson] = []
    for (index, day, period), variable in variables.items():
        if solver.boolean_value(variable):
            requirement = problem.requirements[index]
            lessons.append(
                {
                    'class_id': requirement.class_id,
                    'subject_id': requirement.subject_id,
                    'teacher_id': requirement.teacher_id,
                    'room_id': requirement.room_id,
                    'weekday': day,
                    'period': period,
                }
            )
    lessons.sort(key=lambda lesson: (lesson['class_id'], lesson['weekday'], lesson['period']))
    errors = validate_timetable(session, lessons, settings)
    if errors:
        raise TimetableError(
            'Независимая проверка обнаружила ошибку. Расписание не сохранено.', errors
        )
    optimal = status == cp_model.OPTIMAL
    return {
        'status': 'optimal' if optimal else 'feasible',
        'lessons': lessons,
        'objective': solver.value(sum(objective)),
        'seed': seed,
        'elapsed_seconds': round(monotonic() - started, 3),
        'solutions': callback.solutions,
        'optimized': optimize,
        'quality': timetable_quality(lessons),
        'message': (
            'Найдено корректное расписание; оптимальность по дополнительным предпочтениям доказана.'
            if optimal
            else 'Найдено корректное расписание. Оптимальность по дополнительным предпочтениям не доказана.'
        ),
    }


def validate_timetable(session: Session, lessons: list[Lesson], settings: Settings) -> list[str]:
    """Check every hard constraint without relying on the solver implementation."""
    try:
        problem = _load_problem(session, settings)
    except TimetableError as exc:
        return [exc.message, *exc.details]
    required = {(r.class_id, r.subject_id): r for r in problem.requirements}
    counts: Counter[tuple[int, int]] = Counter()


    seen_class: set[tuple[int, int, int]] = set()
    seen_teacher: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)


    seen_room: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    errors: list[str] = []


    fields = ('class_id', 'subject_id', 'teacher_id', 'weekday', 'period')
    for number, lesson in enumerate(lessons, 1):
        if not isinstance(lesson, dict) or any(
            not isinstance(lesson.get(field), int) or isinstance(lesson.get(field), bool)
            for field in fields
        ):

            
            errors.append(
                f'Урок {number}: идентификаторы, день и номер урока должны быть целыми числами.'
            )


            continue
        class_id, subject_id = lesson['class_id'], lesson['subject_id']
        teacher_id, day, period = lesson['teacher_id'], lesson['weekday'], lesson['period']
        room_id = lesson.get('room_id')


        if room_id is not None and (not isinstance(room_id, int) or isinstance(room_id, bool)):
            errors.append(f'Урок {number}: кабинет должен быть идентификатором или null.')
            continue


        requirement = required.get((class_id, subject_id))
        if requirement is None:


            errors.append(
                f'Урок {number}: класс {class_id} / предмет {subject_id} отсутствует в учебном плане.'
            )


            continue
        counts[class_id, subject_id] += 1
        if day not in DAYS:


            errors.append(f'Урок {number}: день недели должен быть от 0 до 4.')
        if not 1 <= period <= requirement.cap:
            errors.append(
                f'Урок {number}: для {problem.classes[class_id].name} допустимы номера 1–{requirement.cap}.'
            )


        if teacher_id != requirement.teacher_id:


            
            errors.append(f'Урок {number}: учитель не соответствует назначению класса и предмета.')
        if room_id != requirement.room_id:
            errors.append(
                f'Урок {number}: кабинет не соответствует назначению (при отключённой проверке нужен null).'
            )
        class_key = (class_id, day, period)
        if class_key in seen_class:
            errors.append(f'Конфликт класса {class_id}: день {day}, урок {period}.')
        seen_class.add(class_key)
        if day not in DAYS or not 1 <= period <= requirement.cap:
            continue
        start, end = problem.times[requirement.shift, period]
        for label, resource_id, seen in (
            ('Учитель', teacher_id, seen_teacher),
            ('Кабинет', room_id, seen_room),
        ):
            if resource_id is None:
                continue
            key = (resource_id, day)
            if any(
                start < previous_end and previous_start < end
                for previous_start, previous_end in seen[key]
            ):
                errors.append(
                    f'{label} {resource_id}: конфликт времени, день {day}, смена {requirement.shift}, урок {period}.'
                )
            seen[key].append((start, end))
    for key, requirement in required.items():
        if counts[key] != requirement.count:
            errors.append(
                f'{requirement.label}: требуется ровно {requirement.count}, найдено {counts[key]}.'
            )
    return errors
