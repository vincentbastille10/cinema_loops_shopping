from pydub import AudioSegment
import os
from pathlib import Path

# adapte ces chemins si besoin
CINEMA_FOLDER = Path("/Users/vincent/chemin/vers/Cinema loop")
HORROR_FOLDER = Path("/Users/vincent/chemin/vers/Horor Loop")

PREVIEW_FOLDER = Path("static/previews")
PREVIEW_FOLDER.mkdir(parents=True, exist_ok=True)

DURATION_MS = 5000      # 5 secondes
FADE_MS = 300           # fade in/out léger 300 ms

def make_preview(wav_path: Path):
    base = wav_path.stem              # ex: Horror_loop_1
    out_mp3 = PREVIEW_FOLDER / f"{base}.mp3"

    if out_mp3.exists():
        print(f"[SKIP] {out_mp3} existe déjà")
        return

    audio = AudioSegment.from_file(wav_path)
    if len(audio) <= DURATION_MS:
        segment = audio
    else:
        start = (len(audio) - DURATION_MS) // 2
        end = start + DURATION_MS
        segment = audio[start:end]

    segment = segment.fade_in(FADE_MS).fade_out(FADE_MS)
    segment.export(out_mp3, format="mp3", bitrate="128k")
    print(f"[OK] {wav_path.name} -> {out_mp3}")

def process_folder(folder: Path):
    for f in sorted(folder.glob("*.wav")):
        make_preview(f)

if __name__ == "__main__":
    process_folder(CINEMA_FOLDER)
    process_folder(HORROR_FOLDER)
