import json
from pathlib import Path

import httpx

from lec_to_text.config import Settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# https://api.groq.com/openai/v1

settings = Settings.from_env()

# language = settings.asr_language
language = 'en'
model = settings.asr_model

api_key = settings.groq_api_key
# TEST
if api_key is None or api_key == "":
    raise ValueError("Не удалось считать API-ключ. Проверьте .env")

response_format = "verbose_json" #  json, text, verbose_json
temperature = 0

file_path = PROJECT_ROOT / "output/part90_test.mp3"
url = f"{settings.groq_base_url}/audio/transcriptions"
# TEST

with httpx.Client(timeout=120) as client:
    with open(file_path, "rb") as file:
        response = client.post(
            url,
            # OpenAI совместимый API
            headers={
                "Authorization": f"Bearer {api_key}",
            },
            data={
                "model": model,
                "language": language,
                "temperature": str(temperature),
                "response_format": response_format
            },
            files={"file": (file_path.name, file, "audio/mpeg")}
        )
        print(response.status_code)

if response.status_code != 200:
    raise RuntimeError(f"Groq вернул {response.status_code}: {response.text[:300]}...")

resp_dump = response.json()

with open(f"{PROJECT_ROOT}/tmp/response.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(resp_dump, ensure_ascii=False, indent=2))
