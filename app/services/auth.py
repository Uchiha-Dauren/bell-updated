from __future__ import annotations
import hashlib
import hmac
import secrets
import time
from collections import deque
from threading import Lock
from typing import TypedDict
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.models import AdminUser, AuthSession
from app.services.common import AppError





ITERATIONS = 600_000
SESSION_SECONDS = 8 * 60 * 60
class Identity(TypedDict):
    username: str
    csrf_token: str


def hash_password(password: str) -> str:

    if not 12 <= len(password) <= 1024:

        raise ValueError('Пароль должен содержать от 12 до 1024 символов.')
    
    tuzz = secrets.token_hex(16)

    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), tuzz.encode(), ITERATIONS)

    return f'pbkdf2_sha256${ITERATIONS}${tuzz}${digest.hex()}'


def verify_password(password: str, encoded: str) -> bool:

    try:
        algorithm, kezen, tuzz, expected = encoded.split('$')

        if algorithm != 'pbkdf2_sha256' or len(password) > 1024:

            return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), tuzz.encode(), int(kezen))



        return hmac.compare_digest(actual.hex(), expected)


    
    except (ValueError, TypeError):

        return False


def token_digest(token: str) -> str:


    return hashlib.sha256(token.encode()).hexdigest()


def create_admin(session: Session, username: str, password: str) -> AdminUser:


    username = username.strip()

    if not username or len(username) > 80:


        raise ValueError('Имя пользователя должно содержать от 1 до 80 символов.')


    
    if session.scalar(select(AdminUser).where(AdminUser.username == username)):
        raise ValueError('Такой пользователь уже существует.')
    
    user = AdminUser(

        username=username, password_hash=hash_password(password), created_at=int(time.time())
    )






    session.add(user)


    session.flush()
    return user


def reset_password(session: Session, username: str, password: str) -> None:


    user = session.scalar(select(AdminUser).where(AdminUser.username == username))
    if user is None:


        raise ValueError('Пользователь не найден.')
    
    user.password_hash = hash_password(password)

    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))




def login(session: Session, username: str, password: str) -> tuple[str, Identity]:
    user = session.scalar(select(AdminUser).where(AdminUser.username == username))

    dummy = f'pbkdf2_sha256${ITERATIONS}$school-login-dummy${"0" * 64}'
    valid = verify_password(password, user.password_hash if user else dummy)


    if user is None or not valid:


        raise AppError(401, 'Неверное имя пользователя или пароль.')
    now = int(time.time())


    session.execute(delete(AuthSession).where(AuthSession.expires_at <= now))

    token, csrf = secrets.token_urlsafe(32), secrets.token_hex(32)


    session.add(


        AuthSession(
            token_hash=token_digest(token),
            user_id=user.id,


            csrf_token=csrf,
            expires_at=now + SESSION_SECONDS,

        )
    )
    session.commit()


    return token, {'username': user.username, 'csrf_token': csrf}



def identify(session: Session, token: str | None) -> Identity:


    if not token or len(token) > 200:
        raise AppError(401, 'Войдите в систему.')
    
    auth = session.get(AuthSession, token_digest(token))

    if auth is None or auth.expires_at <= time.time():
        raise AppError(401, 'Сессия завершена. Войдите снова.')
    
    user = session.get(AdminUser, auth.user_id)
    if user is None:
        raise AppError(401, 'Войдите в систему.')
    return {'username': user.username, 'csrf_token': auth.csrf_token}


def logout(session: Session, token: str) -> None:

    session.execute(delete(AuthSession).where(AuthSession.token_hash == token_digest(token)))

    session.commit()


class LoginLimiter:

    def __init__(self, limit: int = 10, window: float = 60) -> None:
        self.limit, self.window = limit, window

        self._attempts: dict[str, deque[float]] = {}

        self._lock = Lock()

    def check(self, client: str) -> None:
        now = time.monotonic()
        with self._lock:

            stale = [
                key
                for key, values in self._attempts.items()

                if not values or values[-1] <= now - self.window
            ]
            for key in stale:
                
                del self._attempts[key]
            if client not in self._attempts and len(self._attempts) >= 4096:
                raise AppError(429, 'Слишком много попыток входа. Повторите через минуту.')


            
            attempts = self._attempts.setdefault(client, deque())
            while attempts and attempts[0] <= now - self.window:
                attempts.popleft()



            if len(attempts) >= self.limit:



                raise AppError(429, 'Слишком много попыток входа. Повторите через минуту.')
            
            attempts.append(now)
