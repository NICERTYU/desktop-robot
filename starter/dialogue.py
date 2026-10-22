"""多轮对话记忆：滑动窗口 + 字符预算 + 可选持久化。

为什么需要：
- LLM 本身无状态，每次请求必须把历史消息一起带上；
- 历史无限增长 → token 费用和延迟线性上涨，所以必须裁剪；
- 裁剪会丢信息：这里用"保留最近 N 轮"的滑动窗口，简单可靠。
  （进阶做法是让 LLM 把旧对话摘要成一段话，第 9 周需要时再加。）

用法：
    conv = Conversation("你是桌面机器人……", max_turns=8, max_chars=2000)
    conv.add_user("你好")
    reply = llm(conv.build_messages())
    conv.add_assistant(reply)
    conv.build_messages()   # [system] + 历史，直接丢给 chat.completions
"""

import json
import time
from pathlib import Path


class Conversation:
    """一段可裁剪、可持久化的对话历史。"""

    def __init__(
        self,
        system_prompt: str,
        *,
        max_turns: int = 8,
        max_chars: int = 2000,
    ) -> None:
        self.system_prompt = system_prompt
        self.max_turns = max(1, max_turns)
        self.max_chars = max(100, max_chars)
        self.messages: list[dict[str, str]] = []

    # ---------- 写入 ----------
    def add_user(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.messages.append({"role": "user", "content": text})
        self._trim()

    def add_assistant(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.messages.append({"role": "assistant", "content": text})
        self._trim()

    def drop_last_user(self) -> None:
        """LLM 调用失败时，撤回刚加进去的那句用户输入，避免污染历史。"""
        if self.messages and self.messages[-1]["role"] == "user":
            self.messages.pop()

    def reset(self) -> None:
        self.messages.clear()

    # ---------- 读取 ----------
    def build_messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt}, *self.messages]

    @property
    def turns(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "user")

    def char_count(self) -> int:
        return sum(len(m["content"]) for m in self.messages)

    # ---------- 裁剪 ----------
    def _trim(self) -> None:
        # 至少保留最近一问一答（len > 2 才裁剪），超轮数或超字数就从最旧的成对消息删起
        while len(self.messages) > 2 and (
            self.turns > self.max_turns or self.char_count() > self.max_chars
        ):
            if (
                self.messages[0]["role"] == "user"
                and self.messages[1]["role"] == "assistant"
            ):
                del self.messages[:2]
            else:
                # 异常序列（理论上不会出现）兜底删一条
                del self.messages[0]

    # ---------- 持久化 ----------
    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "messages": self.messages,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(
        cls, path: str | Path, system_prompt: str, **kwargs: int
    ) -> "Conversation":
        conv = cls(system_prompt, **kwargs)
        path = Path(path)
        if not path.exists():
            return conv
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            messages = data.get("messages", [])
            conv.messages = [
                {"role": m["role"], "content": m["content"]}
                for m in messages
                if isinstance(m, dict)
                and m.get("role") in ("user", "assistant")
                and isinstance(m.get("content"), str)
            ]
            conv._trim()
        except (OSError, ValueError, KeyError):
            # 记忆文件坏了就当没有，不要让机器人开不了机
            conv.messages = []
        return conv
