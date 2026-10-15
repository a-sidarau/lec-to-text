# AGENTS.md

Инструкции для AI-агентов и разработчиков, работающих в репозитории `lec_to_text`.

## О проекте

Локальная утилита: **ссылка/файл → скачать аудио → распознать в текст** (позже —
опциональная суммаризация через LLM). Персональный инструмент для транскрибации
лекций (в основном русский язык, длительность 1–2 часа).

## Стек и окружение

- Python **>= 3.12** (фактически 3.14.7), менеджер — **uv**.
- Зависимости: `yt-dlp[default]` (+ `yt-dlp-ejs`), `curl-cffi`, `python-dotenv`,
  `transformers` (задел под ASR-фазу).
- Системные требования: **ffmpeg/ffprobe** и **deno >= 2.3** в `PATH`.
- Машина — **CPU-only**. GPU нет.

## Команды

```bash
uv sync                                       # установка/обновление зависимостей
uv run pytest -q                              # тесты
uv run ruff check . && uv run ruff format .   # линт/формат
uv run python -m lec_to_text.main "<URL|PATH>"    # демо download + audio
uv sync --upgrade-package yt-dlp              # обновить yt-dlp (важно для YouTube)
```

Альтернатива, если venv активирован: `.venv/bin/python -m pytest -q`.

## Структура проекта

```
src/lec_to_text/
  config.py       # Settings: все настройки из .env (см. .env.example)
  inputs.py       # классификация входа: local file / YouTube / remote URL
  downloader.py   # AudioDownloader (yt-dlp): анти-403, метаданные, output/temp
  audio.py        # ffmpeg/ffprobe: probe_audio, extract_audio, to_asr_wav
  errors.py       # иерархия ошибок + classify_download_error
  transcriber.py  # [план/прототип] Protocol Transcriber + Segment/TranscriptResult
  groq_backend.py # [план] GroqTranscriber (API, чанкинг)
  storage.py      # [план] экспорт txt/srt/vtt/md
  cli.py          # [план] CLI
tests/            # pytest, офлайн-тесты (без сети)
```

## Архитектура и ключевые решения

- Пайплайн: `Input Resolver → Downloader → Audio → Transcriber → Storage`.
  Каждая стадия — отдельный модуль с ясным интерфейсом.
- **Аудио сохраняется в `output/`** (`Settings.keep_audio=True` по умолчанию);
  при `keep_audio=False` используется временная папка с автоочисткой.
  Скачанный нативный файл (`.webm/.m4a`) и `*.16k.wav` лежат рядом в `output/`.
- Повторный запуск того же видео **не перекачивает** файл (`overwrites=False`).
- **ASR по умолчанию: Groq API**, модель `whisper-large-v3-turbo` (переключаемая).
  Лимиты free tier: **25 MB/файл, 20 RPM, 2000 RPD** → обязателен чанкинг
  (20-мин mp3 48 kbps ≈ 7 MB, перекрытие 1–2 с, склейка таймстемпов со сдвигом).
- **Русский язык** → используем только семейство Whisper
  (Parakeet/Moonshine/Vosk не подходят). Локальный `faster-whisper` — только
  как будущий фолбэк для приватного/офлайн-аудио (сейчас — только интерфейс).
- Форматы вывода: **TXT / SRT / VTT / Markdown**.
- Приватные лекции нельзя отправлять в API — для них предусмотреть локальный режим.

## Соглашения по коду

- Комментарии и докстринги — **на русском**, объясняют «что и зачем», а не только «что».
- `from __future__ import annotations`, полные type hints, dataclasses.
- Стиль: `ruff`, длина строки 100. Перед коммитом — `ruff check` + `pytest`.
- Секреты только через `.env` (в git не попадает); в коде — `Settings`.
- Не хардкодить пути к бинарям и внешние URL — брать из `Settings`/PATH.
- Не удалять «обвес» yt-dlp (js_runtimes, impersonation, цепочка player_client,
  cookies) — он закрывает 403/bot-check на YouTube.

## Грабли и ограничения

- **YouTube 403 / bot-check**: не вызывать голый `yt-dlp`; ошибки
  типизируются в `errors.py`. Диагностика — README → Troubleshooting 403.
- **Не коммитить**: `output/`, `.env`, `info.json`, временные `lec2text_*/`, `*.srt`, `*.vtt`.
- `windowsfilenames=True`: двоеточие в заголовках заменяется на `：` (норма).
- Длинное аудио: 2 ч WAV 16 kHz mono ≈ **230 MB** — API-лимит 25 MB требует нарезки.
- Локальный ASR на CPU медленный (2 ч лекция ≈ 2–4 ч) — поэтому API основной режим.
- Часть ML-стека имеет колёса под Python 3.14 — проверять перед добавлением зависимостей.

## Статус и роадмап

- ✅ Фазы 0–3: каркас, конфиг, downloader (аудио в `output/`), аудио-препроцессинг.
- ⏳ Фаза 4: ASR-бэкенд Groq (`transcriber.py`, `groq_backend.py`, `split_audio`).
- ⏳ Фаза 5: оркестрация/маршрутизация (`auto`: длинное → API, короткое/приватное → local).
- ⏳ Фаза 6: CLI. ⏳ Фаза 7: storage (txt/srt/vtt/md).
- ⏳ Фаза 8: тесты/документация. ⏳ Фаза 9: суммаризация (future).

## Definition of Done

- Изменение покрыто оффлайн-тестами (`pytest`), `ruff` проходит.
- Новые настройки задокументированы в `.env.example` и README.
- Сетевые вызовы не выполняются в тестах (мокаются).
