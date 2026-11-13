from pathlib import Path
from typing import BinaryIO
from uuid import uuid4
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from app.config import MAX_UPLOAD_BYTES
from app.database import get_settings, school_lock
from app.models import BellEvent, MusicTrack, PlaylistCursor, PlaylistEntry
from app.services.bells import EVENT_PRIORITY, EVENT_TYPES, period_times
from app.services.common import AppError, require, row_dict








def bell_catalog(ssn: Session) -> dict:
    settings = get_settings(ssn)

    shifts = {'1': period_times(settings)}
    if settings.shifts_enabled:

        shifts['2'] = period_times(settings, shift=2)
    events = ssn.scalars(
        select(BellEvent).order_by(BellEvent.weekday, BellEvent.time, BellEvent.id)

    )
    return {
        'events': [row_dict(row) for row in events],
        'periods': shifts['1'],
        'shift_periods': shifts,
        'priority': sorted(EVENT_PRIORITY, key=lambda name: -EVENT_PRIORITY[name]),
    }


def music_catalog(ssn: Session) -> dict:
    playlists = {kind: [] for kind in EVENT_TYPES}

    for entry in ssn.scalars(select(PlaylistEntry).order_by(PlaylistEntry.position)):
        playlists[entry.event_type].append(entry.track_id)
    return {
        'tracks': [

            {'id': row.id, 'original_name': row.original_name}

            for row in ssn.scalars(select(MusicTrack).order_by(MusicTrack.id))
        ],
        'playlists': playlists,
        'event_types': list(EVENT_TYPES),
    }


def upload_track(ssn: Session, sm: BinaryIO, filename: str, upload_dir: Path) -> dict:

    filename = Path(filename.replace('\\', '/')).name

    suffix = Path(filename).suffix.lower()
    if suffix not in {'.mp3', '.wav'}:
        raise AppError(422, 'Разрешены только файлы MP3 и WAV.')
    
    destination = upload_dir / f'{uuid4().hex}{suffix}'
    try:
        count = 0
        with destination.open('xb') as output:



            while chunk := sm.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_UPLOAD_BYTES:
                    raise AppError(413, 'Максимальный размер файла — 25 МиБ.')
                
                output.write(chunk)
        try:
            audio = MP3(destination) if suffix == '.mp3' else WAVE(destination)


            if audio.info.length <= 0:
                raise ValueError('empty audio')

            
        except Exception as exc:
            raise AppError(




                
                422, 'Не удалось прочитать аудио. Нужен непустой файл MP3 или WAV.'
            ) from exc
        with school_lock:
            track = MusicTrack(original_name=filename[:255], stored_name=destination.name)
            ssn.add(track)



            ssn.commit()



            return {
                'id': track.id,
                'original_name': track.original_name,
                'message': 'Музыка загружена.',

            }
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def save_playlist(ssn: Session, event_type: str, track_ids: list[int]) -> dict:



    if event_type not in EVENT_TYPES:



        raise AppError(422, 'Неизвестный тип звонка.')
    with school_lock:
        for track_id in track_ids:



            require(ssn, MusicTrack, track_id)


        ssn.execute(delete(PlaylistEntry).where(PlaylistEntry.event_type == event_type))
        ssn.add_all(
            PlaylistEntry(event_type=event_type, track_id=track_id, position=position)
            for position, track_id in enumerate(track_ids)



        )
        cursor = ssn.get(PlaylistCursor, event_type)
        if cursor:
            cursor.next_index = 0



        ssn.commit()
    return {'message': 'Плейлист сохранён. Очередь воспроизведения начнётся сначала.'}





def play_track(ssn: Session, pic, track_id: int, upload_dir: Path) -> dict:
    track = require(ssn, MusicTrack, track_id)
    settings = get_settings(ssn)

    



    try:
        return pic.play(
            upload_dir / track.stored_name,
            duration=settings.playback_duration,




            fade_seconds=settings.fade_out_seconds,
            enabled=settings.audio_enabled,
        )
    except FileNotFoundError as exc:
        raise AppError(404, 'Аудиофайл отсутствует на диске. Загрузите его заново.') from exc

    


def playback_status(ssn: Session, pic, sch) -> dict:



    state = pic.status()
    original_name = ssn.scalar(



        select(MusicTrack.original_name).where(MusicTrack.stored_name == state.get('track'))
    )
    return state | {'original_name': original_name, 'scheduler': sch.status()}
