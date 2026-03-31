from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.llm.gemini_client import GeminiClient, GeminiClientError


FALLBACK_POEM = "\n".join(
    [
        "Đường dài mỏi bước đừng lo,",
        "Vững tâm từng việc nhỏ cho nhẹ lòng.",
        "Khó khăn rồi cũng qua sông,",
        "Bền chí hôm nay sáng trong ngày mai.",
    ]
)


@dataclass(frozen=True)
class PoemServiceConfig:
    enabled: bool
    prompt_path: str


class PoemService:
    def __init__(self, *, cfg: PoemServiceConfig, gemini: GeminiClient) -> None:
        self._cfg = cfg
        self._gemini = gemini

    def make_encouragement_poem(self, *, context: str = "") -> str | None:
        if not self._cfg.enabled:
            return None
        prompt_file = Path(self._cfg.prompt_path)
        if not prompt_file.exists():
            # Keep bot resilient even when prompt missing
            return FALLBACK_POEM
        prompt_md = prompt_file.read_text(encoding="utf-8")
        prompt = prompt_md.replace("{context}", (context or "").strip())
        try:
            raw = self._gemini.generate_text(prompt=prompt)
        except GeminiClientError:
            return FALLBACK_POEM
        poem = _normalize_poem_4_lines(raw)
        return poem or FALLBACK_POEM


def _normalize_poem_4_lines(text: str) -> str:
    """
    Best-effort normalization: keep first 4 non-empty lines.
    We rely on prompt to enforce luc bat; validation here focuses on line count.
    """
    if not text:
        return ""
    lines = [ln.strip() for ln in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [ln for ln in lines if ln]
    if len(lines) < 4:
        return ""
    lines = lines[:4]
    return "\n".join(lines).strip()

