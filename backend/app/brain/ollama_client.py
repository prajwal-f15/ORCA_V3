import logging
from typing import Any, Dict, List, Optional
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)


class OllamaServiceError(Exception):
    """Raised when the Ollama backend service is unreachable or encounters an error."""

    def __init__(self, message: str = "Ollama service is currently unavailable", status_code: int = 503):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class OllamaClient:
    """Async client communicating with the local Ollama API with optimized options."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.OLLAMA_MODEL
        self.timeout = timeout or settings.OLLAMA_TIMEOUT_SECONDS
        self.default_keep_alive = settings.OLLAMA_KEEP_ALIVE
        self.default_think = settings.OLLAMA_THINK
        self.default_num_predict = settings.OLLAMA_NUM_PREDICT
        self.default_num_ctx = settings.OLLAMA_NUM_CTX
        self.default_temperature = settings.OLLAMA_TEMPERATURE

    def _build_effective_options(self, custom_options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge client default optimization options with caller overrides."""
        opts: Dict[str, Any] = {
            "num_predict": self.default_num_predict,
            "num_ctx": self.default_num_ctx,
            "temperature": self.default_temperature,
            "top_p": 0.8,
        }
        if custom_options:
            opts.update(custom_options)
        return opts

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        format: Optional[str] = None,
        think: Optional[bool] = None,
        keep_alive: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Send a direct generate request to the Ollama /api/generate endpoint.
        Used for fast structured JSON generation without chat template overhead or thinking blocks.
        """
        target_model = model or self.model
        effective_think = self.default_think if think is None else think
        effective_keep_alive = keep_alive or self.default_keep_alive
        effective_options = self._build_effective_options(options)

        payload: Dict[str, Any] = {
            "model": target_model,
            "prompt": prompt,
            "stream": False,
            "think": effective_think,
            "keep_alive": effective_keep_alive,
            "options": effective_options,
        }
        if system:
            payload["system"] = system
        if format:
            payload["format"] = format

        url = f"{self.base_url}/api/generate"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data: Dict[str, Any] = response.json()
                return data.get("response", "")
        except httpx.ConnectError as exc:
            raise OllamaServiceError(
                f"Failed to connect to Ollama server at {self.base_url}. Please ensure Ollama is running."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaServiceError(
                f"Request to Ollama timed out after {self.timeout} seconds."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaServiceError(
                f"Ollama server returned error status {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except Exception as exc:
            raise OllamaServiceError(
                f"Unexpected error communicating with Ollama: {str(exc)}"
            ) from exc

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        format: Optional[str] = None,
        think: Optional[bool] = None,
        keep_alive: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Send a chat request to the Ollama /api/chat endpoint with thinking suppression and token limits.
        """
        target_model = model or self.model
        effective_think = self.default_think if think is None else think
        effective_keep_alive = keep_alive or self.default_keep_alive
        effective_options = self._build_effective_options(options)

        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": False,
            "think": effective_think,
            "keep_alive": effective_keep_alive,
            "options": effective_options,
        }
        if format:
            payload["format"] = format

        url = f"{self.base_url}/api/chat"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data: Dict[str, Any] = response.json()

                message = data.get("message", {})
                content = message.get("content", "")
                thinking = message.get("thinking", "")
                if content:
                    return content
                elif thinking:
                    return thinking
                return ""

        except httpx.ConnectError as exc:
            raise OllamaServiceError(
                f"Failed to connect to Ollama server at {self.base_url}. Please ensure Ollama is running."
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaServiceError(
                f"Request to Ollama timed out after {self.timeout} seconds."
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaServiceError(
                f"Ollama server returned error status {exc.response.status_code}: {exc.response.text}"
            ) from exc
        except Exception as exc:
            raise OllamaServiceError(
                f"Unexpected error communicating with Ollama: {str(exc)}"
            ) from exc
