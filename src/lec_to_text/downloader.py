"""Скачивание аудио из видео через yt-dlp.

Почему отдельный модуль и так много кода вокруг yt-dlp:
YouTube регулярно меняет защиту от автоматического скачивания. Типичные симптомы —
``HTTP Error 403`` или «Sign in to confirm you're not a bot». Голый вызов yt-dlp
на это ломается. Здесь мы собираем «обвес», который решает 95% проблем:

1. **PO Token Provider** — плагин ``bgutil-ytdlp-pot-provider`` (если установлен),
   сам генерирует Proof-of-Origin токен, который YouTube сейчас требует для
   части клиентов. Мы ничего для этого не делаем, просто не мешаем плагину.
2. **EJS / JS-рантайм** — YouTube отдаёт JS-задачи; их решает deno. Указываем
   ``js_runtimes`` и разрешаем подгружать скрипты (``ejs:github``).
3. **Cookies** — могут потребоваться для bot-check; берём из браузера или файла.
4. **Impersonation** — подмена TLS-отпечатка (curl_cffi), чтобы запрос выглядел
   как из настоящего браузера.
5. **Цепочка player_client** — если один YouTube-клиент отдал 403, пробуем
   следующий. Только для YouTube и только при «исправимых» ошибках.
6. **Retry / sleep** — снижают шанс попасть под rate-limit.

Мы НЕ конвертируем аудио в mp3 внутри yt-dlp: сохраняем «нативный» контейнер
(m4a/webm и т.п.) и отдаём его в модуль :mod:`lec_to_text.audio`. Так быстрее
и без потери качества.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

from yt_dlp import YoutubeDL
from yt_dlp.networking.impersonate import ImpersonateTarget
from yt_dlp.utils import DownloadError as YtDlpDownloadError

from .config import Settings
from .errors import (
    DownloadError,
    GeoRestrictedError,
    PrivateVideoError,
    UnsupportedSiteError,
    classify_download_error,
)
from .inputs import InputKind, ResolvedInput, resolve

logger = logging.getLogger(__name__)


class _YtDlpLogger:
    """Мост между логгером yt-dlp и стандартным ``logging``.

    yt-dlp ждёт объект с методами debug/info/warning/error. Он шлёт туда и
    реальные debug-сообщения (с префиксом ``[debug]``), и обычный вывод.
    Разделяем их: ``[debug]`` -> DEBUG, остальное -> INFO.
    """

    def __init__(self, log: logging.Logger) -> None:
        self._log = log

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug] "):
            self._log.debug(msg)
        else:
            self._log.info(msg)

    def info(self, msg: str) -> None:
        self._log.info(msg)

    def warning(self, msg: str) -> None:
        self._log.warning(msg)

    def error(self, msg: str) -> None:
        self._log.error(msg)


@dataclass(slots=True)
class MediaMetadata:
    """Метаданные ролика, нужные для имени файлов и дальнейшей обработки."""

    video_id: str | None
    title: str | None
    duration: float | None  # длительность в секундах
    uploader: str | None
    webpage_url: str | None
    thumbnail: str | None
    extractor: str | None
    is_live: bool


@dataclass(slots=True)
class DownloadResult:
    """Результат скачивания (или «обёртка» вокруг локального файла)."""

    kind: InputKind
    source: str
    audio_path: Path
    metadata: MediaMetadata

    @property
    def video_id(self) -> str | None:
        return self.metadata.video_id

    @property
    def title(self) -> str | None:
        return self.metadata.title

    @property
    def duration(self) -> float | None:
        return self.metadata.duration


class AudioDownloader:
    """Скачивает аудио-дорожку и управляет временными файлами.

    Использование::

        with AudioDownloader() as dl:
            result = dl.download("https://youtu.be/...")
            # ... работаем с result.audio_path ...
        # при keep_audio=True (по умолчанию) аудио остаётся в output_dir;
        # при keep_audio=False временная папка удалится автоматически
    """

    def __init__(self, settings: Settings | None = None) -> None:
        # Настройки можно не передавать — тогда берём из .env/окружения.
        self.settings = settings or Settings.from_env()
        self._log = logger
        self._workdir: Path | None = None
        # Флаг: папку создали МЫ (значит, можем и удалить). Если пользователь
        # передал свой out_dir — удалять его нельзя.
        self._owns_workdir = False

    # -- Контекстный менеджер: гарантированная уборка временных файлов --------
    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.cleanup()

    @property
    def workdir(self) -> Path | None:
        """Текущая рабочая (временная) папка или None."""
        return self._workdir

    # -- Публичное API ------------------------------------------------------
    def probe(self, source: str) -> MediaMetadata:
        """Получает метаданные БЕЗ скачивания (id, title, duration, ...).

        Полезно для маршрутизации (короткое -> локальный ASR, длинное -> API)
        и для проверки ссылки до тяжёлого скачивания.
        """
        resolved = resolve(source)

        # Локальный файл — метаданных из сети нет; длительность узнает audio.py.
        if resolved.kind is InputKind.LOCAL_FILE:
            return MediaMetadata(
                video_id=None,
                title=resolved.path.stem,
                duration=None,
                uploader=None,
                webpage_url=None,
                thumbnail=None,
                extractor="local",
                is_live=False,
            )

        opts = self._build_opts(workdir=None, client=None)
        opts["skip_download"] = True  # download=False уже задаёт это, но явно понятнее
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(resolved.url, download=False)
        except YtDlpDownloadError as exc:
            # Прокидываем типизированную ошибку (403 / bot-check / geo / ...).
            raise classify_download_error(exc) from exc
        if not info:
            raise DownloadError("yt-dlp не смог получить метаданные")
        return self._metadata(info)

    def download(
        self,
        source: str,
        *,
        out_dir: Path | str | None = None,
        clients: tuple[str, ...] | None = None,
        progress_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> DownloadResult:
        """Скачивает аудио и возвращает :class:`DownloadResult`.

        Args:
            source: ссылка или путь к локальному файлу.
            out_dir: куда класть файл. Если None — временная папка.
            clients: своя цепочка YouTube-клиентов (по умолчанию из настроек).
            progress_hook: колбэк прогресса в формате yt-dlp (dict).
        """
        resolved = resolve(source)

        # Локальный файл скачивать не нужно — оборачиваем как есть.
        if resolved.kind is InputKind.LOCAL_FILE:
            return DownloadResult(
                kind=resolved.kind,
                source=resolved.raw,
                audio_path=resolved.path,
                metadata=MediaMetadata(
                    video_id=None,
                    title=resolved.path.stem,
                    duration=None,
                    uploader=None,
                    webpage_url=None,
                    thumbnail=None,
                    extractor="local",
                    is_live=False,
                ),
            )

        workdir = self._prepare_workdir(out_dir)
        chain = tuple(clients) if clients else self.settings.player_clients

        last_error: Exception | None = None
        for client in chain:
            try:
                return self._download_with_client(resolved, workdir, client, progress_hook)
            except YtDlpDownloadError as exc:
                error = classify_download_error(exc)
                last_error = error

                # Эти причины не зависят от выбранного клиента — пробовать другие
                # бессмысленно, сразу сообщаем пользователю.
                if isinstance(error, (PrivateVideoError, GeoRestrictedError, UnsupportedSiteError)):
                    raise error from exc

                # 403 / bot-check / сеть — возможно, повезёт со следующим клиентом.
                self._log.warning(
                    "YouTube-клиент '%s' не сработал (%s). Пробуем следующий...",
                    client,
                    type(error).__name__,
                )

        raise DownloadError(
            f"Не удалось скачать {resolved.url!r} ни одним из клиентов {chain}. "
            f"Последняя ошибка: {last_error}. "
            "Подсказка: см. README -> Troubleshooting 403 (PO Token / cookies)."
        ) from last_error

    def cleanup(self) -> None:
        """Удаляет временную папку, если её создавали мы, и сбрасывает состояние."""
        if self._owns_workdir and self._workdir and self._workdir.exists():
            shutil.rmtree(self._workdir, ignore_errors=True)
        self._workdir = None
        self._owns_workdir = False

    # -- Внутренняя кухня ---------------------------------------------------
    def _download_with_client(
        self,
        resolved: ResolvedInput,
        workdir: Path,
        client: str,
        progress_hook: Callable[[dict[str, Any]], None] | None,
    ) -> DownloadResult:
        """Одна попытка скачивания конкретным YouTube-клиентом."""
        opts = self._build_opts(workdir=workdir, client=client, progress_hook=progress_hook)
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(resolved.url, download=True)
            if not info:
                raise DownloadError("yt-dlp вернул пустой результат")
            if info.get("_type") == "playlist":
                raise UnsupportedSiteError(
                    "Ссылка ведёт на плейлист. Обрабатывайте видео по одному "
                    "или включите noplaylist=False и обрабатывайте entries сами."
                )
            audio_path = self._resolve_audio_path(ydl, info)

        if not audio_path.exists():
            raise DownloadError(
                f"Файл не найден по пути {audio_path}. "
                "Возможно, видео уже в download_archive (LEC2TEXT_DOWNLOAD_ARCHIVE) "
                "и скачивание было пропущено."
            )

        self._log.info("Скачано: %s", audio_path.name)
        return DownloadResult(
            kind=resolved.kind,
            source=resolved.raw,
            audio_path=audio_path,
            metadata=self._metadata(info),
        )

    def _resolve_audio_path(self, ydl: YoutubeDL, info: dict[str, Any]) -> Path:
        """Находит реальный путь скачанного файла.

        ``prepare_filename`` угадывает имя по шаблону, но это ненадёжно.
        yt-dlp кладёт точный путь в ``requested_downloads[*]["filepath"]``
        (а при отсутствии — в ``info["filepath"]``). Сначала проверяем их.
        """
        for entry in info.get("requested_downloads") or []:
            filepath = entry.get("filepath")
            if filepath:
                return Path(filepath)

        filepath = info.get("filepath")
        if filepath:
            return Path(filepath)

        # Последний фолбэк — вычисляем по шаблону.
        return Path(ydl.prepare_filename(info))

    @staticmethod
    def _metadata(info: dict[str, Any]) -> MediaMetadata:
        return MediaMetadata(
            video_id=info.get("id"),
            title=info.get("title"),
            duration=info.get("duration"),
            uploader=info.get("uploader") or info.get("channel"),
            webpage_url=info.get("webpage_url"),
            thumbnail=info.get("thumbnail"),
            extractor=info.get("extractor_key") or info.get("extractor"),
            is_live=bool(info.get("is_live")),
        )

    def _prepare_workdir(self, out_dir: Path | str | None) -> Path:
        """Возвращает папку, в которую скачивается аудио.

        Приоритет:
        1. явный ``out_dir`` от пользователя — используем и НЕ удаляем;
        2. ``settings.output_dir``, если ``keep_audio=True`` (по умолчанию) —
           аудио сохраняется на диске;
        3. временная папка (удаляется в :meth:`cleanup`), если ``keep_audio=False``.
        """
        # 1) Пользователь передал свою папку — используем и не помечаем как свою.
        if out_dir is not None:
            path = Path(out_dir).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            self._workdir = path
            return path

        # Уже создавали — переиспользуем.
        if self._workdir is not None:
            return self._workdir

        # 2) По умолчанию сохраняем аудио в output_dir — файл останется на диске.
        if self.settings.keep_audio:
            target = self.settings.output_dir.expanduser()
            target.mkdir(parents=True, exist_ok=True)
            self._workdir = target
            # Папку создали не мы -> cleanup() её не удалит.
            self._owns_workdir = False
            self._log.debug("Аудио сохраняется в: %s", target)
            return target

        # 3) keep_audio=False — временная папка, которую уберёт cleanup().
        base = self.settings.temp_dir
        if base is not None:
            base = Path(base).expanduser()
            base.mkdir(parents=True, exist_ok=True)

        self._workdir = Path(tempfile.mkdtemp(prefix="lec2text_", dir=str(base) if base else None))
        self._owns_workdir = True
        self._log.debug("Временная папка: %s", self._workdir)
        return self._workdir

    def _js_runtimes(self) -> dict[str, dict[str, str]]:
        """Конфиг JS-рантайма для yt-dlp.

        Формат: ``{"deno": {"path": "/путь/к/deno"}}``. Если путь не задан,
        оставляем пустой конфиг — yt-dlp найдёт deno в PATH (он там у вас есть).
        """
        config: dict[str, str] = {}
        if self.settings.js_runtime:
            config["path"] = self.settings.js_runtime
        return {"deno": config}

    def _parse_cookies_browser(
        self, spec: str
    ) -> tuple[str | None, str | None, str | None, str | None]:
        """Разбирает строку cookies-from-browser в кортеж, который ждёт yt-dlp.

        Формат yt-dlp: ``BROWSER[+KEYRING][:PROFILE][::CONTAINER]``,
        а на вход ему нужен кортеж ``(browser, profile, keyring, container)``.
        Примеры: ``firefox``, ``chrome:Profile 1``, ``chrome+gnomekeyring:Default``.
        """
        spec = spec.strip()
        keyring = container = profile = None
        if "+" in spec:  # +KEYRING
            spec, keyring = spec.split("+", 1)
        if "::" in spec:  # ::CONTAINER
            spec, container = spec.split("::", 1)
        if ":" in spec:  # :PROFILE
            spec, profile = spec.split(":", 1)
        return (spec or None, profile, keyring, container)

    def _build_opts(
        self,
        workdir: Path | None,
        client: str | None,
        progress_hook: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Собирает словарь параметров для :class:`yt_dlp.YoutubeDL`."""
        opts: dict[str, Any] = {
            # Формат: только аудио, иначе лучший доступный единый поток.
            "format": self.settings.format_selector,
            "noplaylist": self.settings.noplaylist,
            # Тихий режим, если не включён verbose; свой логгер подключён ниже.
            "quiet": not self.settings.verbose,
            "no_warnings": not self.settings.verbose,
            "noprogress": True,
            "logger": _YtDlpLogger(self._log),
            # Повторы и «вежливые» паузы против rate-limit.
            "retries": self.settings.retries,
            "fragment_retries": self.settings.fragment_retries,
            "socket_timeout": self.settings.socket_timeout,
            "sleep_interval": self.settings.sleep_interval,
            "max_sleep_interval": self.settings.max_sleep_interval,
            "overwrites": False,
            # Разрешаем символы окон/юникод в именах (иначе всё станет ASCII).
            "windowsfilenames": True,
            # JavaScript-рантайм (deno) и внешние EJS-скрипты.
            "js_runtimes": self._js_runtimes(),
            "remote_components": set(self.settings.remote_components),
        }

        if workdir is not None:
            opts["outtmpl"] = str(workdir / self.settings.filename_template)

        # --force-ipv4 в API yt-dlp = source_address "0.0.0.0".
        if self.settings.force_ipv4:
            opts["source_address"] = "0.0.0.0"

        # Cookies: файл в приоритете, иначе — из браузера.
        if self.settings.cookies_file:
            opts["cookiefile"] = str(self.settings.cookies_file)
        elif self.settings.cookies_from_browser:
            opts["cookiesfrombrowser"] = self._parse_cookies_browser(
                self.settings.cookies_from_browser
            )

        # Подмена TLS-отпечатка (curl_cffi). Строка вида "chrome" или "chrome:windows".
        # yt-dlp ждёт объект ImpersonateTarget, а не строку, поэтому парсим сами.
        if self.settings.impersonate:
            opts["impersonate"] = ImpersonateTarget.from_str(self.settings.impersonate)

        if self.settings.proxy:
            opts["proxy"] = self.settings.proxy
        if self.settings.download_archive:
            opts["download_archive"] = str(self.settings.download_archive)
        if self.settings.cache_dir:
            opts["cachedir"] = str(self.settings.cache_dir)
        if self.settings.ffmpeg_location:
            opts["ffmpeg_location"] = self.settings.ffmpeg_location

        # Выбор YouTube-клиента. "default" -> не задаём вовсе: пусть yt-dlp выберет
        # актуальный сам. Явные клиенты-фолбэки задаём только при необходимости.
        if client and client != "default":
            opts["extractor_args"] = {"youtube": {"player_client": [client]}}

        # Колбэк прогресса (если пользователь захотел показывать проценты).
        if progress_hook is not None:
            opts["progress_hooks"] = [progress_hook]

        return opts


def download_audio(
    source: str,
    *,
    settings: Settings | None = None,
    out_dir: Path | str | None = None,
    clients: tuple[str, ...] | None = None,
) -> DownloadResult:
    """Удобная функция-обёртка для разового скачивания."""
    return AudioDownloader(settings).download(source, out_dir=out_dir, clients=clients)
