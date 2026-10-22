"""第 1 周骨架：录音 → 语音识别 → 多轮对话（自动压缩记忆）→ TTS 播放。

安装依赖：
    pip install -r starter/requirements.txt

环境变量（以 DeepSeek 为例，任何 OpenAI 兼容 API 都行）：
    export LLM_API_KEY=sk-xxxx
    export LLM_BASE_URL=https://api.deepseek.com/v1     # 可选
    export LLM_MODEL=deepseek-chat                      # 可选
    export TTS_ENGINE=edge                              # edge | gptsovits
    export TTS_VOICE=zh-CN-XiaoxiaoNeural               # edge 音色
    export TTS_RATE=-8%                                 # edge 语速
    export TTS_PITCH=-12Hz                              # edge 音高

记忆相关：
    export MEMORY_DIR=~/.robot_memory                   # 记忆目录
    export AUTO_COMPACT=1                               # 0 关闭自动压缩
    export COMPACT_EVERY_TURNS=6                        # 每 6 轮触发一次
    export CONTEXT_TOKEN_BUDGET=6000                    # 或超过预算就压缩
    export KEEP_RECENT_TURNS=4                          # 压缩时保留最近 4 轮

GPT-SoVITS 御姐音（可选，服务没开会自动回退 edge-tts）：
    export TTS_ENGINE=gptsovits
    export GPTSOVITS_URL=http://192.168.1.10:9880
    export GPTSOVITS_REF_AUDIO=/abs/path/ref_yujie.wav
    export GPTSOVITS_PROMPT_TEXT=参考音频里说的那句话

命令：
    回车 = 录音；q = 退出；clear = 清空对话（保留事实）；
    compact = 立即整理记忆；history = 看摘要/事实/最近对话；
    记住 xxx / 忘记 xxx = 写入或删除长期事实

说明：
- 录固定 6 秒，第 2 周换成 VAD 自动断句。
- 记忆在后台线程压缩，不阻塞说话；失败只提示，不丢历史。
"""

import asyncio
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import sounddevice as sd
from faster_whisper import WhisperModel
from openai import OpenAI

from memory import Memory
from tts import synthesize

SAMPLE_RATE = 16000
RECORD_SECONDS = 6

ASR_MODEL = os.getenv("ASR_MODEL", "small")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

MEMORY_DIR = os.getenv("MEMORY_DIR", "~/.robot_memory")
AUTO_COMPACT = os.getenv("AUTO_COMPACT", "1").lower() not in {"0", "false", "no"}
COMPACT_EVERY_TURNS = int(os.getenv("COMPACT_EVERY_TURNS", "6"))
CONTEXT_TOKEN_BUDGET = int(os.getenv("CONTEXT_TOKEN_BUDGET", "6000"))
KEEP_RECENT_TURNS = int(os.getenv("KEEP_RECENT_TURNS", "4"))

SYSTEM_PROMPT = (
    "你是一个桌面机器人的大脑，通过麦克风和用户对话，你的回答会被语音合成朗读。"
    "记住上下文，不要重复自我介绍，也不要每轮都问'还有什么可以帮你'。"
    "要求：口语化、简短（不超过 40 字）、不要用 Markdown、不要列清单、不要用表情符号。"
)


def record_wav(path: Path, seconds: float = RECORD_SECONDS) -> None:
    print(f"🎤 录音 {seconds:.0f} 秒，请说话……")
    audio = sd.rec(
        int(seconds * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(audio.tobytes())


def transcribe(model: WhisperModel, path: Path) -> str:
    segments, _info = model.transcribe(
        str(path),
        language="zh",
        vad_filter=True,
        beam_size=1,
    )
    return "".join(seg.text for seg in segments).strip()


def ask_llm(client: OpenAI, messages: list[dict]) -> str:
    resp = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=0.7,
        max_tokens=200,
    )
    return (resp.choices[0].message.content or "").strip()


def make_summarizer(client: OpenAI):
    """给记忆模块用的摘要器：一次独立的小模型调用，输出 200–300 字。"""

    def summarize(messages: list[dict]) -> str:
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=500,
        )
        return (resp.choices[0].message.content or "").strip()

    return summarize


