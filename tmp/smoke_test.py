import re

import httpx

from lec_to_text.audio import split_audio, to_asr_wav
from lec_to_text.config import Settings
from lec_to_text.downloader import AudioDownloader
from lec_to_text.groq_backend import request_with_retries

if __name__ == "__main__":
    # Setup
    settings = Settings.from_env()
    output_dir = settings.output_dir
    settings.ensure_dirs()

    api_key = settings.groq_api_key
    if api_key is None or api_key == "":
        raise SystemExit("Не удалось считать API-ключ. Проверьте .env")
    video_url = "https://youtu.be/2xNwgReZH4A"
    asr_url = f"{settings.groq_base_url}/audio/transcriptions"
    language = "ru"

    # Downloading
    with AudioDownloader(settings) as dl:
        audio = dl.download(video_url)  # Path

    # Chunking
    converted_audio_file = to_asr_wav(audio.audio_path, settings=settings)
    chunks = split_audio(
        src=converted_audio_file,
        dst_dir=output_dir,
        chunk_seconds=settings.chunk_seconds,
        overlap=settings.chunk_overlap,
        bitrate=settings.chunk_bitrate,
    )  # list[AudioChunk]

    # Transcribing
    texts: list[str] = []
    with httpx.Client(timeout=settings.request_timeout) as client:
        for chunk in chunks:
            resp = request_with_retries(
                client=client,
                file_path=chunk.path,
                url=asr_url,
                api_key=api_key,
                model=settings.asr_model,
                language=language,
                max_attempts=settings.asr_max_attempts,
                base_delay=settings.asr_retry_base_delay,
            )
            texts.append(resp.get("text", "").strip())

    # Saving output
    result = " ".join(t for t in texts if t)
    result = " ".join(result.split())

    if not result:
        raise SystemExit("Все чанки вернули пустой текст - проверьте язык/модель/аудио")

    safe_title = re.sub(r'[\\/:*?"<>|]+', "_", (audio.title or "")[:80]).strip()
    output_file = output_dir / f"{audio.video_id or 'audio'}_{safe_title}.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(result)

    print("Итоговый файл:", output_file)
