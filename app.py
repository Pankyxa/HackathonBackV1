from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from src.routers import auth_router, teams_router

app = FastAPI(
    title="Хакатон API",
    description="Здесь находится API для хакатона",
    version="1.0.0"
)

# Настройка CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(teams_router)


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
