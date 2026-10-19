from pathlib import Path
from typing import Literal

import httpx

from lec_to_text.errors import AsrApiError, AsrAuthError, AsrRequestError, TranscriptionError

from .config import PROJECT_ROOT, Settings
from .transcriber import Segment, TranscriptResult

RespFormat = Literal["text", "json", "verbose_json"]

def send_file(
    client: httpx.Client,
    file_path: str | Path,
    url: str,
    api_key: str,
    model: str,
    language: str,
    response_format: RespFormat = "verbose_json",  #  json, text, verbose_json
    temperature: float = 0.0
) -> dict:
    """Отправка файла API-провайдеру"""
    with open(file_path, "rb") as file:
        resp = client.post(
            url,
            # OpenAI совместимый API
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            data={
                "model": model,
                "language": language,
                "temperature": str(temperature),
                "response_format": response_format,
            },
            files={"file": (Path(file_path).name, file, "audio/mpeg")},
        )

        code = resp.status_code
        match code:
            case 200:
                return resp.json()
            case 401 | 403:
                raise AsrAuthError(f"Статус {resp.status_code}: ошибка доступа")
            case 400 | 404 | 413 | 422:
                raise AsrRequestError(f"Статус {resp.status_code}: плохой запрос или файл")
            case 429:
                raise AsrApiError(f"Статус {resp.status_code}: превышен лимит запросов")
            case code if 500 <= code < 600:
                raise AsrApiError(f"Статус {resp.status_code}: сбой на стороне Groq")
            case _:
                raise AsrApiError(f"Статус {resp.status_code}: {resp.text[:300]}...")


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
            end=float(seg["end"])
        )
        for seg in response.get("segments", []) if seg["text"]
    ]

    return TranscriptResult(
        text=response.get("text", "").strip(),
        segments=segments,
        language=requested_language or response.get("language", ""),
        duration=float(response.get("duration") or 0.0),
        backend=backend,
        model=model,
    )


    # with open(f"{PROJECT_ROOT}/tmp/response.json", "w", encoding="utf-8") as f:
    #     f.write(json.dumps(response, ensure_ascii=False, indent=2))
    # return ...

if __name__ == "__main__":
    settings = Settings.from_env()
    model = settings.asr_model
    api_key = settings.groq_api_key
    language = settings.asr_language
    if api_key is None or api_key == "":
        raise ValueError("Не удалось считать API-ключ. Проверьте .env")

    file_path = PROJECT_ROOT / "output/part90_test.mp3"
    url = f"{settings.groq_base_url}/audio/transcriptions"

    client = httpx.Client(timeout=120)
    transcription = send_file(
        client=client,
        file_path=file_path,
        api_key=api_key,
        model=model,
        url=url,
        language=language)

    result = parse_transcription(
        response=transcription,
        model=model,
        requested_language=language
    )
