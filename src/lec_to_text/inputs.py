"""Распознавание входа: что нам передали — локальный файл, YouTube или другую ссылку.

Это первая стадия пайплайна. Она не скачивает, а только классифицирует вход,
чтобы дальше выбрать правильную стратегию:
- локальный файл — скачивание не нужно, сразу переходим к аудио;
- YouTube — используем yt-dlp с полным «обвесом» против 403;
- прочая ссылка — отдаём yt-dlp в режиме generic (он умеет многие сайты).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .errors import UnsupportedInputError

# Домены, которые считаем YouTube. short-ссылки вида youtu.be тоже здесь.
_YOUTUBE_HOSTS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
)

# Регулярка «похоже на URL со схемой» (http/https/ftp/...).
_URL_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://")


class InputKind(str, Enum):
    """Тип входного источника."""

    LOCAL_FILE = "local_file"  # существующий файл на диске
    YOUTUBE = "youtube"  # ссылка на YouTube
    REMOTE_URL = "remote_url"  # любая другая сетевая ссылка


@dataclass(slots=True)
class ResolvedInput:
    """Результат распознавания.

    ``raw`` — то, что пришло на вход, ``path`` — путь для локального файла,
    ``url`` — ссылка для сетевых источников.
    """

    kind: InputKind
    raw: str
    path: Path | None = None
    url: str | None = None


def is_youtube(url: str) -> bool:
    """True, если ссылка ведёт на YouTube.

    Разбираем вручную (без urllib.parse.getfqdn), чтобы корректно
    обрабатывать поддомены и порт.
    """
    without_scheme = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", url)
    host = without_scheme.split("/", 1)[0].split("?", 1)[0].split("@")[-1].split(":", 1)[0]
    host = host.lower()
    return any(host == h or host.endswith("." + h) for h in _YOUTUBE_HOSTS)


def resolve(source: str) -> ResolvedInput:
    """Классифицирует вход.

    Raises:
        UnsupportedInputError: если это не URL и не существующий файл.
    """
    source = source.strip()
    if not source:
        raise UnsupportedInputError("Пустой вход: укажите ссылку или путь к файлу")

    # 1) Похоже на URL.
    if _URL_RE.match(source):
        if is_youtube(source):
            return ResolvedInput(kind=InputKind.YOUTUBE, raw=source, url=source)
        return ResolvedInput(kind=InputKind.REMOTE_URL, raw=source, url=source)

    # 2) Иначе считаем путём к файлу. expanduser раскрывает "~".
    path = Path(source).expanduser()
    if path.exists() and path.is_file():
        return ResolvedInput(kind=InputKind.LOCAL_FILE, raw=source, path=path.resolve())

    raise UnsupportedInputError(
        f"Не удалось распознать вход: {source!r}. Это не ссылка и не существующий файл."
    )
