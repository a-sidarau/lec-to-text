"""Пример использования модулей скачивания и конвертации (фазы 0–3).

Запуск::

    python -m lec_to_text.main "https://youtu.be/XXXXXXXXXXX"
    python -m lec_to_text.main "/путь/к/лекции.mp4"

Это только демонстрация: скачали аудио -> привели к WAV 16 kHz mono.
Дальше (ASR, экспорт, CLI) дописывается самостоятельно.
"""

from __future__ import annotations

import logging
import sys

from .audio import to_asr_wav
from .config import Settings
from .downloader import AudioDownloader


def main(source: str) -> None:
    # Единая точка настройки логирования для примера.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    settings = Settings.from_env()
    settings.ensure_dirs()

    # AudioDownloader — контекстный менеджер: сам уберёт временные файлы.
    with AudioDownloader(settings) as downloader:
        result = downloader.download(source)

        print(f"Источник:      {result.kind.value}")
        print(f"Название:      {result.title}")
        print(f"Длительность:  {result.duration} c")
        print(f"Скачанное аудио: {result.audio_path}")

        # Канонический WAV для ASR (любой вход -> 16 kHz mono).
        wav_path = to_asr_wav(result.audio_path, settings=settings)
        print(f"Аудио для ASR:  {wav_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Использование: python -m lec_to_text.main "<URL|путь>"')
        raise SystemExit(2)
    main(sys.argv[1])
