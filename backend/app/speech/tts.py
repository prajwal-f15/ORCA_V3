import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from app.config import get_settings
from app.schemas.speech import TTSModelInfoResponse

logger = logging.getLogger(__name__)

# Official mapping of supported Indian language codes to Edge Neural voices by gender
EDGE_TTS_INDIAN_VOICE_MAP: Dict[str, Dict[str, str]] = {
    "mr": {
        "female": "mr-IN-AarohiNeural",
        "male": "mr-IN-ManoharNeural",
    },
    "hi": {
        "female": "hi-IN-SwaraNeural",
        "male": "hi-IN-MadhurNeural",
    },
    "en": {
        "female": "en-IN-NeerjaNeural",
        "male": "en-IN-PrabhatNeural",
    },
    "gu": {
        "female": "gu-IN-DhwaniNeural",
        "male": "gu-IN-NiranjanNeural",
    },
    "ta": {
        "female": "ta-IN-PallaviNeural",
        "male": "ta-IN-ValluvarNeural",
    },
    "te": {
        "female": "te-IN-ShrutiNeural",
        "male": "te-IN-MohanNeural",
    },
    "kn": {
        "female": "kn-IN-SapnaNeural",
        "male": "kn-IN-GaganNeural",
    },
    "ml": {
        "female": "ml-IN-SobhanaNeural",
        "male": "ml-IN-MidhunNeural",
    },
    "bn": {
        "female": "bn-IN-TanishaaNeural",
        "male": "bn-IN-BashkarNeural",
    },
    "ur": {
        "female": "ur-IN-GulNeural",
        "male": "ur-IN-SalmanNeural",
    },
}

# Alias dictionary to normalize language codes (e.g., 'mr-IN' -> 'mr', 'marathi' -> 'mr')
LANGUAGE_ALIASES: Dict[str, str] = {
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
}


class TTSServiceError(Exception):
    """Base exception for Text-to-Speech failures."""
    pass


class TTSValidationError(TTSServiceError):
    """Raised when text payload or parameters fail validation."""
    pass


class UnsupportedLanguageError(TTSServiceError):
    """Raised when requested language is not supported by active engine."""
    pass


class UnsupportedVoiceError(TTSServiceError):
    """Raised when requested voice is not available or does not match the target language."""
    pass


class TTSModelUnavailableError(TTSServiceError):
    """Raised when TTS engine or provider is offline / unreachable."""
    pass


class SynthesisError(TTSServiceError):
    """Raised when speech generation fails during inference/streaming."""
    pass


