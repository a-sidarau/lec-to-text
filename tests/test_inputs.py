"""Тесты распознавания входа (без сети)."""

from __future__ import annotations

import pytest

from lec_to_text import InputKind, UnsupportedInputError, is_youtube, resolve


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
        "https://m.youtube.com/watch?v=abc123",
        "https://music.youtube.com/watch?v=abc123",
        "https://youtube-nocookie.com/embed/abc123",
    ],
)
def test_is_youtube_true(url: str) -> None:
    assert is_youtube(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://vimeo.com/12345",
        "https://example.com/watch?v=abc",
        # Похожий, но не YouTube домен (защита от youtube.com.evil.example).
        "https://youtube.com.evil.example/watch?v=abc",
    ],
)
def test_is_youtube_false(url: str) -> None:
    assert is_youtube(url) is False


def test_resolve_youtube() -> None:
    result = resolve("https://youtu.be/abc123")
    assert result.kind is InputKind.YOUTUBE
    assert result.url == "https://youtu.be/abc123"
    assert result.path is None


def test_resolve_remote_url() -> None:
    result = resolve("https://example.com/video.mp4")
    assert result.kind is InputKind.REMOTE_URL


def test_resolve_local_file(tmp_path) -> None:
    file = tmp_path / "lecture.mp4"
    file.write_bytes(b"fake")
    result = resolve(str(file))
    assert result.kind is InputKind.LOCAL_FILE
    assert result.path == file.resolve()


def test_resolve_missing_path_raises() -> None:
    with pytest.raises(UnsupportedInputError):
        resolve("/no/such/file/here.mp4")


def test_resolve_empty_raises() -> None:
    with pytest.raises(UnsupportedInputError):
        resolve("   ")
