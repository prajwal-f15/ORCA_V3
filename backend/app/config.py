from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings."""

    # Ollama settings
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "qwen3:8b"
    OLLAMA_TIMEOUT_SECONDS: float = 300.0
    OLLAMA_NUM_PREDICT: int = 128
    OLLAMA_PLANNER_NUM_PREDICT: int = 64
    OLLAMA_NUM_CTX: int = 1024
    OLLAMA_KEEP_ALIVE: str = "1h"
    OLLAMA_THINK: bool = False
    OLLAMA_TEMPERATURE: float = 0.2


    # API configuration
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "ORCA V3 Brain Backend"
    SERVER_HOST: str = "127.0.0.1"
    SERVER_PORT: int = 8001

    # Speech-to-Text (STT) settings
    STT_MODEL: str = "base"
    STT_DEVICE: str = "cpu"
    STT_COMPUTE_TYPE: str = "int8"
    STT_MAX_AUDIO_SIZE_MB: int = 25
    STT_CPU_THREADS: int = 4
    STT_BEAM_SIZE: int = 5

    # Text-to-Speech (TTS) settings
    TTS_ENGINE: str = "edge-tts"
    TTS_DEFAULT_LANGUAGE: str = "mr"
    TTS_DEFAULT_VOICE: str = "mr-IN-AarohiNeural"
    TTS_MAX_TEXT_LENGTH: int = 2000
    TTS_RATE: str = "+0%"
    TTS_PITCH: str = "+0Hz"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
