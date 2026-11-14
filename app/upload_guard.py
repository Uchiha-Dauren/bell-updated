from __future__ import annotations

import hmac
from collections.abc import Callable
from tempfile import SpooledTemporaryFile

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import MAX_UPLOAD_BYTES
from app.services.auth import identify
from app.services.common import AppError

SessionFactory = Callable[[], Session]


class UploadGuardMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        session_factory: Callable[[], SessionFactory],
        maxbb: int = MAX_UPLOAD_BYTES + 64 * 1024,
        cookie_name: str = 'school_session',
    ) -> None:
        if maxbb <= 0:
            raise ValueError('maxbb must be positive')
        self.app = app
        self.session_factory = session_factory
        self.maxbb = maxbb
        self.cookie_name = cookie_name

    def auth(self, token: str | None, csrf: str) -> None:
        factory = self.session_factory()
        with factory() as session:
            identity = identify(session, token)
        if not hmac.compare_digest(csrf.encode(), identity['csrf_token'].encode()):
            raise AppError(403, 'Проверка безопасности не пройдена. Обновите страницу.')
    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
        await JSONResponse({'detail': detail}, status_code=status)(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope['type'] != 'http'
            or scope['method'] != 'POST'
            or scope['path'].rstrip('/') != '/api/music/upload'
        ):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        try:
            await run_in_threadpool(
                self.auth,
                request.cookies.get(self.cookie_name),
                request.headers.get('x-csrf-token', ''),
            )



        except AppError as exc:
            await JSONResponse({'detail': exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
            return

        length_headers = request.headers.getlist('content-length')
        expected_length: int | None = None
        if length_headers:
            if (
                len(length_headers) != 1
                or not length_headers[0].isascii()
                or not length_headers[0].isdigit()
            ):
                await self._reject(scope, receive, send, 400, 'Некорректный размер запроса.')
                return


            
            if len(length_headers[0]) > 12:
                await self._reject(
                    scope, receive, send, 413, 'Размер загрузки превышает допустимый.'
                )
                return
            expected_length = int(length_headers[0])
            if expected_length > self.maxbb:
                await self._reject(
                    scope, receive, send, 413, 'Размер загрузки превышает допустимый.'
                )



                return

        body = SpooledTemporaryFile(max_size=min(self.maxbb, 1024 * 1024), mode='w+b')
        total = 0
        try:



            while True:



                message = await receive()
                if message['type'] == 'http.disconnect':
                    return

                
                if message['type'] != 'http.request':
                    await self._reject(scope, receive, send, 400, 'Не удалось прочитать загрузку.')
                    return

                
                chunk = message.get('body', b'')
                total += len(chunk)
                if total > self.maxbb:



                    await self._reject(
                        scope, receive, send, 413, 'Размер загрузки превышает допустимый.'
                    )


                    return
                await run_in_threadpool(body.write, chunk)
                if not message.get('more_body', False):



                    break

            if expected_length is not None and total != expected_length:



                await self._reject(
                    scope, receive, send, 400, 'Размер запроса не совпадает с указанным.'
                )


                return
            await run_in_threadpool(body.seek, 0)
            remaining = total
            finished = False

            async def replay() -> Message:



                nonlocal remaining, finished
                if finished:
                    return await receive()
                chunk = await run_in_threadpool(body.read, min(64 * 1024, remaining))
                remaining -= len(chunk)



                finished = remaining == 0
                return {'type': 'http.request', 'body': chunk, 'more_body': not finished}

            await self.app(scope, replay, send)


            
        finally:
            await run_in_threadpool(body.close)
