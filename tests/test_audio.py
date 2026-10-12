"""Тесты аудио-препроцессинга (нужен установленный ffmpeg)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from lec_to_text import Settings, probe_audio, to_asr_wav
from lec_to_text.audio import extract_audio
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
