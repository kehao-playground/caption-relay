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
)
wf = wave.open(sys.argv[1], "rb")
x = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768.0
stream = rec.create_stream()
stream.accept_waveform(16000, x)
t = time.time()
while rec.is_ready(stream):
    rec.decode_stream(stream)
print(f"[{time.time()-t:.2f}s] {rec.get_result(stream)}")
