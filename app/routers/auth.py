import hmac
from typing import Annotated
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from app.config import COOKIE_SECURE
from app.database import get_db
from app.services import auth
from app.services.common import AppError






router = APIRouter(prefix='/api/auth', tags=['Вход'])




DB = Annotated[Session, Depends(get_db)]

COOKIE_NAME = 'school_session'


limiter = auth.LoginLimiter()


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=80)



    password: str = Field(min_length=1, max_length=1024)


def require_admin(request: Request, session: DB) -> auth.Identity:


    identity = auth.identify(session, request.cookies.get(COOKIE_NAME))
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:


        csrf = request.headers.get('X-CSRF-Token', '')
        if not hmac.compare_digest(csrf.encode(), identity['csrf_token'].encode()):


            raise AppError(403, 'Проверка безопасности не пройдена. Обновите страницу.')
    return identity


@router.post('/login')

def login(data: LoginInput, request: Request, response: Response, session: DB):


    limiter.check(request.client.host if request.client else 'unknown')
    old_token = request.cookies.get(COOKIE_NAME)

    token, identity = auth.login(session, data.username.strip(), data.password)




    if old_token:
        auth.logout(session, old_token)


    response.set_cookie(

        COOKIE_NAME,
        token,


        max_age=auth.SESSION_SECONDS,
        httponly=True,


        secure=COOKIE_SECURE,
        samesite='strict',
        path='/',
    )
    response.headers['Cache-Control'] = 'no-store'
    return identity


@router.get('/me')


def me(response: Response, identity: Annotated[auth.Identity, Depends(require_admin)]):
    response.headers['Cache-Control'] = 'no-store'


    return identity


@router.post('/logout', dependencies=[Depends(require_admin)])

def logout(request: Request, response: Response, session: DB):
    auth.logout(session, request.cookies.get(COOKIE_NAME, ''))


    response.delete_cookie(
        COOKIE_NAME, path='/', secure=COOKIE_SECURE, httponly=True, samesite='strict'
    )



    
    return {'message': 'Вы вышли из системы.'}

