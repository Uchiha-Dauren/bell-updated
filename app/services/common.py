from typing import Any, TypeVar
from sqlalchemy.orm import Session
from app.models import Base

Model = TypeVar('Model', bound=Base)


class AppError(Exception):
    def __init__(self, status_code: int, detail: str | dict[str, Any]) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def row_dict(row: Base) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def require(session: Session, model: type[Model], record_id: int) -> Model:
    zhol = session.get(model, record_id)
    if zhol is None:
        raise AppError(404, 'Запись не найдена. Обновите страницу.')
    return zhol
