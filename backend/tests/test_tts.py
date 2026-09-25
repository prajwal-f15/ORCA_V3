import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app
from app.schemas.speech import TTSModelInfoResponse
from app.speech.tts import (
    EDGE_TTS_INDIAN_VOICE_MAP,
    EdgeTTSService,
    SynthesisError,
    TTSModelUnavailableError,
    TTSValidationError,
    UnsupportedLanguageError,
    UnsupportedVoiceError,
)


class TestTTSServiceUnit(unittest.TestCase):
    """Unit tests for EdgeTTSService input validation, voice resolution, and configuration."""

    def setUp(self):
        self.service = EdgeTTSService()

    def test_empty_text_validation(self):
        with self.assertRaises(TTSValidationError) as ctx:
            self.service.validate_request(text="")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_whitespace_only_text_validation(self):
        with self.assertRaises(TTSValidationError) as ctx:
            self.service.validate_request(text="    \n\t  ")
        self.assertIn("empty", str(ctx.exception).lower())

    def test_oversized_text_validation(self):
        oversized = "मराठी " * 1000  # > 2000 chars
        with self.assertRaises(TTSValidationError) as ctx:
            self.service.validate_request(text=oversized)
        self.assertIn("exceeds maximum allowed limit", str(ctx.exception).lower())

    def test_invalid_rate_format(self):
        with self.assertRaises(TTSValidationError) as ctx:
            self.service.validate_request(text="नमस्कार", rate="fast")
        self.assertIn("invalid rate parameter", str(ctx.exception).lower())

    def test_invalid_pitch_format(self):
        with self.assertRaises(TTSValidationError) as ctx:
            self.service.validate_request(text="नमस्कार", pitch="high")
        self.assertIn("invalid pitch parameter", str(ctx.exception).lower())

    def test_unsupported_language_rejection(self):
        with self.assertRaises(UnsupportedLanguageError) as ctx:
            self.service.validate_request(text="Some text", language="xyz")
        self.assertIn("unsupported language code", str(ctx.exception).lower())

    def test_engine_missing_languages_rejection(self):
        # Konkani and Odia are not in Edge TTS catalog
        with self.assertRaises(UnsupportedLanguageError) as ctx_kok:
            self.service.validate_request(text="Konkani test", language="kok")
        self.assertIn("kok", str(ctx_kok.exception).lower())

        with self.assertRaises(UnsupportedLanguageError) as ctx_or:
            self.service.validate_request(text="Odia test", language="or")
        self.assertIn("or", str(ctx_or.exception).lower())

    def test_valid_voice_language_combination(self):
        # Marathi with valid Marathi voices
        lang, voice = self.service.validate_request(text="नमस्कार", language="mr", voice="mr-IN-AarohiNeural")
        self.assertEqual(lang, "mr")
        self.assertEqual(voice, "mr-IN-AarohiNeural")

        lang, voice = self.service.validate_request(text="नमस्कार", language="mr", voice="mr-IN-ManoharNeural")
        self.assertEqual(lang, "mr")
        self.assertEqual(voice, "mr-IN-ManoharNeural")

        # English with expressive voice
        lang, voice = self.service.validate_request(text="Hello", language="en", voice="en-IN-NeerjaExpressiveNeural")
        self.assertEqual(lang, "en")
        self.assertEqual(voice, "en-IN-NeerjaExpressiveNeural")

    def test_invalid_voice_language_combination(self):
        # Requesting Hindi voice with Marathi language
        with self.assertRaises(UnsupportedVoiceError) as ctx:
            self.service.validate_request(text="नमस्कार", language="mr", voice="hi-IN-SwaraNeural")
        self.assertIn("hi-IN-SwaraNeural", str(ctx.exception))
        self.assertIn("not a valid voice for language 'mr'", str(ctx.exception))

        # Requesting Marathi voice with English language
        with self.assertRaises(UnsupportedVoiceError) as ctx:
            self.service.validate_request(text="Hello", language="en", voice="mr-IN-AarohiNeural")
        self.assertIn("mr-IN-AarohiNeural", str(ctx.exception))

        # Requesting non-existent voice
        with self.assertRaises(UnsupportedVoiceError) as ctx:
            self.service.validate_request(text="Hello", language="en", voice="fake-voice-id")
        self.assertIn("fake-voice-id", str(ctx.exception))

    def test_language_normalization(self):
        cases = [
            ("mr", "mr"),
            ("mr-IN", "mr"),
            ("Marathi", "mr"),
            ("hi", "hi"),
            ("hi-in", "hi"),
            ("Hindi", "hi"),
            ("en", "en"),
            ("en-IN", "en"),
            ("gu", "gu"),
            ("Gujarati", "gu"),
            ("ta", "ta"),
            ("Tamil", "ta"),
            ("te", "te"),
            ("Telugu", "te"),
            ("kn", "kn"),
            ("Kannada", "kn"),
            ("ml", "ml"),
            ("Malayalam", "ml"),
            ("bn", "bn"),
            ("Bengali", "bn"),
            ("ur", "ur"),
            ("Urdu", "ur"),
        ]
        for input_lang, expected_lang in cases:
            lang, voice = self.service.validate_request("Test speech text", language=input_lang)
            self.assertEqual(lang, expected_lang)
            self.assertTrue(voice.startswith(f"{expected_lang}-IN-"))

    def test_voice_resolution_gender(self):
        # Marathi
        self.assertEqual(
            self.service._resolve_voice("mr", gender="female"),
            "mr-IN-AarohiNeural"
        )
        self.assertEqual(
            self.service._resolve_voice("mr", gender="male"),
            "mr-IN-ManoharNeural"
        )
        # Hindi
        self.assertEqual(
            self.service._resolve_voice("hi", gender="female"),
            "hi-IN-SwaraNeural"
        )
        self.assertEqual(
            self.service._resolve_voice("hi", gender="male"),
            "hi-IN-MadhurNeural"
        )
        # English
        self.assertEqual(
            self.service._resolve_voice("en", gender="male"),
            "en-IN-PrabhatNeural"
        )
        self.assertEqual(
            self.service._resolve_voice("en", gender="female"),
            "en-IN-NeerjaNeural"
        )

    def test_validate_request_gender_selection(self):
        # Verify validate_request propagates gender properly
        _, female_voice = self.service.validate_request("नमस्कार", language="mr", gender="female")
        self.assertEqual(female_voice, "mr-IN-AarohiNeural")

        _, male_voice = self.service.validate_request("नमस्कार", language="mr", gender="male")
        self.assertEqual(male_voice, "mr-IN-ManoharNeural")

        _, male_hi_voice = self.service.validate_request("नमस्ते", language="hi", gender="male")
        self.assertEqual(male_hi_voice, "hi-IN-MadhurNeural")

    def test_get_model_info(self):
        info = self.service.get_model_info()
        self.assertIsInstance(info, TTSModelInfoResponse)
        self.assertEqual(info.engine, "edge-tts")
        self.assertEqual(info.default_language, "mr")
        for expected_lang in ["mr", "hi", "en", "gu", "ta", "te", "kn", "ml", "bn", "ur"]:
            self.assertIn(expected_lang, info.supported_languages)
            self.assertIn(expected_lang, info.available_voices)


