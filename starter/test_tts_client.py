"""本地 mock 测试：不依赖真实 GPT-SoVITS 服务，验证客户端行为。

运行：
    python starter/test_tts_client.py
"""

import io
import json
import sys
import tempfile
import threading
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from tts_gptsovits import TTSError, synthesize  # noqa: E402


def make_wav(seconds: float = 0.3, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    received: dict = {}

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        Handler.received = json.loads(self.rfile.read(length))
        data = make_wav()
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:  # 静音
        pass


def main() -> None:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "reply.wav"
        synthesize(
            "你好呀，我是御姐音的机器人",
            out,
            url=f"http://127.0.0.1:{port}",
            ref_audio="/data/refs/yujie.wav",
            prompt_text="今天想让我帮你做点什么呢",
        )
        assert out.exists() and out.stat().st_size > 0
        with wave.open(str(out)) as f:
            assert f.getnchannels() == 1
            assert f.getnframes() > 0
        assert Handler.received["text"] == "你好呀，我是御姐音的机器人"
        assert Handler.received["ref_audio_path"] == "/data/refs/yujie.wav"
        assert Handler.received["prompt_text"] == "今天想让我帮你做点什么呢"
        assert Handler.received["media_type"] == "wav"
        print("PASS 成功路径：收到 WAV，payload 字段正确")

    server.shutdown()

    # 连接失败 → TTSError
    try:
        synthesize(
            "x",
            Path(tempfile.gettempdir()) / "x.wav",
            url="http://127.0.0.1:9",
            ref_audio="/data/refs/yujie.wav",
            prompt_text="p",
            timeout=3,
        )
    except TTSError as exc:
        print(f"PASS 连接失败：{exc}")
    else:
        raise AssertionError("连接失败时应抛 TTSError")

    # 缺参考音频 → 直接在本地报错，不发请求
    try:
        synthesize(
            "x",
            Path(tempfile.gettempdir()) / "x.wav",
            url="http://127.0.0.1:9",
            ref_audio="",
            prompt_text="p",
        )
    except TTSError as exc:
        print(f"PASS 缺参数：{exc}")
    else:
        raise AssertionError("缺 ref_audio 时应抛 TTSError")

    print("\n全部通过 ✅")


if __name__ == "__main__":
    main()
