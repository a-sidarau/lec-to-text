import json

from datetime import datetime
from pathlib import Path

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


timestamp = datetime.now().strftime('%Y%m%d%H%M')

_DEFAULT_OPTS = {
    "format": "bestaudio/best",
    "forceipv4": True,
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            # "quality": "192",
        }
    ],
    "outtmpl": f"{timestamp}_%(title).15B_%(id)s.%(ext)s",
}

def download_audio(url: str, out_dir: Path = Path("./.temp")) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with YoutubeDL(_DEFAULT_OPTS) as ydl:
            # error = ydl.download([url])
            info = ydl.extract_info(url, download=True)
    except DownloadError as error:
        print(f"Download failed: {error}")

    video_id = info["id"]

    # for debug -- writing parsed info into json
    # with open("info.json", "w", encoding="utf-8") as f:
    #     json.dump(info, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":

    url = "https://www.youtube.com/watch?v=9RJml41PFnc"
    download_audio(url)
