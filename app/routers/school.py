from typing import Annotated
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from app.database import get_db
from app.schemas import (
    AssignmentInput,
    ClassInput,
    CurriculumInput,
    GenerateInput,
    GradeInput,
    GradeUpdate,
    LessonMove,
    RoomInput,
    SettingsInput,
    SubjectInput,
    TeacherInput,
)
from app.services import school

router = APIRouter(prefix='/api', tags=['Школа и расписание'])
DB = Annotated[Session, Depends(get_db)]


@router.get('/catalog')
def catalog(session: DB):
    return school.catalog(session)


@router.post('/subjects', status_code=201)
def add_subject(data: SubjectInput, session: DB):
    return school.add_subject(data, session)


@router.post('/teachers', status_code=201)
def add_teacher(data: TeacherInput, session: DB):
    return school.add_teacher(data, session)


@router.put('/teachers/{teacher_id}')
def edit_teacher(teacher_id: int, data: TeacherInput, session: DB):
    return school.edit_teacher(teacher_id, data, session)


@router.post('/grades', status_code=201)
def add_grade(data: GradeInput, session: DB):
    return school.add_grade(data, session)


@router.put('/grades/{grade_id}')
def edit_grade(grade_id: int, data: GradeUpdate, session: DB):
    return school.edit_grade(grade_id, data, session)


@router.post('/classes', status_code=201)
def add_class(data: ClassInput, session: DB):
    return school.add_class(data, session)


@router.put('/classes/{class_id}')
def edit_class(class_id: int, data: ClassInput, session: DB):
    return school.edit_class(class_id, data, session)


@router.post('/rooms', status_code=201)
def add_room(data: RoomInput, session: DB):
    return school.add_room(data, session)


@router.post('/curriculum')
def set_curriculum(data: CurriculumInput, session: DB):
    return school.set_curriculum(data, session)


@router.post('/assignments')
def set_assignment(data: AssignmentInput, session: DB):
    return school.set_assignment(data, session)


@router.post('/seed')
def seed(session: DB):
    return school.seed(session)


@router.put('/settings')
def update_settings(data: SettingsInput, session: DB):
    return school.update_settings(data, session)


@router.post('/timetable/generate', status_code=202)
def generate(request: Request, data: GenerateInput | None = None):
    values = data or GenerateInput()
    return request.app.state.generation_jobs.submit(seed=values.seed, optimize=values.optimize)


@router.get('/timetable/jobs/current')
def current_job(request: Request):
    return request.app.state.generation_jobs.current()


@router.get('/timetable/jobs/{job_id}')
def generation_status(job_id: str, request: Request):
    return request.app.state.generation_jobs.get(job_id)


@router.post('/timetable/jobs/{job_id}/cancel')
def cancel_generation(job_id: str, request: Request):
    return request.app.state.generation_jobs.cancel(job_id)


@router.get('/timetable')
def timetable(session: DB, class_id: int | None = None, teacher_id: int | None = None):
    return school.timetable(session, class_id=class_id, guil=teacher_id)


@router.patch('/timetable/{lesson_id}')
def move_lesson(lesson_id: int, data: LessonMove, session: DB):
    return school.move_lesson(lesson_id, data, session)
