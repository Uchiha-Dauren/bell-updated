from test_api import api as api
from test_api import wav_bytes
def test_valid_upload_playlist_dry_run_stop_and_safe_filename(api):
    c, _, up = api
    r = c.post(
        '/api/music/upload', files={'file': ('../../outside.wav', wav_bytes(), 'audio/wav')}
    )
    assert r.status_code == 201, r.text
    t = r.json()
    assert t['original_name'] == 'outside.wav'
    ps = list(up.iterdir())
    assert len(ps) == 1 and ps[0].suffix == '.wav'
    assert ps[0].name != 'outside.wav'
    assert not (up.parent / 'outside.wav').exists()
    assert (
        c.put(
            '/api/music/playlists/lesson_start', json={'track_ids': [t['id']]}
        ).status_code
        == 200
    )
    assert c.get('/api/music').json()['playlists']['lesson_start'] == [t['id']]
    r = c.post('/api/music/test', json={'track_id': t['id']})
    assert r.status_code == 200
    assert r.json()['mode'] == 'dry-run'
    assert c.get('/api/music/status').json()['mode'] == 'dry-run'
    assert c.post('/api/music/stop').status_code == 200
    assert c.get('/api/music/status').json()['busy'] is False
    assert (
        c.put('/api/music/playlists/lesson_start', json={'track_ids': [999]}).status_code
        == 404
    )
    assert c.get('/api/music').json()['playlists']['lesson_start'] == [t['id']]


def test_fake_audio_is_rejected_and_partial_upload_removed(api):
    c, _, up = api
    assert (
        c.post(
            '/api/music/upload', files={'file': ('fake.mp3', b'not an MP3', 'audio/mpeg')}
        ).status_code
        == 422
    )
    assert list(up.iterdir()) == []
    assert c.get('/api/music').json()['tracks'] == []
    assert (
        c.post(
            '/api/music/upload', files={'file': ('script.html', b'<html/>', 'text/html')}
        ).status_code
        == 422
    )


def test_missing_audio_file_returns_actionable_error(api):
    c, _, up = api
    r = c.post(
        '/api/music/upload', files={'file': ('missing.wav', wav_bytes(), 'audio/wav')}
    )
    tid = r.json()['id']
    for p in up.iterdir():
        p.unlink()
    s = c.get('/api/catalog').json()['settings']
    s['audio_enabled'] = True
    assert c.put('/api/settings', json=s).status_code == 200
    r = c.post('/api/music/test', json={'track_id': tid})
    assert r.status_code == 404
    assert 'отсутствует' in r.json()['detail']
