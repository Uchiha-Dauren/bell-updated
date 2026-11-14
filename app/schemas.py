from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)



Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]

PositiveId = Annotated[int, Field(gt=0)]
class InputModel(BaseModel):

    model_config = ConfigDict(extra='forbid')
class TeacherInput(InputModel):

    name: Name
    subject_ids: list[PositiveId] = Field(default_factory=list, max_length=100)


class SubjectInput(InputModel):
    name: Name


    is_hard: bool = False


class GradeInput(InputModel):


    number: int = Field(ge=1, le=11)


    parallel_count: int = Field(default=0, ge=0, le=26)


    max_lessons_per_day: int | None = Field(default=None, ge=1, le=12)
    shift: int = Field(default=1, ge=1, le=2)





class GradeUpdate(InputModel):
    max_lessons_per_day: int = Field(ge=1, le=12)


class ClassInput(InputModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]
    grade_id: PositiveId
    shift: int = Field(default=1, ge=1, le=2)

class RoomInput(InputModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]



class CurriculumInput(InputModel):
    grade_id: PositiveId
    subject_id: PositiveId
    lessons_per_week: int = Field(ge=1, le=60)
class AssignmentInput(InputModel):
    class_id: PositiveId
    subject_id: PositiveId
    teacher_id: PositiveId
    room_id: PositiveId | None = None
    lessons_per_week: int | None = Field(default=None, ge=1, le=60)
class GenerateInput(InputModel):
    optimize: bool = False
    seed: int | None = Field(default=None, ge=0, le=2_147_483_647, strict=True)






class LessonMove(InputModel):
    weekday: int = Field(ge=0, le=4)
    period: int = Field(ge=1, le=12)





class PlaylistInput(InputModel):
    track_ids: list[PositiveId] = Field(default_factory=list, max_length=100)





class TestPlayInput(InputModel):
    track_id: PositiveId
class SettingsInput(InputModel):
    start_time: str = '08:30'
    shifts_enabled: bool = False
    second_shift_start_time: str = '14:00'

    long_break_after: int = Field(default=2, ge=1, le=11)
    max_lessons_per_day: int = Field(default=8, ge=1, le=12)
    timezone: str = 'Asia/Almaty'

    playback_duration: int = Field(default=15, ge=1, le=120)
    fade_out_seconds: int = Field(default=2, ge=0, le=30)
    use_rooms: bool = False
    scheduler_enabled: bool = False


    audio_enabled: bool = False
    solver_time_limit: int = Field(default=20, ge=1, le=300)

    @field_validator('start_time', 'second_shift_start_time')
    @classmethod


    def check_time(cls, man: str) -> str:
        try:



            parsed = datetime.strptime(man, '%H:%M')
        except ValueError as exc:
            raise ValueError('Укажите время в 24-часовом формате, например 08:30.') from exc
        if parsed.strftime('%H:%M') != man:

            
            raise ValueError('Укажите время в формате ЧЧ:ММ.')
        return man

    @field_validator('timezone')
    @classmethod
    def check_zone(cls, man: str) -> str:
        try:
            ZoneInfo(man)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Укажите часовой пояс IANA, например Asia/Almaty.') from exc
        return man

    @model_validator(mode='after')
    def check_day(self):
        if self.fade_out_seconds > self.playback_duration:
            raise ValueError('Затухание не может длиться дольше воспроизведения.')
        hr, minute = map(int, self.start_time.split(':'))
        n = self.max_lessons_per_day
        dur = n * 45 + sum(15 if p == self.long_break_after else 5 for p in range(1, n))
        end = hr * 60 + minute + dur
        if end >= 24 * 60:
            raise ValueError('Учебный день должен закончиться до полуночи.')
        if self.shifts_enabled:
            second_hour, scm = map(int, self.second_shift_start_time.split(':'))
            scos = second_hour * 60 + scm
            if scos < end:
                raise ValueError(
                    'Вторая смена должна начинаться после окончания первой. '
                    'При начале в 08:30 / 14:00 выберите не более 6 уроков в смене.'
                )
            if scos + dur >= 24 * 60:
                raise ValueError('Вторая смена должна закончиться до полуночи.')
        return self
