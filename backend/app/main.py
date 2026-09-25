from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import api_v1_router
from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="ORCA V3 Intelligent Marine Navigation and Safety Backend",
)

# Enable CORS for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API v1 router
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["Root"])
async def root():
    """Root endpoint providing service metadata and links."""
    return {
        "service": settings.PROJECT_NAME,
        "status": "online",
        "docs_url": "/docs",
        "health_check": f"{settings.API_V1_PREFIX}/health",
        "brain_chat": f"{settings.API_V1_PREFIX}/brain/chat",
    }
