from __future__ import annotations

import os

import pytest

from lec_to_text.config import (
    DEFAULT_ASR_MODEL,
    DEFAULT_CHUNK_SECONDS,
    DEFAULT_GROQ_BASE_URL,
    DEFAULT_REQUEST_TIMEOUT,
    Settings,
)

# Префиксы для парсинга тестируемых переменных окружения и их очистки
_WATCHED_PREFIX = "LEC2TEXT_"
_WATCHED_NAMES = {"GROQ_API_KEY", "HF_TOKEN"}


# Очищаем окружение для тестов
@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Убираем наши переменные из окружения перед каждым тестом.

        autouse=True -> фикстура выполняется автоматически для всех тестов.
        monkeypatch сам вернёт окружение как было после теста.
    """
    # получаем все переменные окружения
    for name in list(os.environ):
        # парсим только нужные переменные
        if name.startswith(_WATCHED_PREFIX) or name in _WATCHED_NAMES:
            # monkeypatch - временно удаляет что-то
            monkeypatch.delenv(name, raising=False)
            # raising=False -> не выкидывает исключение, если переменная не установлена


def test_language_default_is_russian() -> None:
    """Без явной переменной язык по умолчанию -- русский"""
    settings = Settings.from_env(env_file=None)

    assert settings.asr_language == "ru"


def test_defaults_without_env() -> None:
    """Если переменные не заданы, то берутся дефолтные"""
    settings = Settings.from_env(env_file=None)

    assert settings.asr_model == DEFAULT_ASR_MODEL
    assert settings.groq_base_url == DEFAULT_GROQ_BASE_URL
    assert settings.chunk_seconds == DEFAULT_CHUNK_SECONDS
    assert settings.request_timeout == DEFAULT_REQUEST_TIMEOUT


def test_language_empty_is_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если язык задан как пустая строка -- определяется автоматически (None)"""
    monkeypatch.setenv("LEC2TEXT_ASR_LANGUAGE", "")

    settings = Settings.from_env(env_file=None)

    assert settings.asr_language is None


def test_numeric_values_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Числовые переменыне из окружения парсятся как числа"""
    monkeypatch.setenv("LEC2TEXT_CHUNK_SECONDS", "60")
    monkeypatch.setenv("LEC2TEXT_CHUNK_OVERLAP", "2.3")

    settings = Settings.from_env(env_file=None)

    assert settings.chunk_seconds == 60
    assert settings.chunk_overlap == 2.3


def test_garbage_numeric_values_fallback_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Мусор в числовой переменной не роняет приложение — берётся дефолт."""
    monkeypatch.setenv("LEC2TEXT_RETRIES", "sadq")
    monkeypatch.setenv("LEC2TEXT_REQUEST_TIMEOUT", "qqqqq")

    settings = Settings.from_env(env_file=None)

    assert settings.retries == 10
    assert settings.request_timeout == DEFAULT_REQUEST_TIMEOUT


def test_empty_envs_uses_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустая строка типа str -> используется дефолт из конфига"""
    monkeypatch.setenv("LEC2TEXT_ASR_MODEL", "")
    monkeypatch.setenv("LEC2TEXT_GROQ_BASE_URL", "")

    settings = Settings.from_env(env_file=None)

    assert settings.asr_model == DEFAULT_ASR_MODEL
    assert settings.groq_base_url == DEFAULT_GROQ_BASE_URL
