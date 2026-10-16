"""Тесты аудио-препроцессинга (нужен установленный ffmpeg)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from lec_to_text import Settings, probe_audio, to_asr_wav
from lec_to_text.audio import extract_audio, split_audio
from lec_to_text.errors import AudioConversionError

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe не установлены",
)


@pytest.fixture
def tone_mp3(tmp_path):
    """Генерирует короткий стерео-тон 44.1 kHz в mp3 через ffmpeg."""
    path = tmp_path / "tone.mp3"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-ac",
            "2",
            "-ar",
            "44100",
            str(path),
        ],
        check=True,
    )
    return path


def test_probe_reads_parameters(tone_mp3) -> None:
    info = probe_audio(tone_mp3)
    assert info.duration == pytest.approx(1.0, abs=0.1)
    assert info.sample_rate == 44100
    assert info.channels == 2


def test_to_asr_wav_converts(tone_mp3, tmp_path) -> None:
    settings = Settings(asr_sample_rate=16000, asr_channels=1)
    wav = to_asr_wav(tone_mp3, dst=tmp_path / "tone.16k.wav", settings=settings)

    info = probe_audio(wav)
    assert info.sample_rate == 16000
    assert info.channels == 1
    assert info.codec == "pcm_s16le"


def test_to_asr_wav_is_idempotent(tone_mp3, tmp_path) -> None:
    settings = Settings(asr_sample_rate=16000, asr_channels=1)
    wav = to_asr_wav(tone_mp3, dst=tmp_path / "tone.16k.wav", settings=settings)

    # Повторный вызов на уже готовом файле должен вернуть тот же путь
    # без перекодирования.
    again = to_asr_wav(wav, settings=settings)
    assert again == wav


def test_extract_audio_missing_source(tmp_path) -> None:
    with pytest.raises(AudioConversionError):
        extract_audio(tmp_path / "nope.mp4")


# ---------------------------------------------------------------------------
# split_audio
# ---------------------------------------------------------------------------
@pytest.fixture
def make_tone(tmp_path):
    """Фабрика: генерирует моно-тон 16 kHz заданной длительности."""

    def _make(duration: float) -> Path:
        path = tmp_path / f"tone_{duration:g}.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"sine=frequency=440:duration={duration}",
                "-ac",
                "1",
                "-ar",
                "16000",
                str(path),
            ],
            check=True,
        )
        return path

    return _make


def test_split_audio_covers_duration(make_tone, tmp_path) -> None:
    """6 c, chunk=2, overlap=0.5 -> 4 чанка; старты каждые 1.5 c."""
    chunks = split_audio(
        make_tone(6.0),
        tmp_path / "chunks",
        chunk_seconds=2,
        overlap=0.5,
        bitrate="48k",
    )

    assert [c.start for c in chunks] == pytest.approx([0.0, 1.5, 3.0, 4.5], abs=0.01)
    assert [c.end for c in chunks] == pytest.approx([2.0, 3.5, 5.0, 6.0], abs=0.05)


def test_split_audio_last_chunk_is_short(make_tone, tmp_path) -> None:
    """Регресс на ceil: 5.9 c при step=1.5 -> 4 чанка, а не 3 (как давал int)."""
    chunks = split_audio(
        make_tone(5.9),
        tmp_path / "chunks",
        chunk_seconds=2,
        overlap=0.5,
        bitrate="48k",
    )

    assert len(chunks) == 4
    assert chunks[-1].end == pytest.approx(5.9, abs=0.05)


def test_split_audio_files_are_valid_mp3(make_tone, tmp_path) -> None:
    """Каждый чанк — непустой mp3, длительность близка к ожидаемой."""
    chunks = split_audio(
        make_tone(6.0),
        tmp_path / "chunks",
        chunk_seconds=2,
        overlap=0.5,
        bitrate="48k",
    )

    durations: list[float | None] = []
    for chunk in chunks:
        assert chunk.path.exists()
        assert chunk.path.suffix == ".mp3"
        assert chunk.path.stat().st_size > 0
        durations.append(probe_audio(chunk.path).duration)

    # mp3-энкодер добавляет ~30–50 мс «прайминга», поэтому допуск 0.15 c.
    assert durations == pytest.approx([2.0, 2.0, 2.0, 1.5], abs=0.15)


def test_split_audio_without_overlap(make_tone, tmp_path) -> None:
    """overlap=0 -> шаг равен длине чанка, 3 куска по 2 c."""
    chunks = split_audio(
        make_tone(6.0),
        tmp_path / "chunks",
        chunk_seconds=2,
        overlap=0.0,
        bitrate="48k",
    )

    assert [c.start for c in chunks] == pytest.approx([0.0, 2.0, 4.0], abs=0.01)
    assert chunks[-1].end == pytest.approx(6.0, abs=0.05)


def test_split_audio_skips_tiny_tail(make_tone, tmp_path) -> None:
    """Хвост короче 1 c не режется отдельным чанком (min_tail)."""
    chunks = split_audio(
        make_tone(6.5),
        tmp_path / "chunks",
        chunk_seconds=2,
        overlap=0.0,
        bitrate="48k",
    )

    assert len(chunks) == 3
    assert chunks[-1].end == pytest.approx(6.0, abs=0.05)


@pytest.mark.parametrize(
    ("chunk_seconds", "overlap"),
    [(0, 0.0), (-1, 0.0), (2, 2.0), (2, 3.0), (2, -0.1)],
)
def test_split_audio_invalid_params(make_tone, tmp_path, chunk_seconds, overlap) -> None:
    """Невалидные chunk_seconds/overlap -> ValueError до вызова ffmpeg."""
    with pytest.raises(ValueError):
        split_audio(
            make_tone(3.0),
            tmp_path / "chunks",
            chunk_seconds=chunk_seconds,
            overlap=overlap,
            bitrate="48k",
        )
