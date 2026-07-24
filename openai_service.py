from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from questionnaire import QUESTIONS


OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAIServiceError(RuntimeError):
    pass


def _headers(api_key: str) -> dict[str, str]:
    if not api_key:
        raise OpenAIServiceError("OPENAI_API_KEY is empty.")
    return {"Authorization": f"Bearer {api_key}"}


def transcribe_audio(api_key: str, model: str, audio_path: Path) -> str:
    with httpx.Client(timeout=120) as client:
        with audio_path.open("rb") as audio_file:
            response = client.post(
                f"{OPENAI_BASE_URL}/audio/transcriptions",
                headers=_headers(api_key),
                data={"model": model, "language": "ru"},
                files={"file": (audio_path.name, audio_file, _content_type(audio_path))},
            )
    data = _json_or_raise(response)
    text = str(data.get("text", "")).strip()
    if not text:
        raise OpenAIServiceError("OpenAI returned an empty transcription.")
    return text


def generate_ceremony_script(api_key: str, model: str, answers: dict[str, str]) -> str:
    payload = {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": (
                    "Ты пишешь свадебные церемонии на русском языке. "
                    "Стиль: теплый, современный, сильный, искренний, без пошлости, без стендапа и без чрезмерного пафоса. "
                    "Не копируй конкретного публичного ведущего; используй качества лучшего ведущего: точность, бережный юмор, красивые переходы, уважение к паре и гостям. "
                    "Нужен полный текст для ведущего, который можно читать слово в слово."
                ),
            },
            {"role": "user", "content": build_generation_prompt(answers)},
        ],
    }
    with httpx.Client(timeout=180) as client:
        response = client.post(
            f"{OPENAI_BASE_URL}/responses",
            headers={**_headers(api_key), "Content-Type": "application/json"},
            json=payload,
        )
    data = _json_or_raise(response)
    text = _extract_response_text(data).strip()
    if not text:
        raise OpenAIServiceError("OpenAI returned an empty ceremony script.")
    return text


def build_generation_prompt(answers: dict[str, str]) -> str:
    lines = [
        "Составь полный текст свадебной церемонии для ведущего.",
        "",
        "Обязательные требования:",
        "- русский язык;",
        "- ведущий может читать текст дословно;",
        "- добавить ремарки в квадратных скобках: [пауза], [выход жениха], [выход невесты], [кольца], [аплодисменты];",
        "- структура: начало, приглашение жениха, выход жениха, подводка к невесте, выход невесты, история пары, блоки про жениха и невесту, предложение, клятвы, кольца, объявление мужем и женой, финал;",
        "- если клятвы будут личными, оставь красивые подводки и места для клятв;",
        "- не использовать запрещенные темы из анкеты;",
        "- длина: примерно 8-12 минут чтения;",
        "- если каких-то данных мало, не выдумывай факты, а делай универсальный, но красивый переход.",
        "",
        "Ответы анкеты:",
    ]
    for question in QUESTIONS:
        value = answers.get(question.key, "").strip() or "Не заполнено"
        lines.append(f"\n{question.prompt}\n{value}")
    return "\n".join(lines)


def _json_or_raise(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        raise OpenAIServiceError(f"OpenAI returned non-JSON response: {response.text[:500]}") from exc
    if response.status_code >= 400:
        message = data.get("error", {}).get("message") if isinstance(data.get("error"), dict) else None
        raise OpenAIServiceError(message or f"OpenAI request failed with status {response.status_code}.")
    return data


def _extract_response_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]

    chunks: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".mp3": "audio/mpeg",
        ".mpeg": "audio/mpeg",
        ".mp4": "audio/mp4",
        ".m4a": "audio/mp4",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
    }.get(suffix, "application/octet-stream")
