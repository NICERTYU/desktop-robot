"""机器人记忆：事件日志 + 状态快照 + 自动摘要压缩。

参考 DSH 的三层设计，但只保留机器人需要的部分：

    events.jsonl   事实源，只追加，可回放
    state.json     快照：summary / recent / facts / 计数

自动压缩触发（满足其一）：
    - 距上次压缩又过了 compact_every_turns 轮
    - 当前上下文估算超过 token_budget

压缩在后台线程执行，不阻塞对话；失败时保留原对话，只记录错误提示。

用法：
    mem = Memory("~/.robot_memory", SYSTEM_PROMPT,
                 summarizer=summarize_fn,
                 compact_every_turns=6, token_budget=6000)
    mem.add_user("你好")
    reply = llm(mem.build_messages())
    mem.add_assistant(reply)
    ...
    mem.close()

summarizer 是一个 `Callable[[list[dict]], str]`：接收 OpenAI 风格的消息列表，
返回摘要文本。没有 summarizer 时，自动压缩自动关闭。
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional

SUMMARY_SYSTEM = "你是一个记忆压缩器，只输出结构化的记忆摘要，不要解释。"

SUMMARY_INSTRUCTION = """把上面这段旧对话（以及已有摘要）合并成一段新的记忆。

严格按下面的标题输出，每条用短句：

## 用户画像与偏好
## 近期话题
## 未完成的事
## 情绪与关系
## 要记住的事实

要求：
- 总字数 200–300 字
- 只保留仍然有效的信息，过时的丢掉
- 不要编造，不要输出标题以外的解释
"""


def estimate_tokens(text: str) -> int:
    """粗略估算 token：中文按 1 字≈1 token，其它按 3.5 字符≈1 token。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk + (len(text) - cjk) / 3.5)


