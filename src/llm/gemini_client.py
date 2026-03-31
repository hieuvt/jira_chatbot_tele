from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, parse, request


@dataclass(frozen=True)
class GeminiConfig:
    base_url: str
    api_version: str
    model: str
    api_key: str
    timeout_seconds: int = 20


class GeminiClientError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


class GeminiClient:
    def __init__(self, cfg: GeminiConfig) -> None:
        self._cfg = cfg

    def generate_text(self, *, prompt: str) -> str:
        """
        Call Gemini generateContent and return concatenated text.
        Uses API key query param to avoid dependency on google SDK.
        """
        if not self._cfg.api_key.strip():
            raise GeminiClientError(code="GEMINI_MISSING_API_KEY", message="Gemini API key is empty.")
        base = (self._cfg.base_url or "").rstrip("/")
        ver = (self._cfg.api_version or "").strip().strip("/")
        model = (self._cfg.model or "").strip()
        if not base or not ver or not model:
            raise GeminiClientError(code="GEMINI_BAD_CONFIG", message="Gemini base_url/api_version/model missing.")

        path = f"/{ver}/models/{parse.quote(model)}:generateContent"
        url = f"{base}{path}?key={parse.quote(self._cfg.api_key)}"

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.9,
                "topP": 0.95,
                "maxOutputTokens": 256,
            },
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url=url,
            method="POST",
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        try:
            with request.urlopen(req, timeout=float(self._cfg.timeout_seconds)) as resp:
                raw = resp.read()
        except error.HTTPError as exc:
            status = getattr(exc, "code", None)
            try:
                detail = exc.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            raise GeminiClientError(
                code="GEMINI_HTTP_ERROR",
                message=f"Gemini HTTP error status={status} detail={detail[:500]}",
                status=int(status) if status is not None else None,
            ) from exc
        except Exception as exc:
            raise GeminiClientError(code="GEMINI_NETWORK_ERROR", message=str(exc)) from exc

        try:
            data = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:
            raise GeminiClientError(code="GEMINI_INVALID_JSON", message="Gemini response is not valid JSON.") from exc

        # Expected shape:
        # { candidates: [ { content: { parts: [ { text: "..." } ] } } ] }
        text_parts: list[str] = []
        try:
            candidates = data.get("candidates", [])
            if isinstance(candidates, list) and candidates:
                content = candidates[0].get("content", {}) if isinstance(candidates[0], dict) else {}
                parts = content.get("parts", []) if isinstance(content, dict) else []
                if isinstance(parts, list):
                    for p in parts:
                        if isinstance(p, dict) and isinstance(p.get("text"), str):
                            text_parts.append(p["text"])
        except Exception:
            text_parts = []

        merged = "\n".join([x.strip("\n") for x in text_parts if str(x).strip()])
        if not merged.strip():
            raise GeminiClientError(code="GEMINI_EMPTY_RESPONSE", message="Gemini returned empty text.")
        return merged.strip()

