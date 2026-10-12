"""Извлечение и конвертация аудио через ffmpeg/ffprobe.

Мы не тянем Python-обёртки над ffmpeg — вызываем бинарники напрямую через
``subprocess``. Так проще читать код, нет лишних зависимостей и полностью
контролируем аргументы.

Главная функция для дальнейшего пайплайна — :func:`to_asr_wav`: она приводит
любой вход (m4a/webm/mp4/...) к «каноническому» WAV 16 kHz mono, который едят
почти все ASR-модели.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .errors import AudioConversionError, MediaToolError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioInfo:
    """Сводка об аудио-дорожке (результат ffprobe)."""

    path: Path
    duration: float | None  # секунды
    codec: str | None  # например "aac", "opus", "pcm_s16le"
    sample_rate: int | None  # Гц
    channels: int | None  # 1 = моно, 2 = стерео
    format_name: str | None  # контейнер, например "mov,mp4,m4a,..."


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------
def _tool(name: str, ffmpeg_location: str | None = None) -> str:
    """Находит исполняемый файл ffmpeg/ffprobe.

    ``ffmpeg_location`` может быть:
    - папкой с бинарниками,
    - путём к самому бинарю ffmpeg;
    - None -> искать в PATH.
    """
    if ffmpeg_location:
        loc = Path(ffmpeg_location).expanduser()
        candidate = loc / name if loc.is_dir() else loc
        if candidate.exists():
            return str(candidate)

    found = shutil.which(name)
    if not found:
        raise MediaToolError(
            f"Не найден {name}. Установите ffmpeg (в Ubuntu: sudo apt install ffmpeg) "
            "или задайте LEC2TEXT_FFMPEG_LOCATION."
        )
    return found


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Запускает внешнюю команду и превращает ошибки в понятные исключения."""
    logger.debug("run: %s", " ".join(cmd))
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:  # бинарь исчез между проверкой и вызовом
        raise MediaToolError(f"Не удалось запустить {cmd[0]}: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise AudioConversionError(
            f"Команда {cmd[0]!r} завершилась с кодом {exc.returncode}.\n"
            f"stderr:\n{exc.stderr.strip()}"
        ) from exc


def _to_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _codec_for(target_format: str, sample_rate: int) -> str | None:
    """Подбирает аудио-кодек под целевой контейнер.

    Для WAV нужен PCM без потерь; для остальных — разумные кодеки.
    ``None`` означает «пусть ffmpeg выберет сам».
    """
    fmt = target_format.lower()
    if fmt == "wav":
        # 16-битный PCM — стандарт для ASR-моделей.
        return "pcm_s16le"
    if fmt == "flac":
        return "flac"
    if fmt == "mp3":
        return "libmp3lame"
    if fmt in {"m4a", "mp4", "aac"}:
        return "aac"
    if fmt in {"ogg", "opus"}:
        return "libopus"
    if fmt == "webm":
        return "libopus"
    return None


# ---------------------------------------------------------------------------
# Публичное API
# ---------------------------------------------------------------------------
def probe_audio(path: Path | str, *, ffmpeg_location: str | None = None) -> AudioInfo:
    """Читает параметры аудио-дорожки через ffprobe."""
    ffprobe = _tool("ffprobe", ffmpeg_location)
    path = Path(path)
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "a:0",  # только первая аудио-дорожка
        "-show_entries",
        "stream=codec_name,sample_rate,channels",
        "-show_entries",
        "format=duration,format_name",
        "-of",
        "json",
        str(path),
    ]
    proc = _run(cmd)
    data = json.loads(proc.stdout or "{}")

    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}

    return AudioInfo(
        path=path,
        duration=_to_float(fmt.get("duration")),
        codec=stream.get("codec_name"),
        sample_rate=_to_int(stream.get("sample_rate")),
        channels=_to_int(stream.get("channels")),
        format_name=fmt.get("format_name"),
    )


def extract_audio(
    src: Path | str,
    dst: Path | str | None = None,
    *,
    target_format: str = "wav",
    sample_rate: int = 16000,
    channels: int = 1,
    ffmpeg_location: str | None = None,
    overwrite: bool = True,
) -> Path:
    """Извлекает/перекодирует аудио-дорожку в новый файл.

    Args:
        src: исходный медиафайл (видео или аудио).
        dst: куда писать. По умолчанию рядом с исходником, с новым расширением.
        target_format: целевой контейнер ("wav", "flac", "mp3", ...).
        sample_rate: частота дискретизации (Гц). Для ASR обычно 16000.
        channels: число каналов (1 = моно).
        overwrite: перезаписывать ли существующий файл.

    Returns:
        Путь к созданному файлу.
    """
    ffmpeg = _tool("ffmpeg", ffmpeg_location)
    src = Path(src)
    if not src.exists():
        raise AudioConversionError(f"Исходный файл не найден: {src}")

    if dst is None:
        dst = src.with_name(f"{src.stem}.{target_format}")
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)

    codec = _codec_for(target_format, sample_rate)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",  # не читать stdin, меньше шума
        "-loglevel",
        "error",
        "-y" if overwrite else "-n",
        "-i",
        str(src),
        "-vn",  # видеодорожку отбрасываем
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
    ]
    if codec:
        cmd += ["-acodec", codec]
    cmd.append(str(dst))

    _run(cmd)

    if not dst.exists():
        raise AudioConversionError(f"ffmpeg не создал файл {dst}")
    logger.info("Аудио извлечено: %s -> %s", src.name, dst.name)
    return dst


def to_asr_wav(
    src: Path | str,
    dst: Path | str | None = None,
    *,
    settings: Settings | None = None,
    ffmpeg_location: str | None = None,
) -> Path:
    """Приводит аудио к каноническому виду для ASR: WAV, 16 kHz, моно.

    Если файл уже в нужном формате — не перекодируем (экономим время на
    длинных лекциях). Иначе вызываем :func:`extract_audio`.

    Параметры частоты/каналов берутся из :class:`Settings`.
    """
    settings = settings or Settings.from_env()
    sample_rate = settings.asr_sample_rate
    channels = settings.asr_channels
    location = ffmpeg_location or settings.ffmpeg_location

    src = Path(src)

    # Проверяем, нужно ли вообще перекодирование.
    try:
        info = probe_audio(src, ffmpeg_location=location)
        already_ok = (
            info.format_name is not None
            and "wav" in info.format_name
            and info.sample_rate == sample_rate
            and info.channels == channels
        )
        if already_ok:
            logger.debug("Файл уже %d Hz / %d ch WAV, конвертация не нужна", sample_rate, channels)
            return src
    except MediaToolError:
        # Если ffprobe недоступен — просто попробуем конвертировать (extract_audio
        # выдаст понятную ошибку, если ffmpeg тоже нет).
        logger.warning("ffprobe недоступен, конвертирую без проверки формата")

    if dst is None:
        dst = src.with_name(f"{src.stem}.{sample_rate // 1000}k.wav")

    return extract_audio(
        src,
        dst,
        target_format="wav",
        sample_rate=sample_rate,
        channels=channels,
        ffmpeg_location=location,
    )