class BaseTTSService(ABC):
    """Abstract base interface for Text-to-Speech synthesis engines."""

    @abstractmethod
    def validate_request(
        self,
        text: str,
        language: Optional[str] = None,
        voice: Optional[str] = None,
        gender: Optional[str] = "female",
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Validate input text and parameters, returning resolved (normalized_lang, resolved_voice).
        """
        pass

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        language: Optional[str] = None,
        voice: Optional[str] = None,
        gender: Optional[str] = "female",
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Synthesize text into speech audio bytes along with metadata.
        
        Returns:
            Tuple of (audio_bytes, metadata_dict)
        """
        pass

    @abstractmethod
    def get_model_info(self) -> TTSModelInfoResponse:
        """Return engine metadata and list of available voices."""
        pass


class EdgeTTSService(BaseTTSService):
    """
    Production-grade Text-to-Speech implementation using Microsoft Edge Neural TTS.
    
    Optimized for zero local RAM model footprint, running efficiently on CPU laptops
    without conflicting with Qwen3-8B and Faster-Whisper.
    """

    def __init__(self):
        self._settings = get_settings()

    def _normalize_language(self, language: Optional[str]) -> str:
        """Normalize language identifier or fallback to default."""
        if not language:
            return self._settings.TTS_DEFAULT_LANGUAGE
        
        cleaned = language.strip().lower()
        if cleaned in LANGUAGE_ALIASES:
            return LANGUAGE_ALIASES[cleaned]
        
        # Check standard 2-letter prefix
        prefix = cleaned.split("-")[0].split("_")[0]
        if prefix in EDGE_TTS_INDIAN_VOICE_MAP:
            return prefix

        if cleaned in ("kok", "kok-in", "konkani"):
            raise UnsupportedLanguageError(
                "Unsupported language 'kok' (Konkani): not supported by active TTS engine (no native neural voices available)."
            )
        if cleaned in ("or", "or-in", "odia", "oriya"):
            raise UnsupportedLanguageError(
                "Unsupported language 'or' (Odia): not supported by active TTS engine (no native neural voices available)."
            )

        raise UnsupportedLanguageError(
            f"Unsupported language code '{language}'. Supported Indian languages: {', '.join(sorted(EDGE_TTS_INDIAN_VOICE_MAP.keys()))}."
        )

    def _resolve_voice(
        self,
        normalized_lang: str,
        voice: Optional[str] = None,
        gender: Optional[str] = "female",
    ) -> str:
        """Resolve voice identifier based on explicit request or language/gender default."""
        voice_dict = EDGE_TTS_INDIAN_VOICE_MAP.get(normalized_lang)
        if not voice_dict:
            raise UnsupportedLanguageError(
                f"No voice available for language '{normalized_lang}' in active TTS engine."
            )

        if voice and voice.strip():
            voice_clean = voice.strip()
            # Allowed voices for this language
            allowed_voices = set(voice_dict.values())
            if normalized_lang == "en":
                allowed_voices.add("en-IN-NeerjaExpressiveNeural")

            if voice_clean not in allowed_voices:
                raise UnsupportedVoiceError(
                    f"Voice '{voice_clean}' is not a valid voice for language '{normalized_lang}'. "
                    f"Available voices for '{normalized_lang}': {', '.join(sorted(allowed_voices))}."
                )
            return voice_clean

        gender_clean = (gender or "female").strip().lower()
        if gender_clean not in ("female", "male"):
            gender_clean = "female"

        return voice_dict.get(gender_clean, voice_dict["female"])

    def validate_request(
        self,
        text: str,
        language: Optional[str] = None,
        voice: Optional[str] = None,
        gender: Optional[str] = "female",
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
    ) -> Tuple[str, str]:
        """
        Validate input text, length boundaries, language support, and voice compatibility.
        
        Raises:
            TTSValidationError: If text is empty or exceeds length limits.
            UnsupportedLanguageError: If language is not supported.
            UnsupportedVoiceError: If explicit voice does not belong to target language.
        """
        # 1. Non-empty text check
        if not text or not text.strip():
            raise TTSValidationError("Text payload cannot be empty or whitespace-only.")

        cleaned_text = text.strip()

        # 2. Maximum text length check
        max_length = self._settings.TTS_MAX_TEXT_LENGTH
        if len(cleaned_text) > max_length:
            raise TTSValidationError(
                f"Text length ({len(cleaned_text)} characters) exceeds maximum allowed limit of {max_length} characters."
            )

        # 3. Rate format check
        if rate and not re.match(r"^[\+\-]?\d+%$", rate.strip()):
            raise TTSValidationError(f"Invalid rate parameter '{rate}'. Expected format e.g. '+0%', '+10%', '-20%'.")

        # 4. Pitch format check
        if pitch and not re.match(r"^[\+\-]?\d+Hz$", pitch.strip()):
            raise TTSValidationError(f"Invalid pitch parameter '{pitch}'. Expected format e.g. '+0Hz', '+5Hz', '-5Hz'.")

        normalized_lang = self._normalize_language(language)
        resolved_voice = self._resolve_voice(normalized_lang, voice=voice, gender=gender)

        return normalized_lang, resolved_voice

    async def synthesize(
        self,
        text: str,
        language: Optional[str] = None,
        voice: Optional[str] = None,
        gender: Optional[str] = "female",
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
    ) -> Tuple[bytes, Dict[str, Any]]:
        """
        Synthesize text into speech MP3 bytes.
        """
        normalized_lang, resolved_voice = self.validate_request(
            text=text,
            language=language,
            voice=voice,
            gender=gender,
            rate=rate,
            pitch=pitch,
        )

        effective_rate = rate.strip() if rate else self._settings.TTS_RATE
        effective_pitch = pitch.strip() if pitch else self._settings.TTS_PITCH

        start_time = time.perf_counter()
        logger.info(
            f"Starting TTS synthesis | Lang: {normalized_lang} | Voice: {resolved_voice} | Rate: {effective_rate} | Pitch: {effective_pitch} | Text length: {len(text)} chars"
        )

        try:
            import edge_tts

            communicate = edge_tts.Communicate(
                text=text.strip(),
                voice=resolved_voice,
                rate=effective_rate,
                pitch=effective_pitch,
            )

            audio_data = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_data.extend(chunk["data"])

            if not audio_data:
                raise SynthesisError("TTS engine generated 0 audio bytes. The audio stream was empty.")

            audio_bytes = bytes(audio_data)
            processing_duration = round(time.perf_counter() - start_time, 3)

            metadata: Dict[str, Any] = {
                "language": normalized_lang,
                "voice": resolved_voice,
                "engine": self._settings.TTS_ENGINE,
                "audio_bytes_length": len(audio_bytes),
                "audio_format": "audio/mpeg",
                "processing_time": processing_duration,
                "character_count": len(text.strip()),
            }

            logger.info(
                f"TTS complete in {processing_duration}s | Size: {len(audio_bytes)} bytes | Voice: {resolved_voice}"
            )
            return audio_bytes, metadata

        except (TTSValidationError, UnsupportedLanguageError):
            raise
        except ImportError as exc:
            logger.error(f"edge-tts module not installed: {exc}")
            raise TTSModelUnavailableError("TTS engine package 'edge-tts' is not available.") from exc
        except (ConnectionError, TimeoutError, OSError) as exc:
            logger.error(f"Network error communicating with TTS service: {exc}", exc_info=True)
            raise TTSModelUnavailableError(f"TTS service connection failed: {exc}") from exc
        except Exception as exc:
            logger.error(f"Unexpected error during TTS synthesis: {exc}", exc_info=True)
            raise SynthesisError(f"TTS synthesis failed: {exc}") from exc

    def get_model_info(self) -> TTSModelInfoResponse:
        """Return active engine configuration and supported voices."""
        available_voices: Dict[str, List[str]] = {
            lang: [v["female"], v["male"]]
            for lang, v in EDGE_TTS_INDIAN_VOICE_MAP.items()
        }
        return TTSModelInfoResponse(
            engine=self._settings.TTS_ENGINE,
            default_language=self._settings.TTS_DEFAULT_LANGUAGE,
            default_voice=self._settings.TTS_DEFAULT_VOICE,
            supported_languages=sorted(list(EDGE_TTS_INDIAN_VOICE_MAP.keys())),
            available_voices=available_voices,
        )


# Singleton TTS Service instance
tts_service = EdgeTTSService()
