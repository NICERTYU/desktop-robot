"""用 edge-tts 生成一批"御姐音"候选样本，试听后挑一个。

用法：
    pip install edge-tts
    python starter/tts_audition.py

生成的文件在 starter/tts_samples/，每个文件对应一组音色 + 语速/音高参数。
听完把最满意的一组填进 voice_loop.py 的环境变量（或直接改默认值）。
"""

import asyncio
from pathlib import Path

import edge_tts

TEXT = "你好呀，我是你的桌面机器人。今天想让我帮你做点什么呢？"
OUT_DIR = Path(__file__).parent / "tts_samples"

# (文件名, 音色, 语速, 音高)
# edge-tts 的中文女声里没有真正的"御姐音"，最接近的做法是：
# 晓晓 + 降音高 + 略降语速
SAMPLES = [
    ("01_xiaoxiao_normal", "zh-CN-XiaoxiaoNeural", "+0%", "+0Hz"),
    ("02_xiaoxiao_low", "zh-CN-XiaoxiaoNeural", "-6%", "-8Hz"),
    ("03_xiaoxiao_lower", "zh-CN-XiaoxiaoNeural", "-12%", "-16Hz"),
    ("04_xiaoxiao_slow_deep", "zh-CN-XiaoxiaoNeural", "-18%", "-22Hz"),
    ("05_xiaoyi_young", "zh-CN-XiaoyiNeural", "+0%", "+0Hz"),
    ("06_xiaobei_dongbei", "zh-CN-liaoning-XiaobeiNeural", "+0%", "+0Hz"),
    ("07_hsiaochen_tw", "zh-TW-HsiaoChenNeural", "+0%", "+0Hz"),
    ("08_xiaoni_shaanxi", "zh-CN-shaanxi-XiaoniNeural", "+0%", "+0Hz"),
]


async def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, voice, rate, pitch in SAMPLES:
        out = OUT_DIR / f"{name}.mp3"
        communicate = edge_tts.Communicate(TEXT, voice, rate=rate, pitch=pitch)
        await communicate.save(str(out))
        size = out.stat().st_size
        print(f"{name:<22} {size:>8} bytes   {voice}  rate={rate} pitch={pitch}")
    print(f"\n全部生成在：{OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