def play(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["afplay", str(path)], check=False)
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.run(
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
            check=False,
        )


def print_history(memory: Memory) -> None:
    if memory.summary:
        print("\n[历史摘要]\n" + memory.summary)
    if memory.facts:
        print("\n[长期事实]")
        for fact in memory.facts[-10:]:
            print("  - " + fact["text"])
    if memory.recent:
        print("\n[最近对话]")
        for msg in memory.recent[-6:]:
            who = "你" if msg["role"] == "user" else "机器人"
            print(f"  {who}：{msg['content']}")
    if not (memory.summary or memory.facts or memory.recent):
        print("（还没有记忆）")


def main() -> None:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        sys.exit("请先设置环境变量 LLM_API_KEY（OpenAI 兼容 API 的 key）")

    client = OpenAI(api_key=api_key, base_url=LLM_BASE_URL)

    print("加载 ASR 模型……（首次会下载）")
    asr = WhisperModel(ASR_MODEL, device="cpu", compute_type="int8")

    memory = Memory(
        MEMORY_DIR,
        SYSTEM_PROMPT,
        summarizer=make_summarizer(client),
        auto_compact=AUTO_COMPACT,
        compact_every_turns=COMPACT_EVERY_TURNS,
        token_budget=CONTEXT_TOKEN_BUDGET,
        keep_recent_turns=KEEP_RECENT_TURNS,
        max_facts=20,
    )

    print(f"记忆目录：{memory.dir}")
    print(
        f"已载入 {memory.turns} 轮对话、{len(memory.facts)} 条长期事实"
        f"（自动压缩：{'开' if memory.auto_compact else '关'}）"
    )
    if memory.summary:
        print("（已载入历史摘要）")

    print(
        "就绪。回车录音，q 退出，clear 清空，compact 整理记忆，history 查看记忆。"
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        try:
            while True:
                notice = memory.take_notice()
                if notice:
                    print(notice)

                cmd = input("\n> ").strip()
                low = cmd.lower()

                if low in {"q", "quit", "退出"}:
                    break
                if low in {"clear", "清空", "新话题"}:
                    memory.reset(keep_facts=True)
                    print("（已清空对话记忆，长期事实保留）")
                    continue
                if low in {"compact", "压缩", "整理记忆"}:
                    if memory.compact_now(wait=False):
                        print("（已开始整理记忆，后台进行）")
                    else:
                        print("（没有可以整理的历史）")
                    continue
                if low in {"history", "历史"}:
                    print_history(memory)
                    continue
                if low in {"facts", "事实"}:
                    for fact in memory.facts:
                        print("  - " + fact["text"])
                    if not memory.facts:
                        print("（还没有长期事实）")
                    continue
                if cmd.startswith(("记住 ", "remember ")):
                    text = cmd.split(" ", 1)[1].strip()
                    memory.remember(text)
                    print(f"（已记住：{text}）")
                    continue
                if cmd.startswith(("忘记 ", "forget ")):
                    keyword = cmd.split(" ", 1)[1].strip()
                    removed = memory.forget(keyword)
                    print(f"（已删除 {removed} 条相关事实）")
                    continue

                wav_path = tmpdir / "in.wav"
                tts_path = tmpdir / "out.wav"

                record_wav(wav_path)
                text = transcribe(asr, wav_path)
                if not text:
                    print("（没听清，再说一次？）")
                    continue
                print(f"👂 你说：{text}")

                memory.add_user(text)
                try:
                    reply = ask_llm(client, memory.build_messages())
                except Exception as exc:  # 网络/鉴权失败，别把半句话留在记忆里
                    memory.drop_last_user()
                    print(f"（大脑暂时没连上：{exc}）")
                    continue

                if not reply:
                    memory.drop_last_user()
                    print("（它没说话，再试一次？）")
                    continue

                memory.add_assistant(reply)
                print(f"🤖 机器人：{reply}（记忆 {memory.turns} 轮）")

                notice = memory.take_notice()
                if notice:
                    print(notice)

                asyncio.run(synthesize(reply, tts_path))
                play(tts_path)
        except KeyboardInterrupt:
            print("\n再见。")
        finally:
            memory.close()


if __name__ == "__main__":
    main()