class Memory:
    def __init__(
        self,
        directory: str | Path,
        system_prompt: str,
        *,
        summarizer: Optional[Callable[[list[dict]], str]] = None,
        auto_compact: bool = True,
        compact_every_turns: int = 6,
        token_budget: int = 6000,
        keep_recent_turns: int = 4,
        max_facts: int = 20,
    ) -> None:
        self.dir = Path(directory).expanduser()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.dir / "events.jsonl"
        self.state_path = self.dir / "state.json"

        self.system_prompt = system_prompt
        self.summarizer = summarizer
        self.auto_compact = bool(auto_compact and summarizer is not None)
        self.compact_every_turns = max(1, compact_every_turns)
        self.token_budget = max(200, token_budget)
        self.keep_recent_turns = max(1, keep_recent_turns)
        self.max_facts = max(1, max_facts)

        self.summary = ""
        self.recent: list[dict] = []
        self.facts: list[dict] = []
        self.next_id = 1
        self.turns_since_compact = 0
        self.compaction_count = 0
        self.last_error: Optional[str] = None

        self._lock = threading.RLock()
        self._generation = 0
        self._compacting = False
        self._thread: Optional[threading.Thread] = None
        self._notice: Optional[str] = None

        self._load()

    # ---------------- 写入 ----------------
    def add_user(self, text: str) -> None:
        self._add("user", text)

    def add_assistant(self, text: str) -> None:
        self._add("assistant", text)
        with self._lock:
            self._maybe_compact_locked()

    def _add(self, role: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            msg = {"id": self.next_id, "role": role, "content": text}
            self.next_id += 1
            self.recent.append(msg)
            if role == "assistant":
                self.turns_since_compact += 1
            self._append_event({"type": "message", **msg})
            self._save_state()

    def drop_last_user(self) -> None:
        """LLM 调用失败时撤回刚加进去的用户消息，避免污染记忆。"""
        with self._lock:
            if self.recent and self.recent[-1]["role"] == "user":
                msg = self.recent.pop()
                self._append_event({"type": "message_drop", "id": msg["id"]})
                self._save_state()

    def remember(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            if any(f["text"] == text for f in self.facts):
                return
            fact = {"id": (self.facts[-1]["id"] + 1) if self.facts else 1, "text": text, "ts": int(time.time())}
            self.facts.append(fact)
            self.facts = self.facts[-self.max_facts :]
            self._append_event({"type": "fact_add", **fact})
            self._save_state()

    def forget(self, keyword: str) -> int:
        keyword = keyword.strip()
        if not keyword:
            return 0
        with self._lock:
            removed = [f for f in self.facts if keyword in f["text"]]
            self.facts = [f for f in self.facts if keyword not in f["text"]]
            for f in removed:
                self._append_event({"type": "fact_remove", "id": f["id"]})
            if removed:
                self._save_state()
            return len(removed)

    def reset(self, *, keep_facts: bool = True) -> None:
        with self._lock:
            self._generation += 1
            self.recent = []
            self.summary = ""
            self.turns_since_compact = 0
            if not keep_facts:
                self.facts = []
            self._append_event({"type": "reset", "keep_facts": keep_facts})
            self._save_state()

    # ---------------- 读取 ----------------
    def build_messages(self) -> list[dict]:
        with self._lock:
            system = self.system_prompt
            if self.facts:
                lines = "\n".join(f"- {f['text']}" for f in self.facts)
                system += f"\n\n[长期记忆]\n{lines}"
            if self.summary:
                system += f"\n\n[之前对话的摘要]\n{self.summary}"
            messages = [{"role": "system", "content": system}]
            messages.extend(
                {"role": m["role"], "content": m["content"]} for m in self.recent
            )
            return messages

    @property
    def turns(self) -> int:
        with self._lock:
            return sum(1 for m in self.recent if m["role"] == "user")

    @property
    def is_compacting(self) -> bool:
        with self._lock:
            return self._compacting

    def estimate_context_tokens(self) -> int:
        return sum(estimate_tokens(m["content"]) for m in self.build_messages())

    def take_notice(self) -> Optional[str]:
        with self._lock:
            notice, self._notice = self._notice, None
            return notice

    # ---------------- 压缩 ----------------
    def compact_now(self, *, wait: bool = False) -> bool:
        with self._lock:
            if self._compacting:
                thread = self._thread
            else:
                if not self._start_compact_locked(force=True):
                    return False
                thread = self._thread
        if wait and thread is not None:
            thread.join()
        return True

    def wait(self, timeout: Optional[float] = None) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)

    def close(self) -> None:
        self.wait(timeout=30)
        with self._lock:
            self._save_state()

    # ---------------- 内部：压缩调度 ----------------
    def _maybe_compact_locked(self) -> None:
        if not self.auto_compact or self._compacting or self.summarizer is None:
            return
        if len(self.recent) <= self.keep_recent_turns * 2:
            return
        due_turns = self.turns_since_compact >= self.compact_every_turns
        due_tokens = self.estimate_context_tokens() > self.token_budget
        if due_turns or due_tokens:
            self._start_compact_locked(force=False)

    def _start_compact_locked(self, *, force: bool) -> bool:
        keep = self.keep_recent_turns * 2
        if len(self.recent) <= keep:
            return False
        old = self.recent[:-keep]
        # 只按成对消息压缩，别把"用户刚说、还没回答"的那句卷进去
        if old and old[-1]["role"] == "user":
            old = old[:-1]
        if not old:
            return False

        self._compacting = True
        snapshot = (list(old), self.summary, old[-1]["id"], self._generation)
        self._thread = threading.Thread(
            target=self._compact_worker, args=snapshot, daemon=True
        )
        self._thread.start()
        return True

    def _compact_worker(
        self, old: list[dict], prev_summary: str, cut_id: int, generation: int
    ) -> None:
        try:
            summary = self.summarizer(self._summary_request(old, prev_summary))
            summary = (summary or "").strip()
            if not summary:
                raise ValueError("摘要为空")
        except Exception as exc:  # 摘要失败：保留原对话，只记错误
            with self._lock:
                self.last_error = str(exc)
                self._notice = f"（记忆压缩失败，保留原对话：{exc}）"
                self._compacting = False
            return

        with self._lock:
            if generation != self._generation:
                # 压缩期间用户清空过记忆，丢弃这次摘要
                self._compacting = False
                return
            self.recent = [m for m in self.recent if m["id"] > cut_id]
            self.summary = summary[:1500]
            self.turns_since_compact = 0
            self.compaction_count += 1
            self.last_error = None
            self._append_event(
                {
                    "type": "compact",
                    "cut_id": cut_id,
                    "summary": self.summary,
                    "removed": len(old),
                }
            )
            self._save_state()
            self._notice = f"（记忆已压缩：{len(old) // 2} 轮 → 摘要）"
            self._compacting = False

    def _summary_request(self, old: list[dict], prev_summary: str) -> list[dict]:
        system = SUMMARY_SYSTEM
        if prev_summary:
            system += f"\n\n已有摘要：\n{prev_summary}"
        messages = [{"role": "system", "content": system}]
        messages.extend(
            {"role": m["role"], "content": m["content"]} for m in old
        )
        messages.append({"role": "user", "content": SUMMARY_INSTRUCTION})
        return messages

    # ---------------- 内部：持久化 ----------------
    def _append_event(self, event: dict) -> None:
        event = {"ts": int(time.time()), **event}
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
            f.flush()

    def _save_state(self) -> None:
        payload = {
            "version": 1,
            "summary": self.summary,
            "recent": self.recent,
            "facts": self.facts,
            "next_id": self.next_id,
            "turns_since_compact": self.turns_since_compact,
            "compaction_count": self.compaction_count,
            "updated_at": int(time.time()),
        }
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                self.summary = str(data.get("summary", ""))
                self.recent = list(data.get("recent", []))
                self.facts = list(data.get("facts", []))
                self.next_id = int(data.get("next_id", 1))
                self.turns_since_compact = int(data.get("turns_since_compact", 0))
                self.compaction_count = int(data.get("compaction_count", 0))
                self._normalize_ids()
                return
            except (OSError, ValueError, TypeError):
                pass  # 快照坏了就从事件日志重建
        if self.events_path.exists():
            self._rebuild_from_events()
        self._save_state()

    def _normalize_ids(self) -> None:
        max_id = 0
        for msg in self.recent:
            max_id = max(max_id, int(msg.get("id", 0)))
        self.next_id = max(self.next_id, max_id + 1)
        for fact in self.facts:
            max_id = max(max_id, int(fact.get("id", 0)))

    def _rebuild_from_events(self) -> None:
        self.summary = ""
        self.recent = []
        self.facts = []
        self.next_id = 1
        self.turns_since_compact = 0
        self.compaction_count = 0

        if not self.events_path.exists():
            return
        for line in self.events_path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            kind = event.get("type")
            if kind == "message":
                self.recent.append(
                    {
                        "id": int(event.get("id", 0)),
                        "role": event.get("role", "user"),
                        "content": str(event.get("content", "")),
                    }
                )
                self.next_id = max(self.next_id, int(event.get("id", 0)) + 1)
            elif kind == "message_drop":
                drop_id = event.get("id")
                self.recent = [m for m in self.recent if m["id"] != drop_id]
            elif kind == "compact":
                cut_id = int(event.get("cut_id", 0))
                self.summary = str(event.get("summary", ""))
                self.recent = [m for m in self.recent if m["id"] > cut_id]
                self.compaction_count += 1
                self.turns_since_compact = 0
            elif kind == "reset":
                self.recent = []
                self.summary = ""
                self.turns_since_compact = 0
                if not event.get("keep_facts", True):
                    self.facts = []
            elif kind == "fact_add":
                self.facts.append(
                    {
                        "id": int(event.get("id", 0)),
                        "text": str(event.get("text", "")),
                        "ts": int(event.get("ts", 0)),
                    }
                )
            elif kind == "fact_remove":
                fid = event.get("id")
                self.facts = [f for f in self.facts if f["id"] != fid]
        self._save_state()
