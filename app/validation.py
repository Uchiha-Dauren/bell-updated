from typing import Any
FIELD_LABELS = {
    'name': 'Название',
    'username': 'Имя пользователя',
    'password': 'Пароль',
    'number': 'Уровень обучения',
    'parallel_count': 'Количество классов',
    'max_lessons_per_day': 'Максимум уроков в день',
    'grade_id': 'Параллель',
    'class_id': 'Класс',
    'teacher_id': 'Учитель',
    'subject_id': 'Предмет',
    'subject_ids': 'Предметы учителя',
    'room_id': 'Кабинет',
    'lessons_per_week': 'Уроков в неделю',
    'shift': 'Смена',
    'weekday': 'День недели',
    'period': 'Номер урока',
    'start_time': 'Начало занятий',
    'second_shift_start_time': 'Начало второй смены',
    'long_break_after': 'Большая перемена после урока',
    'timezone': 'Часовой пояс',
    'playback_duration': 'Продолжительность музыки',
    'fade_out_seconds': 'Затухание',
    'solver_time_limit': 'Лимит поиска',
    'seed': 'Начальное число генерации',
    'optimize': 'Улучшение расписания',
    'track_id': 'Трек',
    'track_ids': 'Плейлист',
}

ERROR_MESSAGES = {
    'missing': 'заполните это поле',
    'int_type': 'укажите целое число',
    'int_parsing': 'укажите целое число',
    'bool_parsing': 'выберите включено или выключено',
    'string_type': 'введите текст',
    'string_too_short': 'минимальная длина — {min_length}',
    'string_too_long': 'максимальная длина — {max_length}',
    'greater_than': 'значение должно быть больше {gt}',
    'greater_than_equal': 'минимальное значение — {ge}',
    'less_than': 'значение должно быть меньше {lt}',
    'less_than_equal': 'максимальное значение — {le}',
    'extra_forbidden': 'это поле не поддерживается',
    'json_invalid': 'не удалось прочитать данные запроса',
}





def validation_details(errors: list[Any]) -> list[str]:

    details = []

    for error in errors:
        location = [part for part in error['loc'] if part not in {'body', 'query', 'path'}]


        labels = [FIELD_LABELS.get(str(part), str(part)) for part in location]

        label = ' → '.join(labels) or 'Данные формы'
        if error['type'] == 'value_error':
            message = error['msg'].removeprefix('Value error, ')
        else:
            template = ERROR_MESSAGES.get(error['type'], 'проверьте формат значения')
            message = template.format(**error.get('ctx', {}))

            
        details.append(f'{label}: {message}.'.replace('..', '.'))
    return details