class TestTTSAPIIntegration(unittest.TestCase):
    """Integration tests for FastAPI /api/v1/speech/synthesize and /api/v1/speech/tts-info."""

    def setUp(self):
        self.client = TestClient(app)

    def test_get_tts_info_endpoint(self):
        response = self.client.get("/api/v1/speech/tts-info")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["engine"], "edge-tts")
        self.assertIn("supported_languages", data)
        self.assertIn("mr", data["supported_languages"])
        self.assertIn("hi", data["supported_languages"])
        self.assertIn("available_voices", data)
        self.assertIn("mr-IN-AarohiNeural", data["available_voices"]["mr"])

    def test_synthesize_empty_text_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "   ", "language": "mr"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("empty", response.json()["detail"].lower())

    def test_synthesize_oversized_text_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "A" * 2500, "language": "en"},
        )
        self.assertIn(response.status_code, (400, 422))

    def test_synthesize_unsupported_language_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "Test text", "language": "nonexistent_lang"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported language", response.json()["detail"].lower())

    def test_synthesize_unsupported_konkani_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "Boro dis", "language": "kok"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported language", response.json()["detail"].lower())

    def test_synthesize_unsupported_odia_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "Namaskar", "language": "or"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported language", response.json()["detail"].lower())

    def test_synthesize_invalid_voice_returns_400(self):
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "नमस्कार", "language": "mr", "voice": "hi-IN-SwaraNeural"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a valid voice for language 'mr'", response.json()["detail"])

    @patch("app.speech.tts.EdgeTTSService.synthesize")
    def test_synthesize_marathi_success_mocked(self, mock_synth):
        mock_audio = b"\xff\xfb\x90\x44" + (b"\x00" * 200)  # fake MP3
        mock_synth.return_value = (
            mock_audio,
            {
                "language": "mr",
                "voice": "mr-IN-AarohiNeural",
                "engine": "edge-tts",
                "audio_bytes_length": len(mock_audio),
                "audio_format": "audio/mpeg",
                "processing_time": 0.452,
                "character_count": 42,
            },
        )

        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "Prajwal, आज समुद्राची परिस्थिती तपासतो.", "language": "mr"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "audio/mpeg")
        self.assertEqual(response.headers["x-speech-language"], "mr")
        self.assertEqual(response.headers["x-speech-voice"], "mr-IN-AarohiNeural")
        self.assertEqual(response.headers["x-speech-engine"], "edge-tts")
        self.assertEqual(response.headers["x-speech-processing-time"], "0.452")
        self.assertEqual(response.content, mock_audio)

    @patch("app.speech.tts.EdgeTTSService.synthesize")
    def test_synthesize_gender_male_mocked(self, mock_synth):
        mock_audio = b"\xff\xfb\x90\x44" + (b"\x00" * 200)
        mock_synth.return_value = (
            mock_audio,
            {
                "language": "mr",
                "voice": "mr-IN-ManoharNeural",
                "engine": "edge-tts",
                "audio_bytes_length": len(mock_audio),
                "audio_format": "audio/mpeg",
                "processing_time": 0.410,
                "character_count": 25,
            },
        )

        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "नमस्कार Prajwal", "language": "mr", "gender": "male"},
        )

        self.assertEqual(response.status_code, 200)
        mock_synth.assert_called_once()
        call_kwargs = mock_synth.call_args.kwargs
        self.assertEqual(call_kwargs.get("gender"), "male")
        self.assertEqual(response.headers["x-speech-voice"], "mr-IN-ManoharNeural")

    @patch("app.speech.tts.EdgeTTSService.synthesize")
    def test_synthesize_service_unavailable_returns_503(self, mock_synth):
        mock_synth.side_effect = TTSModelUnavailableError("Connection dropped")
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "Testing connectivity", "language": "en"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertIn("unavailable", response.json()["detail"].lower())

    @patch("app.speech.tts.EdgeTTSService.synthesize")
    def test_synthesize_runtime_failure_returns_500(self, mock_synth):
        mock_synth.side_effect = SynthesisError("Decoder error")
        response = self.client.post(
            "/api/v1/speech/synthesize",
            json={"text": "Testing failure", "language": "hi"},
        )
        self.assertEqual(response.status_code, 500)
        self.assertIn("Failed to synthesize speech audio", response.json()["detail"])
        self.assertNotIn("Decoder error", response.json()["detail"])


