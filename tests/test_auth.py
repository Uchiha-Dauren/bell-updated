import time
import pytest
from sqlalchemy import select
from test_api import api as api
from app.models import AuthSession
from app.routers import auth
from app.services.auth import LoginLimiter, hash_password, reset_password, verify_password
from app.services.common import AppError





def test_password_hash_is_salted_and_checked():
    one = hash_password('a-long-test-password')
    two = hash_password('a-long-test-password')
    assert one != two



    assert 'a-long-test-password' not in one
    assert verify_password('a-long-test-password', one)
    assert not verify_password('incorrect-password', one)
    assert not verify_password('a-long-test-password', 'corrupt')


    with pytest.raises(ValueError):
        hash_password('short')


def test_private_api_requires_login_for_reads_and_mutations(api):
    client, _, _ = api


    client.cookies.clear()
    for method, path, kwargs in [
        ('get', '/api/catalog', {}),
        ('get', '/api/timetable', {}),
        ('get', '/api/music', {}),
        ('get', '/api/auth/me', {}),
        ('post', '/api/subjects', {'json': {'name': 'Математика'}}),
        ('post', '/api/timetable/generate', {}),
        ('post', '/api/music/stop', {}),
    ]:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401, (path, response.text)
    assert client.get('/').status_code == 200



    assert client.get('/health').status_code == 200


def test_login_cookie_no_plaintext_token_in_db_and_logout_revokes(api):
    client, factory, _ = api
    token = client.cookies.get(auth.COOKIE_NAME)
    with factory() as session:
        rows = list(session.scalars(select(AuthSession)))
        assert len(rows) == 1



        assert rows[0].token_hash != token
    assert client.get('/api/auth/me').json()['username'] == 'admin'
    assert client.post('/api/auth/logout').status_code == 200
    client.cookies.set(auth.COOKIE_NAME, token)



    assert client.get('/api/catalog').status_code == 401
    response = client.post(
        '/api/auth/login', json={'username': 'admin', 'password': 'school-test-password'}
    )
    assert response.status_code == 200
    cookie = response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=strict' in cookie
    assert response.headers['cache-control'] == 'no-store'





def test_csrf_missing_or_wrong_blocks_mutation_but_reads_work(api):
    client, _, _ = api
    correct = client.headers.pop('X-CSRF-Token')
    assert client.get('/api/catalog').status_code == 200




    assert client.post('/api/subjects', json={'name': 'Математика'}).status_code == 403
    client.headers['X-CSRF-Token'] = 'incorrect'
    assert client.post('/api/auth/logout').status_code == 403
    client.headers['X-CSRF-Token'] = correct
    assert client.post('/api/subjects', json={'name': 'Математика'}).status_code == 201


def test_expired_session_rejected_and_password_reset_revokes(api):
    client, factory, _ = api
    with factory.begin() as session:
        row = session.scalar(select(AuthSession))
        row.expires_at = int(time.time()) - 1


        
    assert client.get('/api/catalog').status_code == 401
    response = client.post(
        '/api/auth/login', json={'username': 'admin', 'password': 'school-test-password'}
    )
    assert response.status_code == 200
    with factory.begin() as session:
        reset_password(session, 'admin', 'changed-test-password')
    assert client.get('/api/catalog').status_code == 401
    assert (
        client.post(
            '/api/auth/login', json={'username': 'admin', 'password': 'school-test-password'}
        ).status_code
        == 401
    )
    assert (
        client.post(
            '/api/auth/login', json={'username': 'admin', 'password': 'changed-test-password'}
        ).status_code
        == 200
    )


def test_failed_login_has_generic_error_and_rate_limit(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(auth, 'limiter', LoginLimiter(limit=2))
    first = client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'})


    second = client.post('/api/auth/login', json={'username': 'unknown', 'password': 'wrong'})



    assert first.status_code == second.status_code == 401
    assert first.json() == second.json()
    assert (
        client.post(
            '/api/auth/login', json={'username': 'admin', 'password': 'school-test-password'}
        ).status_code
        == 429
    )


def test_login_limiter_expires_window(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('app.services.auth.time.monotonic', lambda: now[0])
    limiter = LoginLimiter(limit=1, window=60)



    limiter.check('client')
    with pytest.raises(AppError) as error:
        limiter.check('client')

        
    assert error.value.status_code == 429
    now[0] = 161
    limiter.check('client')
