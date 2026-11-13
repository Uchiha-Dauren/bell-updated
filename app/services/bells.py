from datetime import datetime, timedelta
from typing import Any, Iterable
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.models import BellEvent, SchoolClass, Settings, TimetableLesson







EVENT_TYPES = (
    'lesson_start',
    'lesson_end',
    'break_start',
    'long_break_start',
    'end_of_day',
)







EVENT_PRIORITY = {
    'end_of_day': 5,
    'long_break_start': 4,
    'break_start': 3,
    'lesson_end': 2,
    'lesson_start': 1,
}




LESSON_MINUTES = 45
NORMAL_BREAK_MINUTES = 5
LONG_BREAK_MINUTES = 15


def period_times(settings: Settings, shift: int = 1) -> list[dict[str, Any]]:
    if shift not in (1, 2):
        raise ValueError('Смена должна быть первой или второй.')
    
    if shift == 2 and not settings.shifts_enabled:

        raise ValueError('Сначала включите две смены в настройках.')
    clock = settings.start_time if shift == 1 else settings.second_shift_start_time
    try:
        start = datetime.strptime(clock, '%H:%M')




        if start.strftime('%H:%M') != clock:



            raise ValueError('Укажите время в формате ЧЧ:ММ.')
    except (ValueError, TypeError) as exc:
        raise ValueError('Начало занятий укажите в формате ЧЧ:ММ, например 08:30.') from exc
    count = settings.max_lessons_per_day


    if not isinstance(count, int) or not 1 <= count <= 12:
        raise ValueError('Количество уроков в день должно быть от 1 до 12.')

    
    long_break_after = settings.long_break_after
    if not isinstance(long_break_after, int) or not 1 <= long_break_after <= 12:
        raise ValueError('Большая перемена должна идти после урока с номером от 1 до 12.')

    
    day = start.date()
    result: list[dict[str, Any]] = []
    for period in range(1, count + 1):
        end = start + timedelta(minutes=LESSON_MINUTES)


        if end.date() != day:
            raise ValueError(
                'Занятия должны закончиться до полуночи: начните раньше или уменьшите количество уроков.'
            )
        result.append(
            {'period': period, 'start': start.strftime('%H:%M'), 'end': end.strftime('%H:%M')}
        )
        break_minutes = LONG_BREAK_MINUTES if period == long_break_after else NORMAL_BREAK_MINUTES
        start = end + timedelta(minutes=break_minutes)


    return result


def calculate_bell_events(
    lessons: Iterable[dict[str, Any]],
    settings: Settings,

) -> list[dict[str, Any]]:
   
    grids = {1: {item['period']: item for item in period_times(settings)}}


    if settings.shifts_enabled:
        grids[2] = {item['period']: item for item in period_times(settings, shift=2)}


    occupied: dict[int, set[tuple[int, int]]] = {}
    for lesson in lessons:
        weekday, period = lesson['weekday'], lesson['period']


        shift = lesson.get('shift', 1)
        if weekday not in range(5):



            raise ValueError('День недели должен быть от 0 (понедельник) до 4 (пятница).')
        
        if shift not in grids:
            raise ValueError('Указанная смена не включена в настройках школы.')
        
        if period not in grids[shift]:
            raise ValueError(f'Урок {period} выходит за пределы учебного дня.')
        

        
        occupied.setdefault(weekday, set()).add((shift, period))
    events: dict[tuple[int, str, str], dict[str, Any]] = {}

    long_break_after = settings.long_break_after

    for weekday, slots in sorted(occupied.items()):


        last_end = max(grids[shift][period]['end'] for shift, period in slots)

        for shift, period in sorted(slots):

            times = grids[shift][period]



            kind = (
                'end_of_day'
                if times['end'] == last_end

                else ('long_break_start' if period == long_break_after else 'break_start')


            )
            for clock, event_type in (

                (times['start'], 'lesson_start'),
                (times['end'], 'lesson_end'),
                (times['end'], kind),
            ):

                
                events.setdefault(
                    (weekday, clock, event_type),
                    {
                        'weekday': weekday,
                        'time': clock,
                        'event_type': event_type,
                        'period': period,
                    },
                )
    return sorted(
        events.values(),

        key=lambda event: (event['weekday'], event['time'], -EVENT_PRIORITY[event['event_type']]),
    )


def rebuild_bell_events(session: Session, settings: Settings) -> list[dict[str, Any]]:

    
    lessons = session.execute(
        select(TimetableLesson, SchoolClass.shift).join(
            SchoolClass,
            SchoolClass.id == TimetableLesson.class_id,
        )

    ).all()
    events = calculate_bell_events(
        (
            {'weekday': lesson.weekday, 'period': lesson.period, 'shift': shift}
            for lesson, shift in lessons
        ),
        settings,
    )
    session.execute(delete(BellEvent))
    session.add_all(BellEvent(**event) for event in events)
    session.flush()
    return events
