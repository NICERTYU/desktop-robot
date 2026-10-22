"""GPT-SoVITS 机器人侧客户端：把文字发给 GPT-SoVITS 的 api_v2 服务，拿回 wav。

GPT-SoVITS 跑在 PC / 云 GPU 上（树莓派跑不动），通过 api_v2.py 暴露 HTTP 接口：

    # 在跑模型的机器上
    python api_v2.py -a 0.0.0.0 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml

机器人侧只需要设置环境变量：

    export GPTSOVITS_URL=http://192.168.1.10:9880
    export GPTSOVITS_REF_AUDIO=/abs/path/on/server/ref_yujie.wav
    export GPTSOVITS_PROMPT_TEXT=参考音频里说的那句话（必须与音频逐字一致）
    export GPTSOVITS_PROMPT_LANG=zh        # 可选
    export GPTSOVITS_TEXT_LANG=zh          # 可选
    export GPTSOVITS_SPEED=1.0             # 可选，1.05~1.15 更利落
    export GPTSOVITS_TIMEOUT=60            # 可选

用法：

    from tts_gptsovits import synthesize, TTSError
    synthesize("你好呀", "out.wav")

只用标准库，不增加机器人依赖。
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path


class TTSError(RuntimeError):
    """GPT-SoVITS 调用失败。"""


def synthesize(
    text: str,
    out_path: str | Path,
    *,
    url: str | None = None,
    ref_audio: str | None = None,
    prompt_text: str | None = None,
    prompt_lang: str | None = None,
    text_lang: str | None = None,
    speed: float | None = None,
    timeout: float | None = None,
) -> Path:
    """请求 GPT-SoVITS 合成一句话，保存为 wav 并返回路径。失败抛 TTSError。"""
    url = (url or os.getenv("GPTSOVITS_URL", "http://127.0.0.1:9880")).rstrip("/")
    ref_audio = ref_audio or os.getenv("GPTSOVITS_REF_AUDIO", "")
    prompt_text = prompt_text or os.getenv("GPTSOVITS_PROMPT_TEXT", "")
    prompt_lang = prompt_lang or os.getenv("GPTSOVITS_PROMPT_LANG", "zh")
    text_lang = text_lang or os.getenv("GPTSOVITS_TEXT_LANG", "zh")
    speed = float(speed if speed is not None else os.getenv("GPTSOVITS_SPEED", "1.0"))
    timeout = float(
        timeout if timeout is not None else os.getenv("GPTSOVITS_TIMEOUT", "60")
    )

    if not ref_audio:
        raise TTSError("未设置 GPTSOVITS_REF_AUDIO（参考音频在服务器上的绝对路径）")
    if not prompt_text:
        raise TTSError("未设置 GPTSOVITS_PROMPT_TEXT（必须与参考音频逐字一致）")

    payload = {
        "text": text,
        "text_lang": text_lang,
        "ref_audio_path": ref_audio,
        "prompt_text": prompt_text,
        "prompt_lang": prompt_lang,
        "top_k": 15,
        "top_p": 1,
        "temperature": 1,
        "text_split_method": "cut5",
        "batch_size": 1,
        "speed_factor": speed,
        "streaming_mode": False,
        "media_type": "wav",
        "seed": -1,
    }

    request = urllib.request.Request(
        url + "/tts",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:400].decode("utf-8", "replace")
        raise TTSError(f"HTTP {exc.code}：{detail}") from exc
    except Exception as exc:  # 连接失败、超时等
        raise TTSError(f"连接 {url} 失败：{exc}") from exc

    if not data.startswith(b"RIFF"):
        raise TTSError(f"返回的不是 WAV（前 120 字节：{data[:120]!r}）")

    out_path = Path(out_path)
    out_path.write_bytes(data)
    return out_path
