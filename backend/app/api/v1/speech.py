import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from app.schemas.speech import (
    STTModelInfoResponse,
    SynthesizeRequest,
    TTSModelInfoResponse,
    TranscribeResponse,
    VoicePipelineResponse,
)
from app.speech import (
    AudioValidationError,
    ModelUnavailableError,
    SynthesisError,
    TTSModelUnavailableError,
    TTSValidationError,
    TranscriptionError,
    UnsupportedLanguageError,
    UnsupportedVoiceError,
    VoicePipelineStageError,
    stt_service,
    tts_service,
    voice_pipeline_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/speech", tags=["Speech Services"])


# ---------------------------------------------------------------------------
# Speech-to-Text (STT) Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/transcribe",
    response_model=TranscribeResponse,
    summary="Transcribe Multilingual Audio",
    description="Transcribe uploaded audio file into original-language text using Whisper STT.",
    status_code=status.HTTP_200_OK,
)
async def transcribe_audio(
    file: UploadFile = File(..., description="Audio file to transcribe (e.g. .wav, .mp3, .ogg, .m4a, .webm)"),
    language: Optional[str] = Form(
        None,
        description="Optional ISO language code override (e.g. 'mr', 'hi', 'en', 'gu', 'kn', 'ta', 'te'). Omit for automatic detection.",
    ),
) -> TranscribeResponse:
    """
    Receive multipart/form-data audio file, validate payload, and return transcribed text.
    """
    try:
        # Read raw uploaded bytes
        audio_bytes = await file.read()
        filename = file.filename or "audio.wav"

        # Execute transcription through STT service
        return await stt_service.transcribe(
            audio_bytes=audio_bytes,
            filename=filename,
            language=language,
        )

    except AudioValidationError as exc:
        msg = str(exc)
        if "exceeds maximum allowed limit" in msg:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=msg,
            ) from exc
        elif "Unsupported audio file format" in msg:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=msg,
            ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=msg,
            ) from exc

    except ModelUnavailableError as exc:
        logger.error(f"STT Model unavailable: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Speech-to-Text engine is currently unavailable. Please verify model weights.",
        ) from exc

    except TranscriptionError as exc:
        logger.error(f"STT Transcription failure: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to transcribe audio payload. The audio may be unreadable or corrupt.",
        ) from exc

    except Exception as exc:
        logger.error(f"Unexpected error in /speech/transcribe: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred while processing the audio request.",
        ) from exc


@router.get(
    "/info",
    response_model=STTModelInfoResponse,
    summary="Get STT Model Metadata",
    description="Retrieve information about active Whisper model, device, compute precision, and supported languages.",
)
async def get_stt_info() -> STTModelInfoResponse:
    """Return model runtime info and supported language list."""
    return stt_service.get_model_info()


# ---------------------------------------------------------------------------
# Text-to-Speech (TTS) Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/synthesize",
    summary="Synthesize Multilingual Speech Audio",
    description="Convert natural or code-mixed Indian-language text into high-quality spoken audio stream/file.",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "content": {"audio/mpeg": {}},
            "description": "Binary MP3 audio stream of the synthesized speech with metadata headers.",
        },
        400: {"description": "Invalid input text, empty payload, or unsupported language."},
        500: {"description": "Synthesis generation failure."},
        503: {"description": "TTS engine or network provider unavailable."},
    },
)
async def synthesize_speech(request: SynthesizeRequest) -> Response:
    """
    Accept text and target language/voice, synthesize neural audio, and return MP3 stream with metadata headers.
    """
    try:
        audio_bytes, meta = await tts_service.synthesize(
            text=request.text,
            language=request.language,
            voice=request.voice,
            gender=request.gender,
            rate=request.rate,
            pitch=request.pitch,
        )

        headers = {
            "Content-Disposition": "inline; filename=\"speech.mp3\"",
            "X-Speech-Language": str(meta.get("language", "")),
            "X-Speech-Voice": str(meta.get("voice", "")),
            "X-Speech-Engine": str(meta.get("engine", "")),
            "X-Speech-Processing-Time": f"{meta.get('processing_time', 0.0):.3f}",
            "X-Speech-Audio-Length": str(meta.get("audio_bytes_length", 0)),
        }

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers=headers,
        )

    except (TTSValidationError, UnsupportedLanguageError, UnsupportedVoiceError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except TTSModelUnavailableError as exc:
        logger.error(f"TTS service unavailable: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Text-to-Speech service is currently unavailable. Please verify connection.",
        ) from exc

    except SynthesisError as exc:
        logger.error(f"TTS synthesis failure: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to synthesize speech audio from the provided text.",
        ) from exc

    except Exception as exc:
        logger.error(f"Unexpected error in /speech/synthesize: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal server error occurred while synthesizing speech.",
        ) from exc


@router.get(
    "/tts-info",
    response_model=TTSModelInfoResponse,
    summary="Get TTS Engine Metadata",
    description="Retrieve information about active Text-to-Speech engine, default voice/language, and supported voices.",
)
async def get_tts_info() -> TTSModelInfoResponse:
    """Return TTS engine runtime info, supported Indian languages, and voice mappings."""
    return tts_service.get_model_info()


# ---------------------------------------------------------------------------
# End-to-End Voice Pipeline Endpoints (Audio -> STT -> Brain -> TTS -> Audio)
# ---------------------------------------------------------------------------


@router.post(
    "/voice",
    response_model=VoicePipelineResponse,
    summary="End-to-End Voice Pipeline (STT -> Brain -> TTS)",
    description="Stream user audio, transcribe via STT, generate response with ORCA Brain (Qwen3-8B), and return synthesized audio response with stage latency breakdown.",
    status_code=status.HTTP_200_OK,
)
async def process_voice_turn(
    file: UploadFile = File(..., description="Audio file of spoken user query (e.g. .wav, .mp3, .ogg, .m4a, .webm)"),
    session_id: Optional[str] = Form(None, description="Optional conversation session ID for multi-turn history"),
    language: Optional[str] = Form(None, description="Optional language hint or override"),
) -> VoicePipelineResponse:
    """
    Execute full pipeline:
    1. STT: transcribe audio to text in spoken language
    2. Brain: generate conversational/actionable response with session memory
    3. TTS: synthesize response audio in appropriate language
    """
    try:
        audio_bytes = await file.read()
        filename = file.filename or "voice_input.wav"

        return await voice_pipeline_service.process_voice(
            audio_bytes=audio_bytes,
            filename=filename,
            session_id=session_id,
            language=language,
        )

    except VoicePipelineStageError as exc:
        logger.error(f"Voice Pipeline failure at stage='{exc.stage}': {exc.message}")
        raise HTTPException(
            status_code=exc.status_code,
            detail={
                "stage": exc.stage,
                "error": exc.message,
                "message": exc.detail,
            },
            headers={"X-Pipeline-Failed-Stage": exc.stage},
        ) from exc

    except Exception as exc:
        logger.error(f"Unexpected error in /speech/voice: {exc}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "stage": "pipeline",
                "error": "Unexpected pipeline error",
                "message": str(exc),
            },
            headers={"X-Pipeline-Failed-Stage": "pipeline"},
        ) from exc
