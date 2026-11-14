from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient
from app import main
@pytest.mark.parametrize('failure', ['jobs.start', 'bells.start', 'jobs.stop'])
def test_lifespan_releases_resources_when_background_service_fails(monkeypatch, failure):
    calls = []
    def action(name):
        def run():
            calls.append(name)
            if name == failure:
                raise RuntimeError(name)

        return run





    monkeypatch.setattr(main, 'init_db', lambda: None)
    monkeypatch.setattr(main, 'AudioPlayer', lambda: SimpleNamespace(close=action('audio.close')))
    monkeypatch.setattr(
        main,
        'BellScheduler',
        lambda _player: SimpleNamespace(start=action('bells.start'), shutdown=action('bells.stop')),
    )
    monkeypatch.setattr(
        main,
        'JobManager',
        lambda _factory: SimpleNamespace(start=action('jobs.start'), shutdown=action('jobs.stop')),
    )
    with pytest.raises(RuntimeError, match=failure):
        with TestClient(main.app) as client:
            assert client.get('/health').status_code == 200
    assert calls[-3:] == ['jobs.stop', 'bells.stop', 'audio.close']
