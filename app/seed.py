import argparse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import SessionLocal, get_settings, init_db, school_lock
from app.models import Grade, GradeSubject, Room, SchoolClass, Subject, Teacher, TeachingAssignment

def seed_demo(session: Session) -> dict:
    if any(
        session.scalar(select(func.count()).select_from(model))


        for model in (Grade, Subject, Teacher, Room, SchoolClass)
    ):
        raise ValueError(
            'Демо можно загрузить только в пустую школу. Существующие данные сохранены.'
        )
    curriculum = {
        1: [
            ('Грамота', 5),
            ('Математика', 4),
            ('Окружающий мир', 2),
            ('ИЗО', 2),
            ('Физкультура', 2),
            ('Музыка', 1),
        ],



        6: [
            ('Математика', 4),
            ('Литература', 4),
            ('Естествознание', 3),
            ('История', 2),
            ('Физкультура', 2),
            ('ИЗО', 1),
        ],



        11: [
            ('Алгебра', 4),
            ('Геометрия', 2),
            ('Физика', 3),
            ('Литература', 3),
            ('История', 2),
            ('Физкультура', 2),
        ],
    }
    subjects = {}



    for name in sorted({name for rows in curriculum.values() for name, _ in rows}):
        subjects[name] = Subject(
            name=name, is_hard=name in {'Математика', 'Алгебра', 'Геометрия', 'Физика'}
        )
        session.add(subjects[name])
    teacher_specs = [
        ('Айгерим — математика', ['Математика', 'Алгебра', 'Геометрия']),
        ('Дана — литература', ['Грамота', 'Литература']),
        ('Ерсултан — естествознание', ['Окружающий мир', 'Естествознание', 'Физика']),
        ('Жанар — история и музыка', ['История', 'Музыка']),
        ('Асель — ИЗО', ['ИЗО']),
        ('Даурен — физкультура', ['Физкультура']),
    ]
    by_subject = {}
    for name, names in teacher_specs:
        teacher = Teacher(name=name, subjects=[subjects[n] for n in names])
        session.add(teacher)
        for subject_name in names:
            by_subject[subject_name] = teacher
    session.flush()
    for number, entries in curriculum.items():
        grade = Grade(number=number, max_lessons_per_day={1: 4, 6: 6, 11: 7}[number])
        session.add(grade)
        session.flush()
        for name, count in entries:
            session.add(
                GradeSubject(
                    grade_id=grade.id, subject_id=subjects[name].id, lessons_per_week=count
                )
            )
        for suffix in ('A', 'B'):
            room = Room(name=f'Кабинет {number}{suffix}')
            school_class = SchoolClass(name=f'{number}{suffix}', grade_id=grade.id)
            session.add_all([room, school_class])
            session.flush()
            for name, _ in entries:
                session.add(
                    TeachingAssignment(
                        class_id=school_class.id,
                        subject_id=subjects[name].id,
                        teacher_id=by_subject[name].id,
                        room_id=room.id,
                    )
                )



    get_settings(session).use_rooms = True
    session.flush()
    return {
        'message': 'Демо готово: 1, 6 и 11 классы; 6 параллелей, 6 учителей и 96 уроков в неделю.'
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--generate', action='store_true', help='Также создать и сохранить расписание.'
    )
    args = parser.parse_args()
    init_db()
    with school_lock, SessionLocal.begin() as session:
        try:
            print(seed_demo(session)['message'])
        except ValueError as exc:
            print(exc)
        if args.generate:
            from sqlalchemy import delete

            from app.models import TimetableLesson
            from app.services.bells import rebuild_bell_events
            from app.services.timetable import generate_timetable

            settings = get_settings(session)
            result = generate_timetable(session, settings)
            session.execute(delete(TimetableLesson))
            session.add_all(TimetableLesson(**row) for row in result['lessons'])
            session.flush()
            rebuild_bell_events(session, settings)
            print(f'Сохранено уроков: {len(result["lessons"])} ({result["status"]}).')


if __name__ == '__main__':
    main()
