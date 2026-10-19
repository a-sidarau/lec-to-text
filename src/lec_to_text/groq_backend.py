"""Бэкенд транскрибации через Groq (OpenAI-совместимый API).

Три уровня ответственности:
- :func:`send_file` — один HTTP-запрос (транспорт);
- :func:`parse_transcription` — превращение JSON в ``TranscriptResult`` (чистая функция);
- :func:`request_with_retries` — политика повторов.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx

from .config import PROJECT_ROOT, Settings
from .errors import AsrApiError, AsrAuthError, AsrRequestError, AsrResponseError
from .transcriber import Segment, TranscriptResult

RespFormat = Literal["text", "json", "verbose_json"]
logger = logging.getLogger(__name__)


def _parse_retry_after(resp: httpx.Response) -> float | None:
    """Достаёт Retry-After (в секундах) из ответа, если сервер его прислал."""
    value = resp.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        # По стандарту там может быть HTTP-дата; для Groq это редкость.
        return None


def send_file(
    client: httpx.Client,
    file_path: str | Path,
    url: str,
    api_key: str,
    model: str,
    language: str,
    response_format: RespFormat = "verbose_json",  # json, text, verbose_json
    temperature: float = 0.0,
) -> dict:
    """Один запрос к API: отправляет файл и возвращает JSON ответа.

    Сбои превращаются в типизированные исключения проекта:
    401/403 -> AsrAuthError; остальные 4xx -> AsrRequestError;
    429/5xx/сеть -> AsrApiError; битый JSON -> AsrResponseError.
    """
    if not api_key:
        raise AsrAuthError("Пустой API-ключ")

    try:
        with open(file_path, "rb") as file:
            resp = client.post(
                url,
                # OpenAI-совместимый API: ключ только в заголовке.
                headers={"Authorization": f"Bearer {api_key}"},
                data={
                    "model": model,
                    "language": language,
                    "temperature": str(temperature),
                    "response_format": response_format,
                },
                files={"file": (Path(file_path).name, file, "audio/mpeg")},
            )
    except httpx.RequestError as exc:
        # Таймауты, обрывы, DNS, прокси: запрос не дошёл до сервера.
        raise AsrApiError(f"Сетевая ошибка: {exc}") from exc

    code = resp.status_code
    detail = resp.text[:300]

    match code:
        case 200:
            try:
                return resp.json()
            except ValueError as exc:
                raise AsrResponseError(f"Некорректный JSON: {detail}") from exc
        case 401 | 403:
            raise AsrAuthError(f"Статус {code}: ошибка доступа. {detail}")
        case 400 | 404 | 413 | 422:
            raise AsrRequestError(f"Статус {code}: плохой запрос или файл. {detail}")
        case 429:
            raise AsrApiError(
                f"Статус {code}: превышен лимит запросов. {detail}",
                retry_after=_parse_retry_after(resp),
            )
        case code if 500 <= code < 600:
            raise AsrApiError(f"Статус {code}: сбой на стороне Groq. {detail}")
        case _:
            raise AsrApiError(f"Статус {code}: {detail}")


def parse_transcription(
    response: dict,
    model: str,
    requested_language: str = "",
    backend: str = "groq",
) -> TranscriptResult:
    """Парсим json ответа в отдельные структуры"""

    segments = [
        # Т.к. json отдаёт список словарей, парсим их через list comprehension
        Segment(
            text=seg.get("text", "").strip(),
            start=float(seg["start"]),
            end=float(seg["end"]),
        )
        for seg in response.get("segments", [])
        if seg["text"]
    ]

    return TranscriptResult(
        text=response.get("text", "").strip(),
        segments=segments,
        language=requested_language or response.get("language", ""),
        duration=float(response.get("duration") or 0.0),
        backend=backend,
        model=model,
    )


def request_with_retries(
    client: httpx.Client,
    file_path: str | Path,
    *,
    url: str,
    api_key: str,
    model: str,
    language: str,
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    response_format: RespFormat = "verbose_json",  # json, text, verbose_json
    temperature: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Отправляет файл, повторяя только временные сбои (``AsrApiError``).

    - ``AsrAuthError`` / ``AsrRequestError`` / ``AsrResponseError`` пробрасываются сразу;
    - при 429 приоритет у ``Retry-After`` из исключения;
    - иначе экспоненциальная пауза: base_delay, 2*base_delay, 4*base_delay...
    - ``sleep`` подменяется в тестах, чтобы не ждать по-настоящему.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts должен быть >= 1")

    for attempt in range(1, max_attempts + 1):
        try:
            return send_file(
                client,
                file_path,
                url=url,
                api_key=api_key,
                model=model,
                language=language,
                response_format=response_format,
                temperature=temperature,
            )
        except AsrApiError as exc:
            if attempt == max_attempts:
                raise

            delay = exc.retry_after
            if delay is None:
                delay = min(max_delay, base_delay * 2 ** (attempt - 1))

            logger.warning(
                "ASR: попытка %d/%d не удалась (%s). Повтор через %.1f c",
                attempt,
                max_attempts,
                exc,
                delay,
            )
            sleep(delay)

    raise AssertionError("unreachable")


if __name__ == "__main__":
    settings = Settings.from_env()
    api_key = settings.groq_api_key
    if api_key is None or api_key == "":
        raise SystemExit("Не удалось считать API-ключ. Проверьте .env")

    file_path = PROJECT_ROOT / "output/part90_test.mp3"
    url = f"{settings.groq_base_url}/audio/transcriptions"

    with httpx.Client(timeout=settings.request_timeout) as client:
        transcription = request_with_retries(
            client=client,
            file_path=file_path,
            url=url,
            api_key=api_key,
            model=settings.asr_model,
            language=settings.asr_language or "ru",
            max_attempts=settings.asr_max_attempts,
            base_delay=settings.asr_retry_base_delay,
        )

    result = parse_transcription(
        response=transcription,
        model=settings.asr_model,
        requested_language=settings.asr_language or "",
    )
    print(f"{result.language}: {len(result.segments)} сегментов")
    print(result.text[:200])
