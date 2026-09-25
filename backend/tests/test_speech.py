import io
import math
import struct
import unittest
import wave
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.schemas.speech import STTModelInfoResponse, TranscribeResponse
from app.speech.stt import (
    AudioValidationError,
    FasterWhisperSTTService,
    ModelUnavailableError,
    TranscriptionError,
    WHISPER_SUPPORTED_LANGUAGES,
    normalize_stt_language,
)


def generate_synthetic_wav_bytes(duration_seconds: float = 1.0, sample_rate: int = 16000) -> bytes:
    """Generate a minimal valid mono 16-bit PCM WAV in memory."""
    buf = io.BytesIO()
    num_samples = int(sample_rate * duration_seconds)
    frequency = 440.0  # A4 tone

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


class TestSpeechServiceUnit(unittest.TestCase):
    """Unit tests for FasterWhisperSTTService validation and error handling."""

    def setUp(self):
        self.service = FasterWhisperSTTService()

    def test_empty_audio_validation(self):
        with self.assertRaises(AudioValidationError) as ctx:
            self.service.validate_audio(b"", "empty.wav")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_corrupt_short_audio_validation(self):
        with self.assertRaises(AudioValidationError) as ctx:
            self.service.validate_audio(b"RIFFshort", "corrupt.wav")
        self.assertIn("insufficient header", str(ctx.exception).lower())

    def test_unsupported_format_validation(self):
        valid_bytes = b"0" * 100
        with self.assertRaises(AudioValidationError) as ctx:
            self.service.validate_audio(valid_bytes, "document.pdf")
        self.assertIn("unsupported audio file format", str(ctx.exception).lower())

    def test_supported_languages_list(self):
        info = self.service.get_model_info()
        self.assertIsInstance(info, STTModelInfoResponse)
        self.assertEqual(info.engine, "faster-whisper")
        for lang in ["mr", "hi", "en", "gu", "kn", "ml", "ta", "te", "bn"]:
            self.assertIn(lang, info.supported_languages)
        # Verify unsupported languages are not falsely claimed
        self.assertNotIn("kok", info.supported_languages)
        self.assertNotIn("or", info.supported_languages)

    def test_stt_language_normalization(self):
        test_cases = [
            ("mr-IN", "mr"),
            ("Marathi", "mr"),
            ("hi-in", "hi"),
            ("Hindi", "hi"),
            ("en-US", "en"),
            ("en-IN", "en"),
            ("english", "en"),
            ("gu-in", "gu"),
            ("gujarati", "gu"),
            ("ta-IN", "ta"),
            ("tamil", "ta"),
            ("te-IN", "te"),
            ("telugu", "te"),
            ("kn-in", "kn"),
            ("kannada", "kn"),
            ("ml-in", "ml"),
            ("malayalam", "ml"),
            ("bn-IN", "bn"),
            ("bengali", "bn"),
            ("ur-in", "ur"),
            ("urdu", "ur"),
            ("pa-in", "pa"),
            ("punjabi", "pa"),
        ]
        for input_val, expected_val in test_cases:
            self.assertEqual(normalize_stt_language(input_val), expected_val)

        # None / empty / unsupported fallback to None for auto-detection
        self.assertIsNone(normalize_stt_language(None))
        self.assertIsNone(normalize_stt_language(""))
        self.assertIsNone(normalize_stt_language("   "))
        self.assertIsNone(normalize_stt_language("unsupported_xyz_lang"))
        self.assertIsNone(normalize_stt_language("kok"))  # Konkani not supported by Whisper model
        self.assertIsNone(normalize_stt_language("or"))   # Odia not supported by Whisper model


class TestSpeechAPIIntegration(unittest.TestCase):
    """Integration tests for FastAPI /api/v1/speech endpoints."""

    def setUp(self):
        self.client = TestClient(app)
        self.synthetic_wav = generate_synthetic_wav_bytes(1.0)

    def test_get_speech_info(self):
        response = self.client.get("/api/v1/speech/info")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["engine"], "faster-whisper")
        self.assertIn("supported_languages", data)
        self.assertIn("mr", data["supported_languages"])
        self.assertIn("hi", data["supported_languages"])

    def test_transcribe_empty_file_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/transcribe",
            files={"file": ("empty.wav", b"", "audio/wav")},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.json()["detail"].lower())

    def test_transcribe_unsupported_file_returns_415(self):
        response = self.client.post(
            "/api/v1/speech/transcribe",
            files={"file": ("payload.exe", b"0" * 100, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 415)
        self.assertIn("unsupported", response.json()["detail"].lower())

    def test_transcribe_corrupt_file_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/transcribe",
            files={"file": ("corrupt.wav", b"RIFF123", "audio/wav")},
        )
        self.assertEqual(response.status_code, 400)

    @patch("app.speech.stt.FasterWhisperSTTService._get_model")
    def test_transcribe_marathi_mocked(self, mock_get_model):
        """Verify handling of Marathi fishing query."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = " मला आज Mumbai जवळ fishing ला जायचं आहे."
        
        mock_info = MagicMock()
        mock_info.language = "mr"
        mock_info.language_probability = 0.9421
        mock_info.duration = 3.5

        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        mock_get_model.return_value = mock_model

        response = self.client.post(
            "/api/v1/speech/transcribe",
            files={"file": ("marathi_sample.wav", self.synthetic_wav, "audio/wav")},
            data={"language": "mr"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["text"], "मला आज Mumbai जवळ fishing ला जायचं आहे.")
        self.assertEqual(data["language"], "mr")
        self.assertAlmostEqual(data["confidence"], 0.9421, places=4)
        self.assertEqual(data["duration"], 3.5)
        self.assertGreaterEqual(data["processing_time"], 0.0)

    @patch("app.speech.stt.FasterWhisperSTTService._get_model")
    def test_transcribe_hindi_code_mixed_mocked(self, mock_get_model):
        """Verify Hindi + English code-mixed marine query."""
        mock_model = MagicMock()
        mock_segment = MagicMock()
        mock_segment.text = " Mumbai se Goa ka safe route dikhao."
        
        mock_info = MagicMock()
        mock_info.language = "hi"
        mock_info.language_probability = 0.9150
        mock_info.duration = 2.8

        mock_model.transcribe.return_value = ([mock_segment], mock_info)
        mock_get_model.return_value = mock_model

        response = self.client.post(
            "/api/v1/speech/transcribe",
            files={"file": ("hindi_route.wav", self.synthetic_wav, "audio/wav")},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["text"], "Mumbai se Goa ka safe route dikhao.")
        self.assertEqual(data["language"], "hi")

    @patch("app.speech.stt.FasterWhisperSTTService._get_model")
    def test_transcribe_model_unavailable_returns_503(self, mock_get_model):
        mock_get_model.side_effect = ModelUnavailableError("Weights missing")
        response = self.client.post(
            "/api/v1/speech/transcribe",
            files={"file": ("sample.wav", self.synthetic_wav, "audio/wav")},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("unavailable", response.json()["detail"].lower())

    @patch("app.speech.stt.FasterWhisperSTTService._get_model")
    def test_transcribe_runtime_inference_error_returns_500(self, mock_get_model):
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("Internal CTranslate2 decoder crash")
        mock_get_model.return_value = mock_model

        response = self.client.post(
            "/api/v1/speech/transcribe",
            files={"file": ("sample.wav", self.synthetic_wav, "audio/wav")},
        )
        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to transcribe audio payload", response.json()["detail"])
        self.assertNotIn("CTranslate2 decoder crash", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
