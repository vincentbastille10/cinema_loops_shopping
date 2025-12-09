from pydub import AudioSegment
from pathlib import Path

# 🔧 Dossier parent qui contient "Cinema loop", "Horor Loop", "Greys_anatomy", "TikTok Loop"
BASE_FOLDER = Path("/Users/vincent/chemin/vers/TON_DOSSIER_LOOPS")  # <-- à adapter UNE fois

CINEMA_FOLDER = BASE_FOLDER / "Cinema loop"
HORROR_FOLDER = BASE_FOLDER / "Horor Loop"
GREYS_FOLDER = BASE_FOLDER / "Greys_anatomy"


PREVIEW_FOLDER = Path("static/previews")
PREVIEW_FOLDER.mkdir(parents=True, exist_ok=True)

DURATION_MS = 5000   # 5 secondes
FADE_MS = 300        # fade in/out léger 300 ms


def make_preview(wav_path: Path):
    # ex: greys_anatomy_style_emotional_audio_12.wav
    base = wav_path.stem
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
    if not folder.exists():
        print(f"[WARN] Dossier introuvable : {folder}")
        return
    for f in sorted(folder.glob("*.wav")):
        make_preview(f)


if __name__ == "__main__":
    for folder in (CINEMA_FOLDER, HORROR_FOLDER, GREYS_FOLDER, TIKTOK_FOLDER):
        process_folder(folder)

    print("✅ Terminé : tous les previews MP3 ont été générés.")
