"""Тесты выбора папки для скачивания (без сети)."""

from __future__ import annotations

from lec_to_text import AudioDownloader, Settings


def test_keep_audio_saves_to_output(tmp_path) -> None:
    """keep_audio=True: аудио скачивается в output_dir и НЕ удаляется."""
    output = tmp_path / "output"
    settings = Settings(output_dir=output, keep_audio=True)

    downloader = AudioDownloader(settings)
    workdir = downloader._prepare_workdir(None)

    assert workdir == output
    assert workdir.exists()

    downloader.cleanup()
    assert workdir.exists(), "output_dir пользователя нельзя удалять"


def test_keep_audio_false_uses_temp_dir(tmp_path) -> None:
    """keep_audio=False: временная папка создаётся и удаляется в cleanup()."""
    settings = Settings(
        output_dir=tmp_path / "output",
        keep_audio=False,
        temp_dir=tmp_path / "tmp",
    )

    downloader = AudioDownloader(settings)
    workdir = downloader._prepare_workdir(None)

    assert workdir.name.startswith("lec2text_")
    assert workdir.exists()

    downloader.cleanup()
    assert not workdir.exists()


def test_explicit_out_dir_is_not_deleted(tmp_path) -> None:
    """Явно переданный out_dir используется как есть и не удаляется."""
    settings = Settings(output_dir=tmp_path / "output", keep_audio=True)
    custom = tmp_path / "custom"

    downloader = AudioDownloader(settings)
    workdir = downloader._prepare_workdir(custom)

    assert workdir == custom
    downloader.cleanup()
    assert custom.exists()


def test_local_file_skips_download(tmp_path) -> None:
    """Локальный файл возвращается как есть, без обращения к yt-dlp."""
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"fake")

    settings = Settings(output_dir=tmp_path / "output")
    downloader = AudioDownloader(settings)
    result = downloader.download(str(source))

    assert result.audio_path == source.resolve()
    assert result.metadata.extractor == "local"
    assert result.metadata.title == "lecture"
