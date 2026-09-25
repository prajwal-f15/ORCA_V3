import asyncio
import io
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.schemas.speech import STTModelInfoResponse, TranscribeResponse

logger = logging.getLogger(__name__)

# Standard audio extensions allowed for maritime STT upload
SUPPORTED_AUDIO_EXTENSIONS = {
    ".wav",
    ".mp3",
    ".ogg",
    ".m4a",
    ".flac",
    ".webm",
    ".aac",
    ".wma",
    ".opus",
}

# Standard 99 Whisper-supported language codes
WHISPER_SUPPORTED_LANGUAGES = [
    "en", "zh", "de", "es", "ru", "ko", "fr", "ja", "pt", "tr",
    "pl", "ca", "nl", "ar", "sv", "it", "id", "hi", "fi", "vi",
    "he", "uk", "el", "ms", "cs", "ro", "da", "hu", "ta", "no",
    "th", "ur", "hr", "bg", "lt", "la", "mi", "ml", "cy", "sk",
    "te", "fa", "lv", "bn", "sr", "az", "sl", "kn", "et", "mk",
    "br", "eu", "is", "hy", "ne", "mn", "bs", "kk", "sq", "sw",
    "gl", "mr", "pa", "si", "km", "sn", "yo", "so", "af", "oc",
    "ka", "be", "tg", "sd", "gu", "am", "yi", "lo", "uz", "fo",
    "ht", "ps", "tk", "nn", "mt", "sa", "lb", "my", "bo", "tl",
    "mg", "as", "tt", "haw", "ln", "ha", "ba", "jw", "su", "yue"
]

# Explicit alias dictionary for normalizing STT language hints
STT_LANGUAGE_ALIASES: Dict[str, str] = {
    "mr": "mr",
    "mr-in": "mr",
    "marathi": "mr",
    "hi": "hi",
    "hi-in": "hi",
    "hindi": "hi",
    "en": "en",
    "en-in": "en",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",
    "gu": "gu",
    "gu-in": "gu",
    "gujarati": "gu",
    "ta": "ta",
    "ta-in": "ta",
    "tamil": "ta",
    "te": "te",
    "te-in": "te",
    "telugu": "te",
    "kn": "kn",
    "kn-in": "kn",
    "kannada": "kn",
    "ml": "ml",
    "ml-in": "ml",
    "malayalam": "ml",
    "bn": "bn",
    "bn-in": "bn",
    "bn-bd": "bn",
    "bengali": "bn",
    "ur": "ur",
    "ur-in": "ur",
    "urdu": "ur",
    "pa": "pa",
    "pa-in": "pa",
    "punjabi": "pa",
    "sa": "sa",
    "sa-in": "sa",
    "sanskrit": "sa",
    "sd": "sd",
    "sd-in": "sd",
    "sindhi": "sd",
    "as": "as",
    "as-in": "as",
    "assamese": "as",
    "ne": "ne",
    "ne-np": "ne",
    "nepali": "ne",
}


def normalize_stt_language(language: Optional[str]) -> Optional[str]:
    """
    Normalize an input language identifier (e.g. 'mr-IN', 'marathi', 'en-US') to a valid Whisper ISO code.

    Returns:
        Standard 2-letter Whisper language code if valid/recognized, or None for automatic language detection.
    """
    if not language:
        return None
    cleaned = language.strip().lower()
    if not cleaned:
        return None

    if cleaned in STT_LANGUAGE_ALIASES:
        return STT_LANGUAGE_ALIASES[cleaned]

    if cleaned in WHISPER_SUPPORTED_LANGUAGES:
        return cleaned

    # Check primary language tag prefix (e.g., 'es-ES' -> 'es', 'zh-CN' -> 'zh')
    prefix = cleaned.split("-")[0].split("_")[0]
    if prefix in WHISPER_SUPPORTED_LANGUAGES:
        return prefix

    logger.warning(
        f"Requested STT language '{language}' is not in the standard Whisper language registry. Proceeding with auto-detection."
    )
    return None



class SpeechServiceError(Exception):
    """Base exception for speech service failures."""
    pass


class AudioValidationError(SpeechServiceError):
    """Raised when uploaded audio fails format, size, or integrity checks."""
    pass


class ModelUnavailableError(SpeechServiceError):
    """Raised when the STT model fails to initialize or is offline."""
    pass


class TranscriptionError(SpeechServiceError):
    """Raised when transcription processing fails during inference."""
    pass


class BaseSTTService(ABC):
    """Abstract interface for Speech-to-Text services."""

    @abstractmethod
    def validate_audio(self, audio_bytes: bytes, filename: Optional[str] = None) -> None:
        """Validate input audio bytes for size, non-emptiness, and format."""
        pass

    @abstractmethod
    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TranscribeResponse:
        """Transcribe speech audio into natural text in original language."""
        pass

    @abstractmethod
    def get_model_info(self) -> STTModelInfoResponse:
        """Return metadata about the underlying STT engine and model."""
        pass


