import json
import tempfile
from datetime import datetime
from os import removedirs
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

audio_extension = "mp3"

_BASE_YT_OPTS = {
    "format": "bestaudio/best",
    "forceipv4": True,
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": audio_extension,
            # "quality": "192",
        }
    ],
}

def download_audio(url: str, out_dir: Path | None = None) -> Path | None:
    """_summary_

    Returns:
        _type_: _description_
    """
    if out_dir is None:
        out_dir = Path(tempfile.mkdtemp(prefix=".temp_", dir="./"))
    # out_dir.mkdir(parents=True, exist_ok=True)

    # Making a new dict for yt-dlp out of timestamp and dict unpacking of base options
    # We need just add new outtmlp Path because it will vary between systems
    timestamp = datetime.now().strftime('%Y%m%d%H%M')
    download_options = {
        **_BASE_YT_OPTS, # ** -- dict unpackings
        "outtmpl": str(out_dir / f"{timestamp}_%(title).15B_%(id)s.%(ext)s"),
    }

    try:
        with YoutubeDL(download_options) as ydl:
            # error = ydl.download([url])
            info = ydl.extract_info(url, download=True)
            file_path = Path(ydl.prepare_filename(info)).with_suffix(f".{audio_extension}")
    except DownloadError as error:
        print(f"Download failed: {error}")
        return None

    return file_path
    # video_id = info["id"]

    # for debug -- writing parsed info into json
    # with open("info.json", "w", encoding="utf-8") as f:
    #     json.dump(info, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":

    # url = "https://www.youtube.com/watch?v=9RJml41PFnc"
    url = "https://www.youtube.com/watch?v=qkxf583t4Vc&pp=ugUHEgVlbi1VUw%3D%3D"
    download_audio(url)

    # TODO:
    # [x] Создание временной директории
    # [x] Положить файл во временную директорию
    # [x] Вернуть путь к файлу
    # [ ] Sanitizing filenames
    # [ ] Deleting temp files
