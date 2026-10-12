# lec_to_text

Локальная утилита: **ссылка/файл → скачать видео → извлечь аудио → распознать в текст**.
Текущая реализация покрывает загрузку и аудио-препроцессинг (фазы 0–3).
ASR/экспорт/CLI добавляются поверх этих модулей.

## Что уже есть

| Модуль | Назначение |
|---|---|
| `config.py` | Настройки из `.env`/окружения (`Settings`). |
| `inputs.py` | Классификация входа: локальный файл / YouTube / другая ссылка. |
| `downloader.py` | Устойчивое скачивание аудио через yt-dlp (PO Token, cookies, impersonation, фолбэк клиентов). |
| `audio.py` | Извлечение/конвертация аудио через ffmpeg/ffprobe (`to_asr_wav`). |
| `errors.py` | Типизированные ошибки + классификатор ошибок скачивания. |

## Требования

- Python **>= 3.12** (у вас 3.14 — ок).
- **ffmpeg + ffprobe** в `PATH`.
- **deno >= 2.3** в `PATH` — нужен yt-dlp для решения JS-задач YouTube.
- Пакет **curl_cffi** (ставится зависимостью) — для impersonation.

Проверка:

```bash
ffmpeg -version
deno --version
```

## Установка

```bash
uv sync                 # создаст/обновит .venv и поставит зависимости
cp .env.example .env     # при необходимости поправьте настройки
```

## Быстрый старт

```bash
# после uv sync активируйте venv:
source .venv/bin/activate

# скачать -> получить WAV 16 kHz mono
python -m lec_to_text.main "https://youtu.be/XXXXXXXXXXX"
python -m lec_to_text.main "/path/to/lecture.mp4"
```

Или из кода:

```python
from lec_to_text import AudioDownloader, Settings, to_asr_wav

settings = Settings.from_env()
with AudioDownloader(settings) as dl:  # аудио сохраняется в output/
    result = dl.download("https://youtu.be/XXXXXXXXXXX")
    print(result.title, result.duration)

    wav = to_asr_wav(result.audio_path, settings=settings)
    # wav (тоже в output/) -> отдаём в ваш ASR-бэкенд
```

## Настройка `.env`

Смотрите `.env.example` — там все параметры с комментариями. Ключевые:

- `LEC2TEXT_PLAYER_CLIENTS` — порядок YouTube-клиентов для фолбэка.
- `LEC2TEXT_COOKIES_FROM_BROWSER` — cookies из браузера (часто решает bot-check).
- `LEC2TEXT_IMPERSONATE` — подмена TLS-отпечатка (по умолчанию `chrome`).
- `LEC2TEXT_PROXY` — прокси, если ваш IP заблокирован.
- `LEC2TEXT_KEEP_AUDIO` — `true` (по умолчанию): аудио сохраняется в `output/`;
  `false`: скачивание во временную папку с удалением после обработки.
- `LEC2TEXT_ASR_SAMPLE_RATE` / `LEC2TEXT_ASR_CHANNELS` — формат аудио для ASR.

## Troubleshooting 403 / «Sign in to confirm you're not a bot»

Пробуйте по порядку:

1. **Обновите yt-dlp** — YouTube меняется часто:
   ```bash
   uv sync --upgrade-package yt-dlp
   ```
2. **impersonation** — уже включён (`LEC2TEXT_IMPERSONATE=chrome`); убедитесь, что
   установлен `curl-cffi` (`uv sync`).
3. **Cookies из браузера** — самый простой способ пройти бот-проверку:
   ```env
   LEC2TEXT_COOKIES_FROM_BROWSER=firefox
   # или: chrome, chromium, "chrome:Profile 1"
   ```
   Для Chrome на Linux может понадобиться разблокировать keyring:
   `LEC2TEXT_COOKIES_FROM_BROWSER=chrome+gnomekeyring`.
4. **Смените цепочку клиентов**:
   ```env
   LEC2TEXT_PLAYER_CLIENTS=mweb,android_vr,tv,web_safari
   ```
5. **PO Token Provider** (рекомендация yt-dlp) — если ничего не помогло.
   Он требует отдельный сервер/скрипт (Node/Deno или Docker):
   - репозиторий: `github.com/Brainicism/bgutil-ytdlp-pot-provider`;
   - быстрый старт (Docker):
     ```bash
     docker run --name bgutil-provider -d --init \
       -p 127.0.0.1:4416:4416 brainicism/bgutil-ytdlp-pot-provider
     ```
   - затем поставьте плагин в тот же Python-интерпретатор:
     ```bash
     uv pip install bgutil-ytdlp-pot-provider
     ```
   Плагин сам подхватится yt-dlp — менять код не нужно.
6. **Прокси** (`LEC2TEXT_PROXY`), если IP помечен как «бот».

## Что дальше (фазы 4+)

- **ASR:** по умолчанию для длинных лекций — Groq API (`GROQ_API_KEY`, free tier,
  чанкинг ≤ 25 MB); фолбэк/офлайн — локальный `faster-whisper` (`large-v3-turbo`, int8).
- **Экспорт:** TXT / SRT / VTT / Markdown.
- **CLI:** `lec-to-text transcribe <URL|PATH> --backend auto|local|groq --lang ru`.

## Заметки по надёжности

- Локальный файл скачивать не нужно: `downloader` распознаёт путь и просто
  возвращает его как `DownloadResult`.
- Аудио в yt-dlp не перекодируется: `audio.to_asr_wav` делает 16 kHz mono.
- По умолчанию аудио сохраняется в `output/` (`LEC2TEXT_KEEP_AUDIO=true`).
  При `keep_audio=false` используется временная папка, которая удаляется в
  `AudioDownloader.cleanup()` (или автоматически через `with`).
- Повторный запуск для того же видео переиспользует уже скачанный файл:
  yt-dlp не перезаписывает существующий (`overwrites=False`).
