#!/usr/bin/env python3
"""VAD 切句 + faster-whisper 逐句解碼：保留 whisper 品質、擺脫 WhisperLive 延遲

用法:
  captions_offline.py                # 麥克風即時
  captions_offline.py --file x.wav   # 檔案 1x 測試
  WL_MODEL=small captions_offline.py # 換模型

延遲組成：停頓偵測 0.6s + whisper 解碼(每句) ~1-2s ≈ 講完 2-3 秒內上字幕
環境變數 GEMINI_API_KEY 有設則加英譯。
"""
import argparse, collections, json, os, queue, sys, threading, time, wave
import urllib.request

import numpy as np
import webrtcvad
from faster_whisper import WhisperModel

FRAME_MS = 30
SR = 16000


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
    ap.add_argument("--file")
    args = ap.parse_args()

    final_model_name = os.environ.get("WL_MODEL", "medium")
    # WL_TASK=translate → whisper 內建中→英直譯（完全離線）；transcribe → 中文稿（可接 Gemini 英譯）
    task = os.environ.get("WL_TASK", "transcribe")
    api_key = os.environ.get("GEMINI_API_KEY")
    gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite")
    label = "EN" if task == "translate" else "ZH"

    print(f"[載入 whisper small（草稿）+ {final_model_name}（定稿）task={task}…]",
          flush=True)
    t0 = time.time()
    draft_model = WhisperModel("small", device="cpu", compute_type="int8",
                               cpu_threads=6)
    final_model = WhisperModel(final_model_name, device="cpu", compute_type="int8",
                               cpu_threads=6)
    print(f"[模型就緒 {time.time()-t0:.0f}s]", flush=True)

    chunk_q = queue.Queue()

    def decode(m, audio):
        segments, _ = m.transcribe(audio, language="zh", task=task, beam_size=1,
                                   condition_on_previous_text=False,
                                   vad_filter=False)
        return "".join(s.text for s in segments).strip()

    def whisper_worker():
        while True:
            item = chunk_q.get()
            if item is None:
                break
            audio, t_end = item
            try:
                # 1) small 草稿：最快可讀
                draft = decode(draft_model, audio)
                if draft:
                    print(f"\033[2m…  {draft}  [{time.time()-t_end:.1f}s]\033[0m",
                          flush=True)
                # 2) medium 定稿：品質取代
                text = decode(final_model, audio)
                if text:
                    print(f"\033[36m{label}  {text}\033[0m  [停頓後 {time.time()-t_end:.1f}s]",
                          flush=True)
                if api_key and text and task == "transcribe":
                    try:
                        en = gemini_translate(text, api_key, gemini_model)
                        print(f"\033[1m  EN  {en}\033[0m", flush=True)
                    except Exception as e:
                        print(f"  [翻譯失敗: {e}]", flush=True)
            except Exception as e:
                print(f"[解碼失敗: {e}]", flush=True)
            finally:
                chunk_q.task_done()

    threading.Thread(target=whisper_worker, daemon=True).start()

    vad = webrtcvad.Vad(2)  # 0-3，2 中等積極
    ring = collections.deque(maxlen=10)          # 300ms pre-roll
    buf, voiced_run, idle_run = [], 0, 0
    in_speech = False

    last_voiced = 0

    def feed(pcm, t_end=None):
        nonlocal buf, voiced_run, idle_run, in_speech, last_voiced
        ring.append(pcm)
        is_speech = vad.is_speech(pcm, SR)
        if is_speech:
            voiced_run += 1
            idle_run = 0
        else:
            idle_run += 1
            voiced_run = 0
        if not in_speech and voiced_run >= 5:      # 150ms 語音開始
            in_speech = True
            buf = list(ring)                       # 帶 pre-roll
            last_voiced = len(buf)
        elif in_speech:
            buf.append(pcm)
            if is_speech:
                last_voiced = len(buf)
            dur = len(buf) * FRAME_MS / 1000
            # 600ms 靜音或單句超過 10s → 送出解碼
            if (idle_run >= 20 and voiced_run == 0 and dur > 0.8) or dur > 10:
                # 修剪尾部靜音：到最後一個語音帧 + 150ms
                pcm_out = b"".join(buf[:last_voiced + 5])
                audio = np.frombuffer(pcm_out, np.int16).astype(np.float32) / 32768.0
                chunk_q.put((audio, t_end if t_end else time.time()))
                in_speech, buf, idle_run = False, [], 0

    if args.file:
        wf = wave.open(args.file, "rb")
        rate = wf.getframerate()
        assert rate == SR, f"需 16kHz wav（ffmpeg -ar 16000 轉檔）"
        while True:
            raw = wf.readframes(SR * FRAME_MS // 1000)
            if len(raw) != SR * FRAME_MS // 1000 * 2:  # EOF（短框）
                break
            feed(raw, time.time())
            time.sleep(FRAME_MS / 1000)  # 1x 即時模擬
        if buf:  # 檔案結束時沖出最後一句
            audio = np.frombuffer(b"".join(buf), np.int16).astype(np.float32) / 32768.0
            chunk_q.put((audio, time.time()))
    else:
        import pyaudio
        pa = pyaudio.PyAudio()
        st = pa.open(format=pyaudio.paInt16, channels=1, rate=SR,
                     input=True, frames_per_buffer=SR * FRAME_MS // 1000)
        tag = " + Gemini 英譯" if api_key else "（未設 GEMINI_API_KEY：只出中文）"
        print(f"[字幕啟動] whisper small→{final_model_name} 兩段式{tag} · Ctrl-C 結束", flush=True)
        try:
            while True:
                feed(st.read(SR * FRAME_MS // 1000))
        except KeyboardInterrupt:
            pass
        finally:
            st.stop_stream(); st.close(); pa.terminate()
    chunk_q.join()   # 等待佇列中的句子解碼完
    chunk_q.put(None)


if __name__ == "__main__":
    main()
