#!/usr/bin/env python3
"""低延遲中英字幕（sherpa-onnx 串流識別 + 可選 Gemini 翻譯）

用法:
  captions_live.py               # 麥克風即時（預設 zipformer fp32）
  captions_live.py --model para  # 改用 paraformer
  captions_live.py --file x.wav  # 檔案 1x 測試

環境變數:
  GEMINI_API_KEY  有設就加英譯（建議 gemini-2.5-flash-lite，免費額度較高）
"""
import argparse, json, os, queue, sys, threading, time, wave
import urllib.request

import numpy as np
import sherpa_onnx

BASE = os.path.dirname(os.path.abspath(__file__))
MODELS = {
    "zipformer": (f"{BASE}/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
                  "encoder-epoch-99-avg-1", "decoder-epoch-99-avg-1", "joiner-epoch-99-avg-1"),
    "para": (f"{BASE}/sherpa-onnx-streaming-paraformer-bilingual-zh-en",
             "encoder", "decoder", None),
}


def gemini_translate(text, key, model):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = json.dumps({
        "systemInstruction": {"parts": [{"text":
            "Translate the Chinese presentation transcript into concise, natural English "
            "for live subtitles. Fix obvious homophone transcription errors using context. "
            "Keep technical terms (Whisper, CPU, GPU, model names) as-is. "
            "Output ONLY the translation."}]},
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 256},
    }).encode()
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        out = json.load(r)
    return out["candidates"][0]["content"]["parts"][0]["text"].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="zipformer", choices=list(MODELS))
    ap.add_argument("--file")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    d, enc, dec, jn = MODELS[args.model]

    rec = sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=f"{d}/tokens.txt",
        encoder=f"{d}/{enc}.onnx",   # fp32：實測無重複問題（int8 會重字）
        decoder=f"{d}/{dec}.onnx",
        joiner=f"{d}/{jn}.onnx" if jn else None,
        num_threads=4, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search", provider="cpu",
        rule2_min_trailing_silence=0.7,   # 停頓 0.7s 切句
        rule3_min_utterance_length=8,     # 連講 8s 強制切句
    ) if args.model == "zipformer" else sherpa_onnx.OnlineRecognizer.from_paraformer(
        tokens=f"{d}/tokens.txt",
        encoder=f"{d}/{enc}.onnx",
        decoder=f"{d}/{dec}.onnx",
        num_threads=4, sample_rate=16000, feature_dim=80,
        decoding_method="greedy_search", provider="cpu",
        rule2_min_trailing_silence=0.7,
        rule3_min_utterance_length=8,
    )

    tr_q = queue.Queue()

    def translator():
        while True:
            item = tr_q.get()
            if item is None:
                break
            text, t_speech_end = item
            if not api_key:
                continue
            try:
                t0 = time.time()
                en = gemini_translate(text, api_key, gemini_model)
                dt = time.time() - t0
                print(f"\033[1m  EN  {en}\033[0m", flush=True)
                if t_speech_end:
                    print(f"\033[2m     [語音結束後 {time.time()-t_speech_end:.1f}s]\033[0m", flush=True)
            except Exception as e:
                print(f"  [翻譯失敗: {e}]", flush=True)

    threading.Thread(target=translator, daemon=True).start()

    def on_segment(text, t_end):
        text = text.strip()
        if not text:
            return
        print(f"\033[36mZH  {text}\033[0m", flush=True)
        tr_q.put((text, t_end))

    stream = rec.create_stream()

    seg_state = {"silence": 0, "chunks": 0}

    def process(x, t_end=None):
        stream.accept_waveform(16000, x)
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        text = rec.get_result(stream)
        if text:
            print(f"\r\033[2m… {text[-48:]}  \033[0m", end="", flush=True)
        rms = float(np.sqrt(np.mean(x * x)))
        seg_state["chunks"] += 1
        seg_state["silence"] = seg_state["silence"] + 1 if rms < 0.02 else 0
        # 0.5s 靜音或連講 8s → 斷句（不依賴 sherpa endpoint）
        if text and (seg_state["silence"] >= 5 or seg_state["chunks"] >= 80):
            on_segment(text, t_end)
            rec.reset(stream)
            seg_state.update(silence=0, chunks=0)
            print(f"\r\033[2m{' '*50}\033[0m", end="\r", flush=True)

    if args.file:
        wf = wave.open(args.file, "rb")
        rate = wf.getframerate()
        t0 = time.time()
        while True:
            raw = wf.readframes(rate // 10)
            if not raw:
                break
            x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
            if rate != 16000:
                n = int(len(x) * 16000 / rate)
                x = np.interp(np.linspace(0, len(x) - 1, n),
                              np.arange(len(x)), x).astype(np.float32)
            process(x, time.time() - t0)
            time.sleep(0.1)  # 1x 即時模擬
        stream.input_finished()
        while rec.is_ready(stream):
            rec.decode_stream(stream)
        on_segment(rec.get_result(stream), None)
    else:
        import pyaudio
        pa = pyaudio.PyAudio()
        st = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                     input=True, frames_per_buffer=1600)
        tag = " + Gemini 英譯" if api_key else "（未設 GEMINI_API_KEY：只出中文）"
        print(f"[字幕啟動] {args.model}{tag} · Ctrl-C 結束", flush=True)
        try:
            while True:
                x = np.frombuffer(st.read(1600), np.int16).astype(np.float32) / 32768.0
                process(x)
        except KeyboardInterrupt:
            pass
        finally:
            st.stop_stream(); st.close(); pa.terminate()
    tr_q.put(None)


if __name__ == "__main__":
    main()
