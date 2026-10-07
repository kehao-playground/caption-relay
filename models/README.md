# Local models

Model files are not committed. Place them here for the optional local routes:

| Path | Used by |
|---|---|
| `sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/` | `routes/sherpa/` (default) |
| `sherpa-onnx-streaming-paraformer-bilingual-zh-en/` | `routes/sherpa/captions_live.py --model para` |
| `zh_CN-huayan-medium.onnx` and `.onnx.json` | `scripts/make_paused.py` (Piper TTS fixture generator) |

The sherpa-onnx models are published in the [sherpa-onnx pretrained model list](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/index.html); the Piper voice is published in [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices/tree/main/zh/zh_CN/huayan/medium) (dataset HuaYan_TTS, license listed as Unknown in its model card; do not redistribute audio generated with it).
