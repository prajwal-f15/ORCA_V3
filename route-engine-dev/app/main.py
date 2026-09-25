from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as api_router
from app.core.config import get_settings
from app.db.database import init_db
from app.models.response import ServiceInfoResponse

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context manager for startup and shutdown hooks."""
    init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Production-ready, modular Route Engine service for ORCA V3 Marine Platform.",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

import logging
import uuid
from fastapi import Request

logger = logging.getLogger("orca.route_engine")

# Enable CORS for local testing dashboard and browser integrations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Attach correlation ID to request and response headers for distributed tracing and audit."""
    request_id = request.headers.get("X-Request-ID") or f"req-{uuid.uuid4().hex[:12]}"
    request.state.request_id = request_id

    logger.debug("Handling request [%s] %s %s", request_id, request.method, request.url.path)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.get(
    "/",
    response_model=ServiceInfoResponse,
    summary="Root Service Information",
    description="Provides basic service identification and status metadata.",
    tags=["General"],
)
async def root_info() -> ServiceInfoResponse:
    """Return basic information about the Route Engine service."""
    return ServiceInfoResponse(
        name=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        docs_url=f"http://{settings.HOST}:{settings.PORT}/docs",
        details={
            "description": "ORCA V3 Route Engine Foundation Service",
            "debug": settings.DEBUG,
        },
    )


# Include API routes (both directly at root and under versioned prefix if configured)
from brain_integration.routes import router as brain_test_router

app.include_router(api_router)
app.include_router(brain_test_router)
if settings.API_V1_STR:
    app.include_router(api_router, prefix=settings.API_V1_STR, tags=["V1"])
    app.include_router(brain_test_router, prefix=settings.API_V1_STR, tags=["V1"])


