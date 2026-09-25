import base64
import logging
import time
from typing import Optional

from app.brain.ollama_client import OllamaServiceError
from app.brain.service import BrainService, brain_service
from app.config import get_settings
from app.schemas.speech import VoicePipelineMetrics, VoicePipelineResponse
from app.speech.stt import (
    AudioValidationError,
    BaseSTTService,
    ModelUnavailableError,
    TranscriptionError,
    stt_service,
)
from app.speech.tts import (
    BaseTTSService,
    SynthesisError,
    TTSModelUnavailableError,
    TTSValidationError,
    UnsupportedLanguageError,
    UnsupportedVoiceError,
    tts_service,
)

logger = logging.getLogger(__name__)


class VoicePipelineStageError(Exception):
    """Exception explicitly tagging which stage in the voice pipeline encountered a failure."""

    def __init__(self, stage: str, status_code: int, message: str, detail: Optional[str] = None):
        self.stage = stage
        self.status_code = status_code
        self.message = message
        self.detail = detail or message
        super().__init__(self.detail)


class VoicePipelineService:
    """
    End-to-end voice processing pipeline connecting:
    STT (Speech-to-Text) -> ORCA Brain (Qwen3-8B) -> TTS (Text-to-Speech)
    """

    def __init__(
        self,
        stt: Optional[BaseSTTService] = None,
        brain: Optional[BrainService] = None,
        tts: Optional[BaseTTSService] = None,
    ):
        self.stt = stt or stt_service
        self.brain = brain or brain_service
        self.tts = tts or tts_service
        self.settings = get_settings()

    async def process_voice(
        self,
        audio_bytes: bytes,
        filename: Optional[str] = None,
        session_id: Optional[str] = None,
        language: Optional[str] = None,
    ) -> VoicePipelineResponse:
        """
        Execute the full voice pipeline:
        1. STT: Transcribe user's audio input.
        2. Brain: Generate natural-language answer through Qwen3-8B with session context.
        3. TTS: Synthesize answer into MP3 audio in the target language.
        """
        start_total = time.perf_counter()

        # -------------------------------------------------------------------
        # Stage 1: Speech-to-Text (STT)
        # -------------------------------------------------------------------
        start_stt = time.perf_counter()
        try:
            logger.info("Voice Pipeline: Starting STT stage...")
            transcribe_res = await self.stt.transcribe(
                audio_bytes=audio_bytes,
                filename=filename,
                language=language,
            )
            transcript = transcribe_res.text.strip() if transcribe_res.text else ""
            detected_lang = transcribe_res.language
            stt_duration = round(time.perf_counter() - start_stt, 3)

            if not transcript:
                raise VoicePipelineStageError(
                    stage="stt",
                    status_code=400,
                    message="No intelligible speech detected in the provided audio file.",
                )

            logger.info(
                f"Voice Pipeline: STT completed in {stt_duration}s | Lang: '{detected_lang}' | Transcript: '{transcript}'"
            )

        except VoicePipelineStageError:
            raise
        except AudioValidationError as exc:
            msg = str(exc)
            status_code = 413 if "exceeds maximum allowed limit" in msg else (415 if "Unsupported audio" in msg else 400)
            raise VoicePipelineStageError(stage="stt", status_code=status_code, message=msg) from exc
        except ModelUnavailableError as exc:
            raise VoicePipelineStageError(
                stage="stt",
                status_code=503,
                message="Speech-to-Text engine is currently unavailable. Please verify model weights.",
            ) from exc
        except TranscriptionError as exc:
            raise VoicePipelineStageError(
                stage="stt",
                status_code=500,
                message=f"Failed to transcribe audio payload: {exc}",
            ) from exc
        except Exception as exc:
            logger.error(f"Voice Pipeline STT unexpected error: {exc}", exc_info=True)
            raise VoicePipelineStageError(
                stage="stt",
                status_code=500,
                message=f"Unexpected error in Speech-to-Text processing: {exc}",
            ) from exc

        # -------------------------------------------------------------------
        # Stage 2: ORCA Brain (Qwen3-8B + Session Memory)
        # -------------------------------------------------------------------
        start_brain = time.perf_counter()
        try:
            logger.info(f"Voice Pipeline: Starting Brain stage with query: '{transcript}'...")
            reply_text, active_session_id, _turns = await self.brain.generate_response(
                user_message=transcript,
                session_id=session_id,
            )
            brain_duration = round(time.perf_counter() - start_brain, 3)
            logger.info(
                f"Voice Pipeline: Brain completed in {brain_duration}s | Session: {active_session_id} | Reply length: {len(reply_text)} chars"
            )

        except OllamaServiceError as exc:
            raise VoicePipelineStageError(
                stage="brain",
                status_code=503,
                message=f"ORCA Brain service is unreachable: {exc.message}",
            ) from exc
        except Exception as exc:
            logger.error(f"Voice Pipeline Brain unexpected error: {exc}", exc_info=True)
            raise VoicePipelineStageError(
                stage="brain",
                status_code=500,
                message=f"Failed to generate response from ORCA Brain: {exc}",
            ) from exc

        # -------------------------------------------------------------------
        # Stage 3: Text-to-Speech (TTS)
        # -------------------------------------------------------------------
        start_tts = time.perf_counter()
        try:
            # Determine target TTS language
            target_lang = language or detected_lang or self.settings.TTS_DEFAULT_LANGUAGE
            logger.info(f"Voice Pipeline: Starting TTS stage for language '{target_lang}'...")

            try:
                audio_mp3_bytes, meta = await self.tts.synthesize(
                    text=reply_text,
                    language=target_lang,
                )
                tts_resolved_lang = meta.get("language", target_lang)
            except UnsupportedLanguageError:
                # If detected language is not supported by TTS engine, fallback to default language
                fallback_lang = self.settings.TTS_DEFAULT_LANGUAGE
                logger.warning(
                    f"Language '{target_lang}' unsupported for TTS. Falling back to '{fallback_lang}'."
                )
                audio_mp3_bytes, meta = await self.tts.synthesize(
                    text=reply_text,
                    language=fallback_lang,
                )
                tts_resolved_lang = fallback_lang

            tts_duration = round(time.perf_counter() - start_tts, 3)
            logger.info(
                f"Voice Pipeline: TTS completed in {tts_duration}s | Size: {len(audio_mp3_bytes)} bytes | Lang: {tts_resolved_lang}"
            )

        except (TTSValidationError, UnsupportedLanguageError, UnsupportedVoiceError) as exc:
            raise VoicePipelineStageError(stage="tts", status_code=400, message=str(exc)) from exc
        except TTSModelUnavailableError as exc:
            raise VoicePipelineStageError(
                stage="tts",
                status_code=503,
                message="Text-to-Speech service is currently unavailable.",
            ) from exc
        except SynthesisError as exc:
            raise VoicePipelineStageError(
                stage="tts",
                status_code=500,
                message=f"Speech synthesis failed: {exc}",
            ) from exc
        except Exception as exc:
            logger.error(f"Voice Pipeline TTS unexpected error: {exc}", exc_info=True)
            raise VoicePipelineStageError(
                stage="tts",
                status_code=500,
                message=f"Unexpected error during speech synthesis: {exc}",
            ) from exc

        # -------------------------------------------------------------------
        # Collate Pipeline Response
        # -------------------------------------------------------------------
        total_duration = round(time.perf_counter() - start_total, 3)
        audio_b64 = base64.b64encode(audio_mp3_bytes).decode("utf-8")

        metrics = VoicePipelineMetrics(
            stt_duration_s=stt_duration,
            brain_duration_s=brain_duration,
            tts_duration_s=tts_duration,
            total_duration_s=total_duration,
        )

        return VoicePipelineResponse(
            session_id=active_session_id,
            transcript=transcript,
            detected_language=detected_lang,
            response_text=reply_text,
            response_language=tts_resolved_lang,
            audio_base64=audio_b64,
            audio_format="audio/mpeg",
            metrics=metrics,
        )


# Singleton Voice Pipeline instance
voice_pipeline_service = VoicePipelineService()
