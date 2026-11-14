# bell-updated
School Timetable & Music Bell

A web application for a school administrator. It builds a conflict-free weekly timetable for grades 1–11 (with parallel classes A, B, C, …) and then plays music on a bell schedule that follows that timetable, instead of a plain ring.

Backend: FastAPI, SQLAlchemy 2, Alembic, SQLite
Timetable solver: Google OR-Tools (CP-SAT)
Bell scheduling & audio: APScheduler, pygame, mutagen
Frontend: plain HTML, CSS and JavaScript served by FastAPI (no build step)
Features
Manage subjects, teachers, grades, classes (parallel groups) and, optionally, rooms.
Set the weekly curriculum per grade (e.g. grade 1: reading and literacy; grade 11: algebra, geometry) and assign teachers to subjects.
Generate a full 5-day timetable automatically. Generation runs as a background job that can be watched and cancelled.
Move a single lesson by hand; the whole week is re-validated before the change is saved.
Bell schedule built from the timetable: 45-minute lessons, 5-minute breaks and a 15-minute long break.
Teachers upload their own .mp3 / .wav tracks and assign playlists to bell events.
Optional second shift, configurable start times and time zone (default Asia/Almaty).
Export the timetable to CSV or print it / save it as PDF.
Admin login with a protected session, plus a demo-data loader for quick testing.
The web interface is in Russian.
Getting started


The database and uploaded music are stored in ./data by default. The database schema is created and upgraded automatically on start-up through Alembic migrations.

One process only. The bell scheduler and the audio player live inside the server process, so run a single worker. Starting several workers would play every bell several times.


All old sessions are ended when the password is changed.



Bell events that can have their own playlist: lesson_start, lesson_end, break_start, long_break_start, end_of_day.

How the timetable is generated

The timetable is modelled as a constraint problem and solved with OR-Tools CP-SAT.

Hard rules (never broken):

a teacher cannot teach two classes at the same time;
a class cannot have two lessons at the same time;
a room (when rooms are enabled) cannot host two lessons at the same time;
every subject gets its required number of lessons per week, within the daily limits.

Soft goals (optimised, may be traded off):

fewer gaps ("windows") inside a class's day;
an even load across the days of the week;
avoid more than two lessons of the same subject on one day.

If no valid timetable exists, the app reports what is wrong with the input instead of failing silently. The solver time limit is configurable in Settings (default 20 seconds).

Configuration
Variable	Default	Purpose
SCHOOL_DATA_DIR	./data	Folder for the SQLite database and uploaded music
DATABASE_URL	sqlite:///<data dir>/school.db	Database connection string
SCHOOL_COOKIE_SECURE	false	Set to true when the site is served over HTTPS

See .env.example for a starting point.

Docker
bash
docker compose up --build
docker compose exec school python -m app.admin create --username admin

The app is published only on 127.0.0.1:8000, and data lives in the school_data volume. The container runs as a non-root user with a single worker.

Note: compose.yaml does not pass a sound device into the container, so the timetable and web interface work in Docker, but playing audio through speakers needs extra host configuration. For music playback it is simplest to run the app directly on the computer connected to the school's speakers.

