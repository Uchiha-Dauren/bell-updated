from collections import Counter

from test_api import api as api
from test_api import generate, small_school


def test_classes(api):
    a, _, _ = api
    b = a.post('/api/grades', json={'number': 5, 'parallel_count': 0}).json()['id']
    assert a.get('/api/catalog').json()['classes'] == []
    for c in ['5A', '5B']:
        d = a.post('/api/classes', json={'grade_id': b, 'name': c})
        assert d.status_code == 201, d.text
    e = a.get('/api/catalog').json()['classes']
    assert [f['name'] for f in e] == ['5A', '5B']
    assert all('student_count' not in f and 'language' not in f for f in e)
    assert '/api/classes/split' not in a.get('/openapi.json').json()['paths']
    for g in [
        dict(name='Language', grade_id=b, language='en'),
        dict(name='Afternoon', grade_id=b, shift=2),
    ]:
        assert a.post('/api/classes', json=g).status_code == 422


def test_shifts(api):
    a, _, _ = api
    b = a.get('/api/catalog').json()['settings']
    b.update(shifts_enabled=True, max_lessons_per_day=1, second_shift_start_time='14:00')
    assert a.put('/api/settings', json=b).status_code == 200
    c = a.post('/api/grades', json={'number': 7, 'parallel_count': 0}).json()['id']
    d = a.post('/api/subjects', json={'name': 'Математика'}).json()['id']
    e = a.post(
        '/api/teachers', json={'name': 'Мұғалім', 'subject_ids': [d]}
    ).json()['id']
    for f in [1, 2]:
        g = a.post(
            '/api/classes', json={'name': f'7-{f}', 'grade_id': c, 'shift': f}
        ).json()['id']
        h = a.post(
            '/api/assignments',
            json={
                'class_id': g,
                'subject_id': d,
                'teacher_id': e,
                'lessons_per_week': 5,
            },
        )
        assert h.status_code == 200, h.text
    i = generate(a, seed=123)
    assert i['seed'] == 123
    assert i['lesson_count'] == 10
    j = a.get('/api/timetable').json()
    assert set(j['shift_periods']) == {'1', '2'}
    assert j['shift_periods']['2'][0]['start'] == '14:00'
    assert Counter((k['weekday'], k['period']) for k in j['lessons']) == {
        (l, 1): 2 for l in range(5)
    }
    assert all('language' not in k for k in j['lessons'])
    assert [
        k['time']
        for k in a.get('/api/bells').json()['events']
        if k['event_type'] == 'end_of_day'
    ] == ['14:45'] * 5
    b['shifts_enabled'] = False
    assert a.put('/api/settings', json=b).status_code == 409
    assert len(a.get('/api/timetable').json()['lessons']) == 10


def test_edit(api):
    a, _, _ = api
    b, c, d = small_school(a)
    e = a.get('/api/catalog').json()['classes'][0]
    f = {g: h for g, h in e.items() if g != 'id'}
    f.update(name='1C')
    assert a.put(f'/api/classes/{e["id"]}', json=f).status_code == 200
    assert a.get('/api/timetable').json()['lessons'] == []
    assert (
        a.post(
            '/api/assignments',
            json={
                'class_id': e['id'],
                'subject_id': b,
                'teacher_id': c,
                'lessons_per_week': 3,
            },
        ).status_code
        == 200
    )
    i = generate(a)
    assert i['lesson_count'] == 5
    assert len(a.get(f'/api/timetable?class_id={e["id"]}').json()['lessons']) == 3