class FasterWhisperSTTService(BaseSTTService):
    """
    Production-grade Speech-to-Text implementation using faster-whisper (CTranslate2).
    
    Optimized for CPU inference on Windows laptops (Intel Core i7, 16GB RAM),
    providing fast multilingual transcription with INT8 quantization.
    """

    def __init__(self):
        self._settings = get_settings()
        self._model = None
        self._lock = threading.Lock()
        self._model_load_time: Optional[float] = None

    def _get_model(self):
        """Thread-safe lazy initialization and reuse of the WhisperModel instance."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    model_name = self._settings.STT_MODEL
                    device = self._settings.STT_DEVICE
                    compute_type = self._settings.STT_COMPUTE_TYPE
                    cpu_threads = self._settings.STT_CPU_THREADS

                    logger.info(
                        f"Initializing faster-whisper model '{model_name}' on device='{device}', "
                        f"compute_type='{compute_type}', cpu_threads={cpu_threads}..."
                    )
                    start_load = time.perf_counter()
                    try:
                        from faster_whisper import WhisperModel

                        self._model = WhisperModel(
                            model_size_or_path=model_name,
                            device=device,
                            compute_type=compute_type,
                            cpu_threads=cpu_threads,
                            download_root=None,
                        )
                        self._model_load_time = round(time.perf_counter() - start_load, 3)
                        logger.info(
                            f"faster-whisper model '{model_name}' loaded successfully in {self._model_load_time}s"
                        )
                    except Exception as exc:
                        logger.error(f"Failed to load faster-whisper model '{model_name}': {exc}", exc_info=True)
                        raise ModelUnavailableError(
                            f"STT model '{model_name}' could not be loaded on {device} ({compute_type}): {exc}"
                        ) from exc
        return self._model

    def validate_audio(self, audio_bytes: bytes, filename: Optional[str] = None) -> None:
        """
        Validate audio payload size, presence of bytes, and format.
        
        Raises:
            AudioValidationError: On empty payload, oversized upload, or invalid extension.
        """
        # 1. Empty audio check
        if not audio_bytes or len(audio_bytes) == 0:
            raise AudioValidationError("Audio upload is empty (0 bytes). Please provide valid audio data.")

        # 2. Maximum file size check
        max_bytes = self._settings.STT_MAX_AUDIO_SIZE_MB * 1024 * 1024
        if len(audio_bytes) > max_bytes:
            size_mb = round(len(audio_bytes) / (1024 * 1024), 2)
            raise AudioValidationError(
                f"Audio file size ({size_mb} MB) exceeds maximum allowed limit of {self._settings.STT_MAX_AUDIO_SIZE_MB} MB."
            )

        # 3. File extension check (if filename provided)
        if filename:
            ext = os.path.splitext(filename)[1].lower()
            if ext and ext not in SUPPORTED_AUDIO_EXTENSIONS:
                raise AudioValidationError(
                    f"Unsupported audio file format '{ext}'. Supported formats: {', '.join(sorted(SUPPORTED_AUDIO_EXTENSIONS))}"
                )

        # 4. Minimal byte header check
        # A valid audio file (e.g. WAV, MP3, OGG, FLAC, M4A) is at least ~44 bytes
        if len(audio_bytes) < 44:
            raise AudioValidationError("Corrupted or incomplete audio payload (insufficient header bytes).")

    async def transcribe(
        self,
        audio_bytes: bytes,
        filename: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TranscribeResponse:
        """
        Transcribe the supplied audio stream using faster-whisper.
        
        Args:
            audio_bytes: Raw binary audio bytes.
            filename: Optional source filename.
            language: Optional ISO-639-1 language code override.
            
        Returns:
            TranscribeResponse with verbatim transcription and metadata.
        """
        self.validate_audio(audio_bytes, filename)

        # Offload CPU-bound inference to worker thread
        return await asyncio.to_thread(self._transcribe_sync, audio_bytes, language)

    def _transcribe_sync(self, audio_bytes: bytes, language: Optional[str] = None) -> TranscribeResponse:
        model = self._get_model()

        # Sanitize and normalize language code if provided
        lang_param = normalize_stt_language(language)

        audio_stream = io.BytesIO(audio_bytes)
        start_time = time.perf_counter()

        try:
            segments, info = model.transcribe(
                audio_stream,
                language=lang_param,
                beam_size=self._settings.STT_BEAM_SIZE,
                vad_filter=True,  # Voice Activity Detection to filter out marine engine silence / noise
                vad_parameters=dict(min_silence_duration_ms=500),
            )

            # Consume segments generator
            transcribed_segments = list(segments)
            full_text = " ".join([seg.text.strip() for seg in transcribed_segments]).strip()

            processing_duration = round(time.perf_counter() - start_time, 3)
            detected_lang = info.language if info else None
            lang_prob = round(info.language_probability, 4) if info and hasattr(info, "language_probability") else None
            audio_duration = round(info.duration, 2) if info and hasattr(info, "duration") else None

            logger.info(
                f"STT complete in {processing_duration}s | Lang: {detected_lang} (p={lang_prob}) | Text: '{full_text}'"
            )

            return TranscribeResponse(
                text=full_text,
                language=detected_lang,
                confidence=lang_prob,
                duration=audio_duration,
                processing_time=processing_duration,
            )

        except ModelUnavailableError:
            raise
        except Exception as exc:
            logger.error(f"Error during audio transcription: {exc}", exc_info=True)
            raise TranscriptionError(f"Transcription processing failed: {exc}") from exc

    def get_model_info(self) -> STTModelInfoResponse:
        """Return information about the active model and configuration."""
        return STTModelInfoResponse(
            engine="faster-whisper",
            model_name=self._settings.STT_MODEL,
            device=self._settings.STT_DEVICE,
            compute_type=self._settings.STT_COMPUTE_TYPE,
            supported_languages=WHISPER_SUPPORTED_LANGUAGES,
        )


# Singleton STT Service instance
stt_service = FasterWhisperSTTService()