class TestTTSLiveGeneration(unittest.IsolatedAsyncioTestCase):
    """Live TTS synthesis tests against real audio generation for all supported Indian languages."""

    async def asyncSetUp(self):
        self.service = EdgeTTSService()

    async def test_live_marathi_synthesis(self):
        text = "Prajwal, आज समुद्राची परिस्थिती तपासतो. Mumbai जवळ वारे 12 knots आहेत."
        audio, meta = await self.service.synthesize(text=text, language="mr")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "mr")
        self.assertEqual(meta["voice"], "mr-IN-AarohiNeural")
        self.assertGreater(meta["processing_time"], 0.0)

    async def test_live_hindi_synthesis(self):
        text = "नमस्ते Prajwal, आज समुद्र में मछली पकड़ने की स्थिति अच्छी है."
        audio, meta = await self.service.synthesize(text=text, language="hi")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "hi")
        self.assertEqual(meta["voice"], "hi-IN-SwaraNeural")

    async def test_live_english_synthesis(self):
        text = "Captain Prajwal, ocean safety checks completed. Wave height is 1.2 meters."
        audio, meta = await self.service.synthesize(text=text, language="en")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "en")
        self.assertEqual(meta["voice"], "en-IN-NeerjaNeural")

    async def test_live_gujarati_synthesis(self):
        text = "નમસ્તે Prajwal, આજે દરિયામાં માછીમારી માટે હવામાન સારું છે."
        audio, meta = await self.service.synthesize(text=text, language="gu")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "gu")
        self.assertEqual(meta["voice"], "gu-IN-DhwaniNeural")

    async def test_live_tamil_synthesis(self):
        text = "வணக்கம் Prajwal, இன்று கடல் நிலை பாதுகாப்பாக உள்ளது."
        audio, meta = await self.service.synthesize(text=text, language="ta")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "ta")
        self.assertEqual(meta["voice"], "ta-IN-PallaviNeural")

    async def test_live_telugu_synthesis(self):
        text = "నమస్కారం Prajwal, ఈరోజు సముద్రంలో చేపల వేటకు పరిస్థితులు బాగున్నాయి."
        audio, meta = await self.service.synthesize(text=text, language="te")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "te")
        self.assertEqual(meta["voice"], "te-IN-ShrutiNeural")

    async def test_live_kannada_synthesis(self):
        text = "ನಮಸ್ಕಾರ Prajwal, ಇಂದು ಸಮುದ್ರದಲ್ಲಿ ಮೀನುಗಾರಿಕೆಗೆ ಹವಾಮಾನ ಉತ್ತಮವಾಗಿದೆ."
        audio, meta = await self.service.synthesize(text=text, language="kn")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "kn")
        self.assertEqual(meta["voice"], "kn-IN-SapnaNeural")

    async def test_live_malayalam_synthesis(self):
        text = "നമസ്കാരം Prajwal, ഇന്ന് കടലിൽ മത്സ്യബന്ധനത്തിന് അനുകൂലമായ കാലാവസ്ഥയാണ്."
        audio, meta = await self.service.synthesize(text=text, language="ml")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "ml")
        self.assertEqual(meta["voice"], "ml-IN-SobhanaNeural")

    async def test_live_bengali_synthesis(self):
        text = "নমস্কার Prajwal, আজ সমুদ্রে মাছ ধরার আবহাওয়া খুব ভালো."
        audio, meta = await self.service.synthesize(text=text, language="bn")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "bn")
        self.assertEqual(meta["voice"], "bn-IN-TanishaaNeural")

    async def test_live_urdu_synthesis(self):
        text = "سلام Prajwal, آج سمندر میں مچھلی کے شکار کے حالات بہتر ہیں."
        audio, meta = await self.service.synthesize(text=text, language="ur")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "ur")
        self.assertEqual(meta["voice"], "ur-IN-GulNeural")

    async def test_live_mixed_marathi_english_synthesis(self):
        text = "आज Mumbai जवळ fishing conditions चांगल्या आहेत. Safe navigation zone activate केला आहे."
        audio, meta = await self.service.synthesize(text=text, language="mr")
        self.assertGreater(len(audio), 1000)
        self.assertEqual(meta["language"], "mr")


if __name__ == "__main__":
    unittest.main()
