import logging
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker
from app.config import UPLOAD_DIR
from app.database import SessionLocal, get_settings, school_lock
from app.models import BellEvent, BellPlayback, MusicTrack, PlaylistCursor, PlaylistEntry
from app.services.audio import AudioPlayer
from app.services.bells import EVENT_PRIORITY








logger = logging.getLogger(__name__)
LATE_GRACE_SECONDS = 3


class BellScheduler:
   

    def __init__(self, player: AudioPlayer, session_factory: sessionmaker = SessionLocal):
        self.player = player

        self.session_factory = session_factory

        self._scheduler = BackgroundScheduler(timezone='UTC')
        
        self.last_result: dict[str, Any] = {'status': 'not_started'}

    def start(self) -> None:
        if self._scheduler.running:
            return
        
        self._scheduler.add_job(


            self.tick,
            'cron',
            second='*',


            id='school-bell',
            replace_existing=True,


            max_instances=1,

            coalesce=True,

            misfire_grace_time=1,
        )
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)

    def status(self) -> dict[str, Any]:
        return {'running': self._scheduler.running, 'last_result': self.last_result}

    def tick(self, now: datetime | None = None) -> dict[str, Any]:
        if now is not None and now.tzinfo is None:
            raise ValueError('Scheduler test timestamps must be timezone-aware.')
        with school_lock:
            try:
                self.last_result = self._tick_locked(now)
            except Exception as exc:
                logger.exception('Bell scheduler failed')
                self.last_result = {'status': 'error', 'message': str(exc)}
            return self.last_result

    def _tick_locked(self, now: datetime | None) -> dict[str, Any]:
        with self.session_factory() as session:
            settings = get_settings(session)


            if not settings.scheduler_enabled:

                return {'status': 'disabled'}
            
            local_now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo(settings.timezone))


            if local_now.weekday() >= 5:
                return {'status': 'weekend'}
            if local_now.second + local_now.microsecond / 1_000_000 > LATE_GRACE_SECONDS:

                return {'status': 'outside_grace'}

            
            bell_time = local_now.strftime('%H:%M')
            events = session.scalars(

                select(BellEvent).where(

                    BellEvent.weekday == local_now.weekday(),
                    BellEvent.time == bell_time,
                )
            ).all()
            if not events:
                return {'status': 'no_event'}
            key = f'{local_now.date().isoformat()}:{bell_time}'

            if session.get(BellPlayback, key) is not None:

                return {'status': 'already_dispatched', 'key': key}

            
            claim = BellPlayback(key=key, status='claimed')


            session.add(claim)
            selected: tuple[str, MusicTrack] | None = None

            for event in sorted(events, key=lambda event: -EVENT_PRIORITY.get(event.event_type, 0)):
                tracks = session.scalars(
                    
                    select(MusicTrack)


                    .join(PlaylistEntry, PlaylistEntry.track_id == MusicTrack.id)

                    .where(PlaylistEntry.event_type == event.event_type)

                    .order_by(PlaylistEntry.position, PlaylistEntry.id),

                ).all()

                if not tracks:

                    continue
                cursor = session.get(PlaylistCursor, event.event_type)


                if cursor is None:

                    cursor = PlaylistCursor(event_type=event.event_type, next_index=0)

                    session.add(cursor)

                index = cursor.next_index % len(tracks)
                track = tracks[index]

                cursor.next_index = (index + 1) % len(tracks)
                selected = event.event_type, track

                break
            duration, fade_seconds, enabled = (
                settings.playback_duration,

                settings.fade_out_seconds,
                settings.audio_enabled,

            )
            if selected is None:
                claim.status = 'no_playlist'

                session.commit()
                logger.info('Bell %s has no configured playlist', key)

                return {'status': 'no_playlist', 'key': key}
            
            event_type, track = selected
            track_id, stored_name = track.id, track.stored_name


            session.commit()
        try:
            result = self.player.play(
                UPLOAD_DIR / stored_name,
                duration=duration,
                fade_seconds=fade_seconds,

                enabled=enabled,


            )
            outcome = 'dry_run' if not enabled else 'dispatched'
        except Exception as exc:


            logger.exception('Could not start bell %s', key)

            result = {'error': str(exc)}
            outcome = 'failed'
        with self.session_factory.begin() as session:

            claim = session.get(BellPlayback, key)

            if claim is not None:
                claim.status = f'{outcome}: {event_type}; track={track_id}'[:255]

        return {
            'status': outcome,

            'key': key,
            
            'event_type': event_type,
            'track_id': track_id,

            'player': result,
        }
