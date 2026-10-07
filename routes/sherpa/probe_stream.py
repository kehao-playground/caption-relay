from pathlib import Path
import sys, time, wave
import numpy as np
import sherpa_onnx

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / "models" / "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20"
rec = sherpa_onnx.OnlineRecognizer.from_transducer(
    tokens=f"{D}/tokens.txt",
    encoder=f"{D}/encoder-epoch-99-avg-1.int8.onnx",
    decoder=f"{D}/decoder-epoch-99-avg-1.int8.onnx",
    joiner=f"{D}/joiner-epoch-99-avg-1.int8.onnx",
    num_threads=4, sample_rate=16000, feature_dim=80,
    decoding_method="greedy_search", provider="cpu",
    rule2_min_trailing_silence=0.7,  # 說話後 0.7s 靜音即切句
    rule3_min_utterance_length=8,    # 連續講超過 8s 強制切句，避免重複迴圈
)
stream = rec.create_stream()

wf = wave.open(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "fixtures" / "test_zh.wav"), "rb")
rate = wf.getframerate()
last, max_dt = 0.0, 0.0
t0 = time.time()
while True:
    raw = wf.readframes(rate // 10)  # 100ms
    if not raw:
        break
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if rate != 16000:
        n = int(len(x) * 16000 / rate)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    stream.accept_waveform(16000, x)
    t = time.time()
    while rec.is_ready(stream):
        rec.decode_stream(stream)
    max_dt = max(max_dt, time.time() - t)
    text = rec.get_result(stream)
    now = time.time() - t0
    if text and now - last > 0.5:
        print(f"\r… {text[-48:]}  ", end="", flush=True)
        last = now
    if rec.is_endpoint(stream):
        print(f"\r[{now:5.1f}s] {text}", flush=True)
        stream.reset()
stream.input_finished()
while rec.is_ready(stream):
    rec.decode_stream(stream)
text = rec.get_result(stream)
if text:
    print(f"[{time.time()-t0:5.1f}s] {text}", flush=True)
print(f"[單輪解碼上限 {max_dt*1000:.0f}ms（須 <100ms 才即時）]", flush=True)
