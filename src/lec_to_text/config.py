"""Настройки приложения.

Здесь собраны *все* внешние параметры (через ``.env`` или переменные окружения).
Модули проекта НЕ читают окружение напрямую — они получают готовый объект
:class:`Settings`. Так проще тестировать (можно подсунуть свои настройки) и
переиспользовать код.

Приоритет: переменные окружения > значения из ``.env`` > дефолты из кода.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Корень проекта.
# __file__ = .../lec_to_text/src/lec_to_text/config.py
# parents[0] = .../lec_to_text/src/lec_to_text   (пакет)
# parents[1] = .../lec_to_text/src              (src)
# parents[2] = .../lec_to_text                  (корень проекта)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Значения по умолчанию, вынесены в константы.
# Нужны, чтобы использовать их и в dataclass-дефолтах, и во from_env(),
# не дублируя литералы в двух местах.
# ---------------------------------------------------------------------------
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"

# Селектор формата yt-dlp: сначала только-аудио, иначе лучший единый поток.
DEFAULT_FORMAT_SELECTOR = "bestaudio/best"

# Шаблон имени файла. %(title).120B — заголовок, обрезанный до 120 байт,
# [%(id)s] — ID ролика (гарантирует уникальность), %(ext)s — расширение.
DEFAULT_FILENAME_TEMPLATE = "%(title).120B [%(id)s].%(ext)s"

# Порядок YouTube-клиентов, которые пробуем по очереди.
# Если один отдаёт 403 / просит «подтвердить, что вы не бот» — переходим к следующему.
# "default" — пусть yt-dlp сам выберет актуальный клиент; дальше — явные фолбэки.
DEFAULT_PLAYER_CLIENTS = ("default", "android_vr", "web_safari", "mweb")

# Как подключать внешние JS-скрипты (EJS) для решения JS-задач YouTube.
# ejs:github — скачивать их с GitHub (нужен JS-рантайм, у нас deno).
DEFAULT_REMOTE_COMPONENTS = ("ejs:github",)


# ---------------------------------------------------------------------------
# Небольшие парсеры переменных окружения: строки -> нужный тип.
# ---------------------------------------------------------------------------
def _as_bool(value: str | None, default: bool) -> bool:
    """Превращает строку ("1", "true", "yes", ...) в bool."""
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "y"}


def _as_int(value: str | None, default: int) -> int:
    """Безопасно превращает строку в int (при мусоре вернёт default)."""
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _as_float(value: str | None, default: float) -> float:
    """Безопасно превращает строку в float."""
    try:
        return float(value) if value not in (None, "") else default
    except ValueError:
        return default


def _as_path(value: str | None, default: Path | None) -> Path | None:
    """Строка -> Path с раскрытием ``~``. Пустая строка/None -> default."""
    if not value:
        return default
    return Path(value).expanduser()


def _as_list(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    """Строку "a,b,c" превращает в кортеж ("a", "b", "c")."""
    if not value:
        return default
    return tuple(part.strip() for part in value.split(",") if part.strip())


@dataclass(slots=True)
class Settings:
    """Единый объект настроек для всех модулей."""

    # --- Общие -------------------------------------------------------------
    output_dir: Path = DEFAULT_OUTPUT_DIR  # куда класть готовые транскрипты
    temp_dir: Path | None = None  # где создавать временные папки (None -> системная)
    keep_audio: bool = (
        True  # True -> аудио остаётся в output_dir; False -> временная папка с удалением
    )
    verbose: bool = False  # подробный лог yt-dlp

    # --- Downloader (yt-dlp) ----------------------------------------------
    format_selector: str = DEFAULT_FORMAT_SELECTOR
    filename_template: str = DEFAULT_FILENAME_TEMPLATE
    noplaylist: bool = True  # считать ссылку одним видео, а не плейлистом
    player_clients: tuple[str, ...] = DEFAULT_PLAYER_CLIENTS
    cookies_from_browser: str | None = None  # напр. "firefox" или "chrome:Profile 1"
    cookies_file: Path | None = None  # путь к cookies.txt (Netscape)
    impersonate: str | None = "chrome"  # подмена TLS-отпечатка через curl_cffi
    proxy: str | None = None  # напр. "socks5://127.0.0.1:1080"
    retries: int = 10  # повторы скачивания
    fragment_retries: int = 10  # повторы скачивания фрагментов (DASH/HLS)
    socket_timeout: int = 30  # таймаут сокета, сек
    sleep_interval: float = 1.0  # пауза между запросами (анти-бан)
    max_sleep_interval: float = 5.0
    force_ipv4: bool = True  # использовать только IPv4
    download_archive: Path | None = None  # файл-«архив» уже скачанных ID (не качать повторно)
    cache_dir: Path | None = None  # кэш yt-dlp (подписи, токены и т.п.)
    ffmpeg_location: str | None = None  # путь к ffmpeg, если не в PATH
    js_runtime: str | None = None  # путь к deno (None -> искать в PATH)
    remote_components: tuple[str, ...] = DEFAULT_REMOTE_COMPONENTS

    # --- Аудио-препроцессинг ----------------------------------------------
    asr_sample_rate: int = 16000  # частота дискретизации для ASR
    asr_channels: int = 1  # моно
    asr_format: str = "wav"  # контейнер для ASR

    # --- Задел под ASR (используется на следующих фазах) -------------------
    hf_token: str | None = None  # токен Hugging Face
    groq_api_key: str | None = None  # ключ Groq (API-ASR, режим по умолчанию для длинных)

    # ----------------------------------------------------------------------
    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> Settings:
        """Собирает настройки из ``.env`` + переменных окружения.

        ``load_dotenv(override=False)`` — уже заданные в реальном окружении
        переменные НЕ перезаписываются значениями из файла.
        """
        if env_file:
            load_dotenv(env_file, override=False)

        return cls(
            output_dir=_as_path(os.getenv("LEC2TEXT_OUTPUT_DIR"), DEFAULT_OUTPUT_DIR),
            temp_dir=_as_path(os.getenv("LEC2TEXT_TEMP_DIR"), None),
            keep_audio=_as_bool(os.getenv("LEC2TEXT_KEEP_AUDIO"), True),
            verbose=_as_bool(os.getenv("LEC2TEXT_VERBOSE"), False),
            format_selector=os.getenv("LEC2TEXT_FORMAT_SELECTOR", DEFAULT_FORMAT_SELECTOR),
            filename_template=os.getenv("LEC2TEXT_FILENAME_TEMPLATE", DEFAULT_FILENAME_TEMPLATE),
            noplaylist=_as_bool(os.getenv("LEC2TEXT_NOPLAYLIST"), True),
            player_clients=_as_list(os.getenv("LEC2TEXT_PLAYER_CLIENTS"), DEFAULT_PLAYER_CLIENTS),
            cookies_from_browser=os.getenv("LEC2TEXT_COOKIES_FROM_BROWSER") or None,
            cookies_file=_as_path(os.getenv("LEC2TEXT_COOKIES_FILE"), None),
            impersonate=os.getenv("LEC2TEXT_IMPERSONATE", "chrome") or None,
            proxy=os.getenv("LEC2TEXT_PROXY") or None,
            retries=_as_int(os.getenv("LEC2TEXT_RETRIES"), 10),
            fragment_retries=_as_int(os.getenv("LEC2TEXT_FRAGMENT_RETRIES"), 10),
            socket_timeout=_as_int(os.getenv("LEC2TEXT_SOCKET_TIMEOUT"), 30),
            sleep_interval=_as_float(os.getenv("LEC2TEXT_SLEEP_INTERVAL"), 1.0),
            max_sleep_interval=_as_float(os.getenv("LEC2TEXT_MAX_SLEEP_INTERVAL"), 5.0),
            force_ipv4=_as_bool(os.getenv("LEC2TEXT_FORCE_IPV4"), True),
            download_archive=_as_path(os.getenv("LEC2TEXT_DOWNLOAD_ARCHIVE"), None),
            cache_dir=_as_path(os.getenv("LEC2TEXT_CACHE_DIR"), None),
            ffmpeg_location=os.getenv("LEC2TEXT_FFMPEG_LOCATION") or None,
            js_runtime=os.getenv("LEC2TEXT_JS_RUNTIME") or None,
            remote_components=_as_list(
                os.getenv("LEC2TEXT_REMOTE_COMPONENTS"), DEFAULT_REMOTE_COMPONENTS
            ),
            asr_sample_rate=_as_int(os.getenv("LEC2TEXT_ASR_SAMPLE_RATE"), 16000),
            asr_channels=_as_int(os.getenv("LEC2TEXT_ASR_CHANNELS"), 1),
            asr_format=os.getenv("LEC2TEXT_ASR_FORMAT", "wav"),
            hf_token=os.getenv("HF_TOKEN") or None,
            groq_api_key=os.getenv("GROQ_API_KEY") or None,
        )

    def ensure_dirs(self) -> None:
        """Создаёт каталоги, которые нужны для работы (output/temp/cache)."""
        self.output_dir.expanduser().mkdir(parents=True, exist_ok=True)
        for path in (self.temp_dir, self.cache_dir):
            if path is not None:
                path.expanduser().mkdir(parents=True, exist_ok=True)
