from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import engine
from src.init_db import init_models
from src.routers import auth_router, teams_router, users_router, files_router, stages_router, evaluations_router, events_router
from src.utils.background_tasks import scheduler, check_and_schedule_auto_activate_stages, periodic_check_auto_activate_stages
from src.utils.enum_utils import initialize_enum_data
from src.utils.router_states import initialize_router_states

app = FastAPI(
    title="Хакатон API",
    description="Здесь находится API для хакатона",
    version="1.0.0"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://hackathon.tyuiu.ru",
        "http://localhost:5173",
        "http://localhost:5174"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range"]
)
app.include_router(auth_router)
app.include_router(teams_router)
app.include_router(users_router)
app.include_router(files_router)
app.include_router(stages_router)
app.include_router(evaluations_router)
app.include_router(events_router)

@app.on_event("startup")
async def startup_event():
    """Выполняется при запуске приложения"""
    await init_models(engine)
    async with AsyncSession(engine) as session:
        await initialize_enum_data(session)
        await initialize_router_states(session)
    scheduler.start()
    # Планируем автоматическую активацию этапов при старте
    await check_and_schedule_auto_activate_stages()
    # Добавляем периодическую проверку (каждую минуту)
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler.add_job(
        periodic_check_auto_activate_stages,
        trigger=IntervalTrigger(minutes=1),
        id='periodic_check_auto_activate_stages',
        name='Periodic check for auto-activate stages',
        replace_existing=True
    )

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="HackathonAPI",
        version="1.0.0",
        description="API с JWT аутентификацией",
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "Bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter your bearer token in the format **Bearer &lt;token&gt;**"
        }
    }

    openapi_schema["security"] = [{"Bearer": []}]

    public_paths = ["/auth/login", "/auth/register", "/docs", "/openapi.json"]

    for path in openapi_schema["paths"]:
        if any(path.endswith(public_path) for public_path in public_paths):
            for method in openapi_schema["paths"][path]:
                if method.lower() in ["get", "post", "put", "delete", "patch"]:
                    openapi_schema["paths"][path][method]["security"] = []

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
