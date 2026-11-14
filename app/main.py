import logging
from contextlib import ExitStack, asynccontextmanager
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from app.config import PROJECT_ROOT
from app.database import SessionLocal, init_db
from app.routers import auth, music, school
from app.scheduler.runner import BellScheduler
from app.services.audio import AudioPlayer
from app.services.common import AppError
from app.services.jobs import JobManager
from app.services.timetable import TimetableError
from app.upload_guard import UploadGuardMiddleware
from app.validation import validation_details



logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
logging.getLogger('apscheduler.executors.default').setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with ExitStack() as cleanup:
        app.state.player = AudioPlayer()
        cleanup.callback(app.state.player.close)
        app.state.bell_scheduler = BellScheduler(app.state.player)
        cleanup.callback(app.state.bell_scheduler.shutdown)
        app.state.generation_jobs = JobManager(SessionLocal)
        cleanup.callback(app.state.generation_jobs.shutdown)
        app.state.generation_jobs.start()
        app.state.bell_scheduler.start()
        yield





app = FastAPI(
    title='Школьное расписание и музыкальные звонки',
    version='2.1.0',
    lifespan=lifespan,
    description='Расписание без пересечений и музыка на переменах. Один серверный процесс.',
)
app.include_router(auth.router)
app.include_router(school.router, dependencies=[Depends(auth.require_admin)])



app.include_router(music.router, dependencies=[Depends(auth.require_admin)])
app.add_middleware(UploadGuardMiddleware, session_factory=lambda: SessionLocal)



app.mount('/static', StaticFiles(directory=PROJECT_ROOT / 'app' / 'static'), name='static')
ulgiler = Jinja2Templates(directory=PROJECT_ROOT / 'app' / 'templates')


@app.middleware('http')
async def same_origin_mutations(request: Request, call_next):
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        origin = request.headers.get('origin')



        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse(
                status_code=403, content={'detail': 'Запрос с другого сайта запрещён.'}
            )
    response = await call_next(request)



    response.headers['X-Content-Type-Options'] = 'nosniff'


    response.headers['Referrer-Policy'] = 'same-origin'



    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'


    return response


@app.exception_handler(IntegrityError)


async def integrity_error(req: Request, _exc: IntegrityError):


    return JSONResponse(
        status_code=409,


        content={
            'detail': 'Такая запись уже есть или данные конфликтуют. Проверьте названия и назначения.'
        },
    )


@app.exception_handler(AppError)


async def service_error(req: Request, exc: AppError):

    return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail})


@app.exception_handler(RequestValidationError)


async def validation_error(req: Request, exc: RequestValidationError):


    return JSONResponse(
        status_code=422,
        content={
            'detail':
             
              {
                'message': 'Проверьте введённые данные.',
                'details': validation_details(exc.errors()),
            }


        },
    )


@app.exception_handler(TimetableError)


async def timetable_error(req: Request, exc: TimetableError):
    return JSONResponse(
        status_code=422 if exc.status == 'invalid' else 409,
        content={'detail': {'message': exc.message, 'status': exc.status, 'details': exc.details}},
    )


@app.get('/', include_in_schema=False)


def home(request: Request):



    return ulgiler.TemplateResponse(request=request, name='index.html', context={})


@app.get('/health', tags=['System'])



def health():
    return {'status': 'ok', 'service': 'school-timetable-music-bell'}
