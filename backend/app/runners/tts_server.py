#!/usr/bin/env python3
"""sherpa-onnx TTS HTTP 服务（薄封装）。

只做协议适配，不做任何语音合成算法实现：全部推理都委托给
``sherpa_onnx.OfflineTts``（官方 Python API）。

接口：
    GET  /health  -> {"status": "ok", "sample_rate": ...}
    POST /tts     -> body {"text": "...", "speaker_id": 0, "speed": 1.0}
                     返回 audio/wav（16-bit PCM）

用法（一般由 process_manager 按 models.yaml 模板拉起）：
    python -m app.runners.tts_server --port=7002 \
        --vits-model=/path/model.onnx --tokens=/path/tokens.txt --lexicon=/path/lexicon.txt
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import struct
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("tts_server")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="sherpa-onnx TTS HTTP server")
    parser.add_argument("--port", type=int, required=True, help="监听端口")
    parser.add_argument("--vits-model", required=True, help="VITS/MatchedTTS ONNX 模型路径")
    parser.add_argument("--tokens", required=True, help="tokens.txt 路径")
    parser.add_argument("--lexicon", default="", help="lexicon.txt 路径（中文模型需要）")
    parser.add_argument("--dict-dir", default="", help="jieba 词典目录（可选）")
    parser.add_argument("--rule-fsts", default="", help="规则 FST，多个用逗号分隔（可选）")
    parser.add_argument("--num-threads", type=int, default=2)
    parser.add_argument("--provider", default="cpu", help="cpu / cuda / coreml ...")
    parser.add_argument("--max-num-sentences", type=int, default=2)
    return parser


def samples_to_wav(samples, sample_rate: int) -> bytes:
    """把 float32 采样转成 16-bit PCM WAV 字节流。"""
    try:
        import numpy as np

        clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
        pcm = (clipped * 32767.0).astype("<i2").tobytes()
    except ImportError:  # pragma: no cover - numpy 通常随 sherpa-onnx 一起安装
        pcm = b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, float(s))) * 32767)) for s in samples
        )

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def build_tts(args: argparse.Namespace):
    try:
        import sherpa_onnx
    except ImportError as exc:  # pragma: no cover
        logger.error(
            "未安装 sherpa-onnx Python 包，请执行: pip install sherpa-onnx"
        )
        raise SystemExit(2) from exc

    vits = sherpa_onnx.OfflineTtsVitsModelConfig(
        model=args.vits_model,
        lexicon=args.lexicon,
        tokens=args.tokens,
        dict_dir=args.dict_dir,
    )
    model_config = sherpa_onnx.OfflineTtsModelConfig(
        vits=vits,
        num_threads=args.num_threads,
        provider=args.provider,
        debug=False,
    )
    config = sherpa_onnx.OfflineTtsConfig(
        model=model_config,
        rule_fsts=args.rule_fsts,
        max_num_sentences=args.max_num_sentences,
    )
    tts = sherpa_onnx.OfflineTts(config)
    logger.info(
        "TTS 模型加载完成: sample_rate=%s speakers=%s", tts.sample_rate, tts.num_speakers
    )
    return tts


def make_handler(tts, lock: threading.Lock):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "sherpa-model-hub-tts/0.1"

        # ------------------------------------------------------------ 工具
        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            logger.info("%s - %s", self.address_string(), fmt % args)

        # ------------------------------------------------------------ GET
        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") in ("", "/health"):
                self._send_json(
                    200,
                    {
                        "status": "ok",
                        "sample_rate": tts.sample_rate,
                        "num_speakers": tts.num_speakers,
                    },
                )
            else:
                self._send_json(404, {"detail": "not found"})

        # ----------------------------------------------------------- POST
        def do_POST(self) -> None:  # noqa: N802
            if self.path.rstrip("/") != "/tts":
                self._send_json(404, {"detail": "not found"})
                return

            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                payload = json.loads(raw.decode("utf-8") or "{}")
                text = str(payload.get("text") or "").strip()
                speaker_id = int(payload.get("speaker_id") or 0)
                speed = float(payload.get("speed") or 1.0)
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json(400, {"detail": f"请求体非法: {exc}"})
                return

            if not text:
                self._send_json(400, {"detail": "text 不能为空"})
                return
            if speaker_id < 0 or speaker_id >= max(tts.num_speakers, 1):
                self._send_json(
                    400, {"detail": f"speaker_id 超出范围 [0, {tts.num_speakers - 1}]"}
                )
                return

            try:
                with lock:  # sherpa-onnx 推理非线程安全，串行化
                    audio = tts.generate(text, sid=speaker_id, speed=speed)
                wav_bytes = samples_to_wav(audio.samples, audio.sample_rate)
            except Exception as exc:  # noqa: BLE001 - 单次请求失败不应影响服务
                logger.exception("合成失败")
                self._send_json(500, {"detail": f"合成失败: {exc}"})
                return

            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav_bytes)))
            self.end_headers()
            self.wfile.write(wav_bytes)

    return Handler


def main() -> None:
    args = build_parser().parse_args()
    tts = build_tts(args)

    server = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(tts, threading.Lock()))
    server.daemon_threads = True
    logger.info("TTS 服务已启动: http://0.0.0.0:%s  (POST /tts, GET /health)", args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("收到中断信号，退出")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
