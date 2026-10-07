from pathlib import Path
import sys, time
from whisper_live.client import TranscriptionClient

c = TranscriptionClient(
    "localhost", 9090,
    lang="zh", translate=True, model=sys.argv[1] if len(sys.argv) > 1 else "medium",
    mute_audio_playback=True,
    hotwords="Whisper,CPU,低延遲",
    initial_prompt=None,
)
t0 = time.time()
c(str(Path(__file__).resolve().parents[2] / "fixtures" / "test_zh.wav"))
print(f"\n[total {time.time()-t0:.1f}s]")
