from typing import Annotated
from fastapi import APIRouter, Depends, File, Request, UploadFile
from sqlalchemy.orm import Session
from app.config import UPLOAD_DIR
from app.database import get_db
from app.schemas import PlaylistInput, TestPlayInput
from app.services import music as service



router = APIRouter(prefix='/api', tags=['Музыка и звонки'])


DB = Annotated[Session, Depends(get_db)]


@router.get('/bells')
def bells(session: DB):
    return service.bell_catalog(session)




@router.get('/music')
def music(session: DB):

    return service.music_catalog(session)


@router.post('/music/upload', status_code=201)


def upload_music(session: DB, file: UploadFile = File(...)):


    try:
        return service.upload_track(session, file.file, file.filename or '', UPLOAD_DIR)
    finally:
        file.file.close()


@router.put('/music/playlists/{event_type}')
def set_playlist(event_type: str, data: PlaylistInput, session: DB):
    return service.save_playlist(session, event_type, data.track_ids)


@router.post('/music/test')
def test_music(data: TestPlayInput, request: Request, session: DB):

    
    return service.play_track(session, request.app.state.player, data.track_id, UPLOAD_DIR)


@router.post('/music/stop')


def stop_music(request: Request):
    request.app.state.player.stop()


    return {'message': 'Воспроизведение остановлено. Следующие звонки остаются включёнными.'}


@router.get('/music/status')


def player_status(request: Request, session: DB):
    return service.playback_status(

        session, request.app.state.player, request.app.state.bell_scheduler
    )
