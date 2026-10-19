"""Иерархия исключений проекта.

Зачем это нужно: разные сбои требуют разной реакции. Например:
- ``403 Forbidden`` на YouTube часто лечится сменой клиента player_client,
  поэтому downloader ловит этот тип и пробует следующий клиент;
- «видео приватное» или «недоступно в стране» сменой клиента не исправишь —
  такие ошибки нужно сразу пробрасывать пользователю;
- ошибки ffmpeg — это уже про локальное окружение, а не про сеть.

Поэтому downloader по тексту ошибки yt-dlp определяет точный тип через
:func:`classify_download_error`.
"""

from __future__ import annotations


class Lec2TextError(Exception):
    """Базовое исключение проекта (ловить его — значит поймать всё наше)."""


# ---------------------------------------------------------------------------
# Входные данные
# ---------------------------------------------------------------------------
class InputError(Lec2TextError):
    """Некорректный вход: битая ссылка, несуществующий путь и т.п."""


class UnsupportedInputError(InputError):
    """Вход распознан, но такой тип источника мы не поддерживаем."""


# ---------------------------------------------------------------------------
# Скачивание
# ---------------------------------------------------------------------------
class DownloadError(Lec2TextError):
    """Общая ошибка скачивания."""


class DownloadForbiddenError(DownloadError):
    """HTTP 403 Forbidden.

    На YouTube это чаще всего «протухший» URL потока или отсутствие PO Token.
    Обычно лечится повторной попыткой с другим player_client / PO Token.
    """


class BotCheckError(DownloadError):
    """YouTube требует «Sign in to confirm you're not a bot».

    Требуются cookies и/или PO Token (или другой IP).
    """


class GeoRestrictedError(DownloadError):
    """Видео недоступно в вашем регионе (нужен прокси)."""


class PrivateVideoError(DownloadError):
    """Видео приватное / требует входа / удалено — сменой клиента не лечится."""


class NetworkError(DownloadError):
    """Сетевой сбой (таймаут, обрыв соединения, DNS)."""


class UnsupportedSiteError(DownloadError):
    """yt-dlp не знает, как обработать этот URL."""


# ---------------------------------------------------------------------------
# Медиа-инструменты (ffmpeg/ffprobe)
# ---------------------------------------------------------------------------
class MediaToolError(Lec2TextError):
    """Проблема с внешним инструментом: не найден, упал и т.п."""


class AudioConversionError(MediaToolError):
    """Не удалось конвертировать/извлечь аудио."""


# ---------------------------------------------------------------------------
# Транскрибация
# ---------------------------------------------------------------------------


class TranscriptionError(Lec2TextError):
    """Ошибка транскрибации текста (внешним или локлаьным)"""


class AsrAuthError(TranscriptionError):
    """Неверный ключ.ошибка аутентификации"""


class AsrApiError(TranscriptionError):
    """Временный сбой API"""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AsrResponseError(TranscriptionError):
    """Ошибка при получении ответа от провайдера"""


class AsrRequestError(TranscriptionError):
    """Неверный запрос"""


# ---------------------------------------------------------------------------
def classify_download_error(exc: BaseException) -> DownloadError:
    """Определяет точный тип ошибки скачивания по тексту сообщения yt-dlp.

    yt-dlp не даёт типизированных исключений для разных причин, поэтому
    мы сопоставляем подстроки. Возвращаемое исключение можно смело бросать
    (``raise``) — в него уже вложен исходный текст.
    """
    text = str(exc).lower()

    # Порядок проверок важен: сначала более специфичные причины.
    if "sign in to confirm you're not a bot" in text or "confirm you're not a bot" in text:
        return BotCheckError(str(exc))

    if "private video" in text or "this video is private" in text:
        return PrivateVideoError(str(exc))

    if "login required" in text or "sign in" in text and "cookies" in text:
        return PrivateVideoError(str(exc))

    if (
        "not available in your country" in text
        or "geo" in text
        or "blocked in your country" in text
    ):
        return GeoRestrictedError(str(exc))

    if "unsupported url" in text or "no suitable extractor" in text:
        return UnsupportedSiteError(str(exc))

    if "http error 403" in text or "forbidden" in text:
        return DownloadForbiddenError(str(exc))

    if any(
        k in text
        for k in (
            "timed out",
            "timeout",
            "connection",
            "temporary failure",
            "network is unreachable",
            "getaddrinfo",
            "ssl",
        )
    ):
        return NetworkError(str(exc))

    return DownloadError(str(exc))
