"""TTS 双引擎：GPT-SoVITS（主）+ edge-tts（离线兜底）。

环境变量：
    TTS_ENGINE=edge|gptsovits      默认 edge
    edge 参数：
        TTS_VOICE=zh-CN-XiaoxiaoNeural
        TTS_RATE=-8%
        TTS_PITCH=-12Hz
    GPT-SoVITS 参数见 tts_gptsovits.py，关键是：
        GPTSOVITS_URL / GPTSOVITS_REF_AUDIO / GPTSOVITS_PROMPT_TEXT

用法：
    from tts import synthesize
    engine = await synthesize("你好呀", Path("out.wav"))   # 返回实际用的引擎

设计原则：GPT-SoVITS 服务挂了、超时、或没配置，自动回退 edge-tts，
机器人不会突然变成哑巴。
"""

import asyncio
import os
import time
from pathlib import Path

import edge_tts

TTS_ENGINE = os.getenv("TTS_ENGINE", "edge").strip().lower()

EDGE_VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoxiaoNeural")
EDGE_RATE = os.getenv("TTS_RATE", "-8%")
EDGE_PITCH = os.getenv("TTS_PITCH", "-12Hz")


async def synthesize(text: str, path: str | Path) -> str:
    """把 text 合成到 path，返回实际使用的引擎名（"gptsovits" / "edge"）。"""
    path = Path(path)

    if TTS_ENGINE == "gptsovits":
        try:
            from tts_gptsovits import synthesize as gptsovits_synthesize

            started = time.perf_counter()
            await asyncio.to_thread(gptsovits_synthesize, text, path)
            print(f"   [TTS] GPT-SoVITS {time.perf_counter() - started:.2f}s")
            return "gptsovits"
        except Exception as exc:  # 服务不可用就回退，绝不阻塞对话
            print(f"   [TTS] GPT-SoVITS 不可用（{exc}），回退 edge-tts")

    started = time.perf_counter()
    await edge_tts.Communicate(
        text, EDGE_VOICE, rate=EDGE_RATE, pitch=EDGE_PITCH
    ).save(str(path))
    print(f"   [TTS] edge-tts {time.perf_counter() - started:.2f}s")
    return "edge"
