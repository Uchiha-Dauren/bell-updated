import asyncio
import time
from collections import deque
from tempfile import SpooledTemporaryFile
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models import AdminUser, AuthSession, Base
from app.services.auth import token_digest
from app.upload_guard import UploadGuardMiddleware


@pytest.fixture
def upload_factory(tmp_path):
    engine = create_engine(

        f'sqlite:///{tmp_path / "upload.db"}', connect_args={'check_same_thread': False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory.begin() as session:
        user = AdminUser(username='upload-admin', password_hash='unused', created_at=1)
        session.add(user)
        session.flush()


        session.add(
            AuthSession(
                token_hash=token_digest('test-session'),
                user_id=user.id,
                csrf_token='test-csrf',
                expires_at=int(time.time()) + 60,
            )
        )
    yield factory
    engine.dispose()


def make_scope(authenticated=True, csrf='test-csrf', length=None):
    headers = []
    if authenticated:


        headers.append((b'cookie', b'school_session=test-session'))
        headers.append((b'x-csrf-token', csrf.encode()))
    if length is not None:
        headers.append((b'content-length', str(length).encode()))
    return {
        'type': 'http',
        'asgi': {'version': '3.0'},
        'http_version': '1.1',
        'method': 'POST',
        'scheme': 'http',
        'path': '/api/music/upload',
        'raw_path': b'/api/music/upload',
        'query_string': b'',
        'headers': headers,
        'client': ('127.0.0.1', 1234),
        'server': ('testserver', 80),
    }


def invoke(factory, scope, chunks, limit=16, app_error=False, disconnect=False):
    requests = deque(
        {'type': 'http.request', 'body': body, 'more_body': index < len(chunks) - 1 or disconnect}
        for index, body in enumerate(chunks)
    )




    if disconnect:
        requests.append({'type': 'http.disconnect'})
    received = []
    sent = []
    downstream = []

    async def receive():
        message = requests.popleft()
        received.append(message)
        return message

    async def send(message):
        sent.append(message)




    async def app(_scope, receive_body, send_response):
        data = bytearray()
        while True:
            message = await receive_body()
            data.extend(message.get('body', b''))
            if not message.get('more_body', False):
                break
        downstream.append(bytes(data))
        if app_error:
            raise RuntimeError('downstream failure')
        await send_response({'type': 'http.response.start', 'status': 201, 'headers': []})
        await send_response({'type': 'http.response.body', 'body': b'ok'})

    guard = UploadGuardMiddleware(app, session_factory=lambda: factory, maxbb=limit)
    asyncio.run(guard(scope, receive, send))
    return received, sent, downstream


@pytest.mark.parametrize(
    ('authenticated', 'csrf', 'expected'),
    [
        (False, '', 401),
        (True, '', 403),
        (True, 'wrong', 403),
    ],
)
def test_auth_failure_never_reads_upload_body(upload_factory, authenticated, csrf, expected):


    received, sent, downstream = invoke(
        upload_factory, make_scope(authenticated, csrf), [b'oversized-body' * 100]
    )
    assert received == []
    assert downstream == []


    assert sent[0]['status'] == expected


def test_content_length_overflow_rejected_without_reading(upload_factory):
    received, sent, downstream = invoke(upload_factory, make_scope(length=17), [b'x' * 17])
    assert received == []
    assert downstream == []
    assert sent[0]['status'] == 413


def test_chunked_overflow_stops_reading_and_never_invokes_parser(upload_factory):
    received, sent, downstream = invoke(upload_factory, make_scope(), [b'a' * 8, b'b' * 9, b'c'])
    assert len(received) == 2
    assert downstream == []
    assert sent[0]['status'] == 413


@pytest.mark.parametrize('length', [None, 16])
def test_valid_stream_is_replayed_exactly(upload_factory, length):
    received, sent, downstream = invoke(
        upload_factory, make_scope(length=length), [b'a' * 8, b'b' * 8]
    )
    assert len(received) == 2
    assert downstream == [b'a' * 8 + b'b' * 8]
    assert sent[0]['status'] == 201


def test_incorrect_content_length_cannot_bypass_limit(upload_factory):
    _, sent, downstream = invoke(upload_factory, make_scope(length=1), [b'a' * 17])
    assert sent[0]['status'] == 413
    assert downstream == []
    _, sent, downstream = invoke(upload_factory, make_scope(length=16), [b'a'])
    assert sent[0]['status'] == 400
    assert downstream == []


@pytest.mark.parametrize('failure', ['overflow', 'disconnect', 'downstream'])
def test_spooled_body_is_closed_on_all_exit_paths(upload_factory, monkeypatch, failure):
    spools = []

    def track_spool(*args, **kwargs):
        spool = SpooledTemporaryFile(*args, **kwargs)
        spools.append(spool)
        return spool

    monkeypatch.setattr('app.upload_guard.SpooledTemporaryFile', track_spool)
    if failure == 'downstream':
        
        with pytest.raises(RuntimeError, match='downstream failure'):
            invoke(upload_factory, make_scope(), [b'data'], app_error=True)
    elif failure == 'disconnect':
        _, sent, downstream = invoke(upload_factory, make_scope(), [b'data'], disconnect=True)
        assert sent == downstream == []
    else:
        invoke(upload_factory, make_scope(), [b'x' * 17])
    assert len(spools) == 1
    assert spools[0].closed
