from pathlib import Path
import sys
import subprocess, wave

BASE = Path(__file__).resolve().parent

sents = [
    "大家好，今天很高興跟各位分享我們團隊最新的研究成果。",
    "過去三年，我們專注於開發一套即時語音翻譯系統，讓講者可以用自己的母語演講，而觀眾看到的是英文字幕。",
    "這套系統完全在本地運作，不需要網路連線，也不會把你的聲音上傳到雲端。",
    "接下來我會示範幾個實際的應用場景，包括學術演講與技術分享。",
    "我們採用 Whisper 模型，在十二核心的 CPU 上面，實現了低延遲的語音辨識。",
    "最後，歡迎大家隨時提出問題，謝謝大家。",
]

parts = []
for i, s in enumerate(sents):
    f = f"/tmp/sent_{i}.wav"
    subprocess.run([str(Path(sys.executable).with_name("piper")), "-m",
                    str(BASE / "zh_CN-huayan-medium.onnx"), "-f", f],
                   input=s.encode(), check=True)
    parts.append(f)

out = wave.open(str(BASE / "test_zh_paused.wav"), "wb")
first = wave.open(parts[0])
out.setnchannels(first.getnchannels()); out.setsampwidth(first.getsampwidth())
out.setframerate(first.getframerate())
silence = b"\x00" * int(first.getframerate() * 0.6) * first.getsampwidth() * first.getnchannels()
for j, f in enumerate(parts):
    w = wave.open(f)
    out.writeframes(w.readframes(w.getnframes()))
    if j < len(parts) - 1:
        out.writeframes(silence)
out.close()
print("done")
