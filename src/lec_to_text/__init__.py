from __future__ import annotations

from .audio import AudioInfo, AudioChunk, extract_audio, probe_audio, to_asr_wav, split_audio
from .config import Settings
from .downloader import (
    AudioDownloader,
    DownloadResult,
    MediaMetadata,
    download_audio,
)
from .errors import (
    AudioConversionError,
    BotCheckError,
    DownloadError,
    DownloadForbiddenError,
    GeoRestrictedError,
    InputError,
    Lec2TextError,
    MediaToolError,
    NetworkError,
    PrivateVideoError,
    UnsupportedInputError,
    UnsupportedSiteError,
)
from .inputs import InputKind, ResolvedInput, is_youtube, resolve

__version__ = "0.1.0"

__all__ = [
    "AudioConversionError",
    "AudioDownloader",
    "AudioInfo",
    "AudioChunk",
    "BotCheckError",
    "DownloadError",
    "DownloadForbiddenError",
    "DownloadResult",
    "GeoRestrictedError",
    "InputError",
    "InputKind",
    "Lec2TextError",
    "MediaMetadata",
    "MediaToolError",
    "NetworkError",
    "PrivateVideoError",
    "ResolvedInput",
    "Settings",
    "UnsupportedInputError",
    "UnsupportedSiteError",
    "__version__",
    "download_audio",
    "extract_audio",
    "is_youtube",
    "probe_audio",
    "split_audio",
    "resolve",
    "to_asr_wav",
]
