#!/usr/bin/env python3
"""中→英即時字幕：WhisperLive 中文聽寫（本地）+ Gemini API 文字翻譯（可選）

用法:
  live_zh2en.py                # 麥克風即時模式（上台用）
  live_zh2en.py --file x.wav   # 檔案 1x 串流（測試用）
  live_zh2en.py --file x.wav --latency  # 量測每段延遲

環境變數:
  GEMINI_API_KEY  有設就啟用 Gemini 英譯（沒設只顯示中文稿）
  WL_MODEL        whisper 模型，預設 medium
  GEMINI_MODEL    預設 gemini-2.5-flash
"""
import argparse, json, os, queue, sys, threading, time, wave
import urllib.request

from whisper_live.client import StreamingTranscriptionClient

HOST, PORT = "localhost", 9090


def gemini_translate(text, key, model):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    body = json.dumps({
        "systemInstruction": {"parts": [{"text":
            "Translate the Chinese presentation transcript into concise, natural English "
            "for live subtitles. Keep technical terms as-is. Output ONLY the translation."}]},
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
    ap.add_argument("--file")
    ap.add_argument("--latency", action="store_true")
    args = ap.parse_args()

    api_key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("WL_MODEL", "medium")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    t0 = [None]
    tr_q = queue.Queue()

    def translator():
        while True:
            text, lag = tr_q.get()
            if text is None:
                break
            if not api_key:
                continue
            try:
                ts = time.time() - t0[0]
                en = gemini_translate(text, api_key, gemini_model)
                print(f"\033[1m  EN  {en}\033[0m", flush=True)
                if args.latency:
                    print(f"     [翻譯於語音後 {time.time()-t0[0]-lag:.1f}s + "
                          f"{time.time()-t0[0]-ts:.1f}s]", flush=True)
            except Exception as e:
                print(f"  [翻譯失敗: {e}]", flush=True)

    def on_started():
        t0[0] = time.time()
        tag = "中文聽寫 + Gemini 英譯" if api_key else "中文聽寫（未設 GEMINI_API_KEY，只出中文）"
        print(f"[字幕啟動] model={model} · {tag} · Ctrl-C 結束", flush=True)

    seen, last_key, same_cnt = set(), [None], [0]

    def emit(seg):
        text = seg["text"].strip()
        if not text:
            return
        lag = float(seg["end"]) if seg.get("end") else None
        print(f"\r\033[36mZH  {text}\033[0m", flush=True)
        if args.latency and lag is not None and t0[0]:
            print(f"     [語音結束後 {time.time()-t0[0]-lag:.1f}s 上字幕]", flush=True)
        tr_q.put((text, lag))

    def seg_key(seg):
        return (seg.get("start"), seg.get("end"), seg.get("text"))

    def on_partial(text, segs):
        print(f"\r\033[2m… {text[:60]}\033[0m", end="", flush=True)
        if not segs:
            return
        key = seg_key(segs[-1])
        if key == last_key[0]:
            same_cnt[0] += 1
        else:
            last_key[0], same_cnt[0] = key, 1
        # 本地穩定偵測：尾段連續兩次相同就先上字幕，不等 server 定稿
        if same_cnt[0] >= 2 and key not in seen:
            seen.add(key)
            emit(segs[-1])

    def on_committed(text, segs):
        if segs:
            key = seg_key(segs[0])
            if key not in seen:   # server 慢來的定稿，補發沒上過的
                seen.add(key)
                emit(segs[0])

    client = StreamingTranscriptionClient(
        HOST, PORT, lang="zh", model=model,
        on_session_started=on_started,
        on_partial_transcript=on_partial,
        same_output_threshold=2,   # 實測最佳：1 反而無法定稿（計數器交互）
        clip_audio=True,           # 剪掉無語音段落，避免暫停拖累
        on_close=lambda: None,
    )

    threading.Thread(target=translator, daemon=True).start()

    with client:
        if args.file:
            wf = wave.open(args.file, "rb")
            rate, ch, sw = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
            assert ch == 1 and sw == 2, "需 16-bit 單聲道 wav"
            import numpy as np
            while True:
                raw = wf.readframes(rate // 10)  # 100ms
                if not raw:
                    break
                x = np.frombuffer(raw, dtype=np.int16)
                if rate != 16000:  # 線性插值重採樣到 16k
                    n = int(len(x) * 16000 / rate)
                    xi = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float64))
                    x = xi.astype(np.int16)
                client.send(x.tobytes(), pcm_format="int16")
                time.sleep(0.1)
            time.sleep(10)  # 等尾段定稿
        else:
            import pyaudio
            pa = pyaudio.PyAudio()
            stream = pa.open(format=pyaudio.paInt16, channels=1, rate=16000,
                             input=True, frames_per_buffer=1600)
            print("[麥克風開啟，開始說話…]", flush=True)
            try:
                while True:
                    client.send(stream.read(1600), pcm_format="int16")
            except KeyboardInterrupt:
                pass
            finally:
                stream.stop_stream(); stream.close(); pa.terminate()
    tr_q.put((None, None))


if __name__ == "__main__":
    main()
