import torch
from transformers import pipeline

# import dotenv

MODEL_NAME = "openai/whisper-large-v3"

device = 0 if torch.cuda.is_available() else "cpu"

pipe = pipeline(
    task="automatic-speech-recognition",
    model=MODEL_NAME,
    chunk_length_s=30,
    device=device,
)
