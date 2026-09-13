"""sherpa-onnx 进程启动脚本。

sherpa-onnx 官方为 ASR 提供了 ``sherpa-onnx-online-websocket-server`` /
``sherpa-onnx-offline-websocket-server`` 两个可执行文件，直接由
``process_manager`` 拉起即可。

TTS 官方只提供 Python/C++ API，没有现成的 HTTP server 可执行文件，因此这里附带
``tts_server.py``：一个仅做协议适配（HTTP → ``sherpa_onnx.OfflineTts``）的薄封装，
不包含任何合成逻辑。
"""
