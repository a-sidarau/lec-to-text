"""Тесты Groq-бэкенда: парсинг, транспорт и повторы (полностью без сети)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from lec_to_text import groq_backend
from lec_to_text.errors import (
    AsrApiError,
    AsrAuthError,
    AsrRequestError,
    AsrResponseError,
)
from lec_to_text.groq_backend import parse_transcription, request_with_retries, send_file
from lec_to_text.transcriber import Segment

URL = "https://api.groq.com/openai/v1/audio/transcriptions"

SAMPLE_PAYLOAD = {
    "task": "transcribe",
    "language": "English",
    "duration": 12.5,
    "text": "Hello world. Second sentence. Third.",
    "segments": [
        {"start": 0.0, "end": 2.5, "text": " Hello world. "},
        {"start": 2.5, "end": 5.0, "text": " Second sentence. "},
        {"start": 5.0, "end": 6.0, "text": ""},  # пустой — должен отфильтроваться
        {"start": 6.0, "end": 12.5, "text": " Third. "},
    ],
}


@pytest.fixture
def audio_file(tmp_path: Path) -> Path:
    path = tmp_path / "audio.mp3"
    path.write_bytes(b"fake-mp3-bytes")
    return path


def _mock_client(handler) -> httpx.Client:
    """Клиент httpx с поддельным транспортом: сеть не используется."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _send(client: httpx.Client, audio_file: Path) -> dict:
    return send_file(
        client,
        audio_file,
        URL,
        "test-key",
        "whisper-large-v3-turbo",
        "en",
    )


# ---------------------------------------------------------------------------
# Уровень A: парсинг ответа
# ---------------------------------------------------------------------------
def test_parse_maps_segments_and_metadata() -> None:
    result = parse_transcription(
        SAMPLE_PAYLOAD,
        model="whisper-large-v3-turbo",
        requested_language="en",
    )

    assert result.language == "en"
    assert result.duration == 12.5
    assert result.backend == "groq"
    assert result.model == "whisper-large-v3-turbo"
    assert result.text == "Hello world. Second sentence. Third."
    assert result.segments == [
        Segment(start=0.0, end=2.5, text="Hello world."),
        Segment(start=2.5, end=5.0, text="Second sentence."),
        Segment(start=6.0, end=12.5, text="Third."),
    ]


def test_parse_uses_response_language_when_not_requested() -> None:
    result = parse_transcription(SAMPLE_PAYLOAD, model="m")
    assert result.language == "English"


def test_parse_allows_empty_segments() -> None:
    result = parse_transcription({"segments": [], "text": ""}, model="m")
    assert result.segments == []
    assert result.text == ""


# ---------------------------------------------------------------------------
# Уровень B: один HTTP-запрос
# ---------------------------------------------------------------------------
def test_send_file_success_sends_auth_and_multipart(audio_file: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == URL
        assert request.headers["Authorization"] == "Bearer test-key"

        body = request.read()
        assert b'name="file"' in body
        assert b'filename="audio.mp3"' in body
        assert b'name="model"' in body
        assert b"whisper-large-v3-turbo" in body

        return httpx.Response(200, json=SAMPLE_PAYLOAD)

    with _mock_client(handler) as client:
        result = _send(client, audio_file)

    assert result == SAMPLE_PAYLOAD


def test_send_file_401_raises_auth_error(audio_file: Path) -> None:
    handler = lambda request: httpx.Response(401, text="invalid key")
    with _mock_client(handler) as client, pytest.raises(AsrAuthError):
        _send(client, audio_file)


def test_send_file_400_raises_request_error(audio_file: Path) -> None:
    handler = lambda request: httpx.Response(400, text="bad request")
    with _mock_client(handler) as client, pytest.raises(AsrRequestError):
        _send(client, audio_file)


def test_send_file_429_parses_retry_after(audio_file: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, text="slow down")

    with _mock_client(handler) as client, pytest.raises(AsrApiError) as exc_info:
        _send(client, audio_file)

    assert exc_info.value.retry_after == 7.0


def test_send_file_500_raises_api_error(audio_file: Path) -> None:
    handler = lambda request: httpx.Response(500, text="boom")
    with _mock_client(handler) as client, pytest.raises(AsrApiError):
        _send(client, audio_file)


def test_send_file_timeout_raises_api_error(audio_file: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    with _mock_client(handler) as client, pytest.raises(AsrApiError):
        _send(client, audio_file)


def test_send_file_invalid_json_raises_response_error(audio_file: Path) -> None:
    handler = lambda request: httpx.Response(200, text="not-json")
    with _mock_client(handler) as client, pytest.raises(AsrResponseError):
        _send(client, audio_file)


def test_send_file_empty_key_raises_auth_error(audio_file: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("запрос не должен выполняться")

    with _mock_client(handler) as client, pytest.raises(AsrAuthError):
        send_file(client, audio_file, URL, "", "m", "en")


# ---------------------------------------------------------------------------
# Уровень C: политика повторов
# ---------------------------------------------------------------------------
def _retry_kwargs(audio_file: Path) -> dict:
    return {
        "client": object(),  # send_file замокан, клиент не используется
        "file_path": audio_file,
        "url": URL,
        "api_key": "test-key",
        "model": "whisper-large-v3-turbo",
        "language": "en",
    }


def test_retry_succeeds_after_transient_failures(monkeypatch, audio_file: Path) -> None:
    calls: list[int] = []
    delays: list[float] = []

    def fake_send(*args, **kwargs):
        calls.append(1)
        if len(calls) < 3:
            raise AsrApiError("temporary")
        return SAMPLE_PAYLOAD

    monkeypatch.setattr(groq_backend, "send_file", fake_send)

    result = request_with_retries(
        **_retry_kwargs(audio_file),
        base_delay=1.0,
        sleep=delays.append,
    )

    assert result == SAMPLE_PAYLOAD
    assert len(calls) == 3
    assert delays == [1.0, 2.0]


def test_retry_uses_retry_after(monkeypatch, audio_file: Path) -> None:
    calls: list[int] = []
    delays: list[float] = []

    def fake_send(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise AsrApiError("429", retry_after=7.0)
        return SAMPLE_PAYLOAD

    monkeypatch.setattr(groq_backend, "send_file", fake_send)

    request_with_retries(
        **_retry_kwargs(audio_file),
        base_delay=1.0,
        sleep=delays.append,
    )

    assert delays == [7.0]


def test_retry_does_not_retry_auth_error(monkeypatch, audio_file: Path) -> None:
    calls: list[int] = []

    def fake_send(*args, **kwargs):
        calls.append(1)
        raise AsrAuthError("bad key")

    monkeypatch.setattr(groq_backend, "send_file", fake_send)

    with pytest.raises(AsrAuthError):
        request_with_retries(**_retry_kwargs(audio_file), sleep=lambda _: None)

    assert len(calls) == 1


def test_retry_gives_up_after_max_attempts(monkeypatch, audio_file: Path) -> None:
    calls: list[int] = []
    delays: list[float] = []

    def fake_send(*args, **kwargs):
        calls.append(1)
        raise AsrApiError("down")

    monkeypatch.setattr(groq_backend, "send_file", fake_send)

    with pytest.raises(AsrApiError):
        request_with_retries(
            **_retry_kwargs(audio_file),
            max_attempts=3,
            base_delay=1.0,
            sleep=delays.append,
        )

    assert len(calls) == 3
    assert delays == [1.0, 2.0]


def test_retry_rejects_invalid_max_attempts(audio_file: Path) -> None:
    with pytest.raises(ValueError):
        request_with_retries(**_retry_kwargs(audio_file), max_attempts=0)
