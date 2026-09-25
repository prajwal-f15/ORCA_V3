from fastapi import APIRouter
from app.api.v1.health import router as health_router
from app.api.v1.brain import router as brain_router
from app.api.v1.safety import router as safety_router
from app.api.v1.speech import router as speech_router

api_v1_router = APIRouter()

api_v1_router.include_router(health_router)
api_v1_router.include_router(brain_router)
api_v1_router.include_router(safety_router)
api_v1_router.include_router(speech_router)
