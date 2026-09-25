import base64
import io
import math
import struct
import unittest
import wave
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.brain.ollama_client import OllamaServiceError
from app.main import app
from app.schemas.speech import TranscribeResponse, VoicePipelineResponse
from app.speech.pipeline import VoicePipelineService, VoicePipelineStageError
from app.speech.stt import AudioValidationError, ModelUnavailableError, TranscriptionError
from app.speech.tts import SynthesisError, TTSModelUnavailableError, TTSValidationError


def generate_synthetic_wav_bytes(duration_seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate a minimal valid mono 16-bit PCM WAV in memory for synthetic testing."""
    buf = io.BytesIO()
    num_samples = int(sample_rate * duration_seconds)
    frequency = 440.0

    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for i in range(num_samples):
            val = int(32767.0 * 0.1 * math.sin(2.0 * math.pi * frequency * i / sample_rate))
            frames.extend(struct.pack("<h", val))
        wav_file.writeframes(frames)

    return buf.getvalue()


class TestVoicePipelineUnit(unittest.IsolatedAsyncioTestCase):
    """Unit tests for VoicePipelineService error wrapping and stage isolation."""

    def setUp(self):
        self.mock_stt = MagicMock()
        self.mock_brain = MagicMock()
        self.mock_tts = MagicMock()
        self.pipeline = VoicePipelineService(
            stt=self.mock_stt,
            brain=self.mock_brain,
            tts=self.mock_tts,
        )
        self.valid_audio = generate_synthetic_wav_bytes(1.0)

    async def test_stt_validation_error_raises_stage_stt(self):
        self.mock_stt.transcribe = AsyncMock(side_effect=AudioValidationError("Audio upload is empty (0 bytes)."))
        with self.assertRaises(VoicePipelineStageError) as ctx:
            await self.pipeline.process_voice(b"", "empty.wav")
        self.assertEqual(ctx.exception.stage, "stt")
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_stt_model_unavailable_raises_stage_stt(self):
        self.mock_stt.transcribe = AsyncMock(side_effect=ModelUnavailableError("Whisper weights missing"))
        with self.assertRaises(VoicePipelineStageError) as ctx:
            await self.pipeline.process_voice(self.valid_audio, "test.wav")
        self.assertEqual(ctx.exception.stage, "stt")
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_stt_empty_transcript_raises_stage_stt(self):
        self.mock_stt.transcribe = AsyncMock(
            return_value=TranscribeResponse(text="", language="en", confidence=0.0, duration=1.0, processing_time=0.1)
        )
        with self.assertRaises(VoicePipelineStageError) as ctx:
            await self.pipeline.process_voice(self.valid_audio, "silent.wav")
        self.assertEqual(ctx.exception.stage, "stt")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("No intelligible speech", ctx.exception.message)

    async def test_brain_offline_raises_stage_brain(self):
        self.mock_stt.transcribe = AsyncMock(
            return_value=TranscribeResponse(text="Hello", language="en", confidence=0.9, duration=1.0, processing_time=0.1)
        )
        self.mock_brain.generate_response = AsyncMock(
            side_effect=OllamaServiceError("Connection refused to Ollama")
        )
        with self.assertRaises(VoicePipelineStageError) as ctx:
            await self.pipeline.process_voice(self.valid_audio, "test.wav")
        self.assertEqual(ctx.exception.stage, "brain")
        self.assertEqual(ctx.exception.status_code, 503)

    async def test_tts_failure_raises_stage_tts(self):
        self.mock_stt.transcribe = AsyncMock(
            return_value=TranscribeResponse(text="Hello", language="en", confidence=0.9, duration=1.0, processing_time=0.1)
        )
        self.mock_brain.generate_response = AsyncMock(
            return_value=("Hello Captain! Ocean is clear.", "session-123", 1)
        )
        self.mock_tts.synthesize = AsyncMock(side_effect=SynthesisError("Edge TTS connection lost"))
        with self.assertRaises(VoicePipelineStageError) as ctx:
            await self.pipeline.process_voice(self.valid_audio, "test.wav")
        self.assertEqual(ctx.exception.stage, "tts")
        self.assertEqual(ctx.exception.status_code, 500)


class TestVoicePipelineAPIIntegration(unittest.TestCase):
    """Integration tests for POST /api/v1/speech/voice with mocked downstream dependencies."""

    def setUp(self):
        self.client = TestClient(app)
        self.synthetic_wav = generate_synthetic_wav_bytes(1.0)

    @patch("app.speech.pipeline.stt_service.transcribe")
    @patch("app.speech.pipeline.brain_service.generate_response")
    @patch("app.speech.pipeline.tts_service.synthesize")
    def test_marathi_voice_flow_mocked(self, mock_tts, mock_brain, mock_stt):
        """Verify end-to-end Marathi query handling."""
        mock_stt.return_value = TranscribeResponse(
            text="आज समुद्रात मासेमारीसाठी परिस्थिती कशी आहे?",
            language="mr",
            confidence=0.95,
            duration=3.2,
            processing_time=0.45,
        )
        mock_brain.return_value = (
            "नमस्कार Prajwal, आज मुंबई जवळ समुद्राची परिस्थिती मासेमारीसाठी अनुकूल आहे. वारे 10 knots आहेत.",
            "sess-mr-001",
            1,
        )
        fake_audio_mp3 = b"\xff\xfb\x90\x44" + (b"\x12" * 500)
        mock_tts.return_value = (
            fake_audio_mp3,
            {"language": "mr", "voice": "mr-IN-AarohiNeural", "processing_time": 0.85},
        )

        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("marathi_query.wav", self.synthetic_wav, "audio/wav")},
            data={"session_id": "sess-mr-001", "language": "mr"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["session_id"], "sess-mr-001")
        self.assertEqual(data["transcript"], "आज समुद्रात मासेमारीसाठी परिस्थिती कशी आहे?")
        self.assertEqual(data["detected_language"], "mr")
        self.assertIn("मासेमारीसाठी अनुकूल आहे", data["response_text"])
        self.assertEqual(data["response_language"], "mr")
        self.assertEqual(data["audio_format"], "audio/mpeg")
        self.assertTrue(len(data["audio_base64"]) > 100)
        # Verify base64 decodes back to original bytes
        decoded_bytes = base64.b64decode(data["audio_base64"])
        self.assertEqual(decoded_bytes, fake_audio_mp3)
        # Verify metrics
        metrics = data["metrics"]
        self.assertIn("stt_duration_s", metrics)
        self.assertIn("brain_duration_s", metrics)
        self.assertIn("tts_duration_s", metrics)
        self.assertIn("total_duration_s", metrics)

    @patch("app.speech.pipeline.stt_service.transcribe")
    @patch("app.speech.pipeline.brain_service.generate_response")
    @patch("app.speech.pipeline.tts_service.synthesize")
    def test_hindi_voice_flow_mocked(self, mock_tts, mock_brain, mock_stt):
        """Verify end-to-end Hindi query handling."""
        mock_stt.return_value = TranscribeResponse(
            text="आज समुद्र में मछली पकड़ने के लिए स्थिति कैसी है?",
            language="hi",
            confidence=0.92,
            duration=2.8,
            processing_time=0.40,
        )
        mock_brain.return_value = (
            "नमस्ते Prajwal, आज समुद्र में मछली पकड़ने के लिए मौसम बहुत अच्छा है.",
            "sess-hi-002",
            1,
        )
        fake_audio_mp3 = b"\xff\xfb\x90\x44" + (b"\x34" * 400)
        mock_tts.return_value = (
            fake_audio_mp3,
            {"language": "hi", "voice": "hi-IN-SwaraNeural", "processing_time": 0.75},
        )

        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("hindi_query.wav", self.synthetic_wav, "audio/wav")},
            data={"session_id": "sess-hi-002"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["transcript"], "आज समुद्र में मछली पकड़ने के लिए स्थिति कैसी है?")
        self.assertEqual(data["detected_language"], "hi")
        self.assertEqual(data["response_language"], "hi")

    @patch("app.speech.pipeline.stt_service.transcribe")
    @patch("app.speech.pipeline.brain_service.generate_response")
    @patch("app.speech.pipeline.tts_service.synthesize")
    def test_english_voice_flow_mocked(self, mock_tts, mock_brain, mock_stt):
        """Verify end-to-end English query handling."""
        mock_stt.return_value = TranscribeResponse(
            text="How are the sea conditions for fishing today?",
            language="en",
            confidence=0.98,
            duration=2.5,
            processing_time=0.35,
        )
        mock_brain.return_value = (
            "Captain Prajwal, sea conditions are safe today with calm waters and 1 meter waves.",
            "sess-en-003",
            1,
        )
        fake_audio_mp3 = b"\xff\xfb\x90\x44" + (b"\x56" * 450)
        mock_tts.return_value = (
            fake_audio_mp3,
            {"language": "en", "voice": "en-IN-NeerjaNeural", "processing_time": 0.70},
        )

        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("english_query.wav", self.synthetic_wav, "audio/wav")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["transcript"], "How are the sea conditions for fishing today?")
        self.assertEqual(data["detected_language"], "en")

    @patch("app.speech.pipeline.stt_service.transcribe")
    @patch("app.speech.pipeline.brain_service.generate_response")
    @patch("app.speech.pipeline.tts_service.synthesize")
    def test_mixed_language_voice_flow_mocked(self, mock_tts, mock_brain, mock_stt):
        """Verify end-to-end Marathi + English code-mixed query."""
        mock_stt.return_value = TranscribeResponse(
            text="आज Mumbai जवळ fishing conditions कशा आहेत?",
            language="mr",
            confidence=0.91,
            duration=3.0,
            processing_time=0.42,
        )
        mock_brain.return_value = (
            "आज Mumbai जवळ fishing conditions चांगल्या आहेत. Safe zone active आहे.",
            "sess-mixed-004",
            1,
        )
        fake_audio_mp3 = b"\xff\xfb\x90\x44" + (b"\x78" * 480)
        mock_tts.return_value = (
            fake_audio_mp3,
            {"language": "mr", "voice": "mr-IN-AarohiNeural", "processing_time": 0.80},
        )

        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("mixed_query.wav", self.synthetic_wav, "audio/wav")},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["transcript"], "आज Mumbai जवळ fishing conditions कशा आहेत?")
        self.assertIn("fishing conditions चांगल्या आहेत", data["response_text"])

    def test_invalid_audio_format_returns_415(self):
        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("document.pdf", b"0" * 100, "application/pdf")},
        )
        self.assertEqual(response.status_code, 415)
        detail = response.json()["detail"]
        self.assertEqual(detail["stage"], "stt")
        self.assertIn("unsupported audio file format", detail["error"].lower())

    def test_empty_audio_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["stage"], "stt")
        self.assertIn("empty", detail["error"].lower())

    @patch("app.speech.pipeline.stt_service.transcribe")
    def test_stt_failure_reports_stt_stage_500(self, mock_stt):
        mock_stt.side_effect = TranscriptionError("Decoder buffer overflow")
        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("query.wav", self.synthetic_wav, "audio/wav")},
        )
        self.assertEqual(response.status_code, 500)
        detail = response.json()["detail"]
        self.assertEqual(detail["stage"], "stt")
        self.assertIn("Failed to transcribe audio payload", detail["message"])

    @patch("app.speech.pipeline.stt_service.transcribe")
    @patch("app.speech.pipeline.brain_service.generate_response")
    def test_brain_failure_reports_brain_stage_503(self, mock_brain, mock_stt):
        mock_stt.return_value = TranscribeResponse(
            text="How is weather?", language="en", confidence=0.95, duration=1.5, processing_time=0.2
        )
        mock_brain.side_effect = OllamaServiceError("Ollama daemon unreachable on port 11434")
        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("query.wav", self.synthetic_wav, "audio/wav")},
        )
        self.assertEqual(response.status_code, 503)
        detail = response.json()["detail"]
        self.assertEqual(detail["stage"], "brain")
        self.assertIn("ORCA Brain service is unreachable", detail["message"])

    @patch("app.speech.pipeline.stt_service.transcribe")
    @patch("app.speech.pipeline.brain_service.generate_response")
    @patch("app.speech.pipeline.tts_service.synthesize")
    def test_tts_failure_reports_tts_stage_500(self, mock_tts, mock_brain, mock_stt):
        mock_stt.return_value = TranscribeResponse(
            text="Hello", language="en", confidence=0.95, duration=1.0, processing_time=0.2
        )
        mock_brain.return_value = ("Hello Captain", "session-456", 1)
        mock_tts.side_effect = SynthesisError("Audio stream write failure")

        response = self.client.post(
            "/api/v1/speech/voice",
            files={"file": ("query.wav", self.synthetic_wav, "audio/wav")},
        )
        self.assertEqual(response.status_code, 500)
        detail = response.json()["detail"]
        self.assertEqual(detail["stage"], "tts")
        self.assertIn("Speech synthesis failed", detail["message"])


if __name__ == "__main__":
    unittest.main()
