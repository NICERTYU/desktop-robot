"""记忆系统测试：自动压缩、失败兜底、持久化、事实记忆。不需要网络。"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from memory import Memory  # noqa: E402


def make_memory(td, summarizer, **kwargs):
    defaults = dict(
        compact_every_turns=3,
        token_budget=10**9,
        keep_recent_turns=1,
        auto_compact=True,
    )
    defaults.update(kwargs)
    return Memory(td, "你是测试机器人", summarizer=summarizer, **defaults)


def test_auto_compact_by_turns():
    calls = []

    def summarizer(messages):
        calls.append(messages)
        return "## 用户画像与偏好\n用户喜欢咖啡"

    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(td, summarizer)
        for i in range(6):
            mem.add_user(f"用户消息{i}")
            mem.add_assistant(f"回答{i}")
        mem.wait()
        assert calls, "应该调用过摘要器"
        assert mem.summary.startswith("## 用户画像与偏好")
        assert mem.compaction_count >= 1
        assert mem.turns <= 1, f"压缩后应只保留最近 1 轮，实际 {mem.turns}"
        assert "用户消息0" not in mem.build_messages()[-1]["content"]
        print("PASS 按轮数自动压缩")


def test_auto_compact_by_tokens():
    def summarizer(messages):
        return "## 近期话题\n聊了很长的事情"

    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(
            td, summarizer, compact_every_turns=100, token_budget=80
        )
        mem.add_user("长" * 60)
        mem.add_assistant("回" * 60)
        assert mem.summary == ""  # 只有一轮，还不需要压
        mem.add_user("长" * 60)
        mem.add_assistant("回" * 60)
        mem.wait()
        assert mem.summary, "超过 token 预算应触发压缩"
        assert mem.estimate_context_tokens() < 500
        print("PASS 超过 token 预算自动压缩")


def test_compaction_failure_keeps_history():
    def bad_summarizer(messages):
        raise RuntimeError("网络断了")

    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(td, bad_summarizer, compact_every_turns=2)
        for i in range(4):
            mem.add_user(f"u{i}")
            mem.add_assistant(f"a{i}")
        for _ in range(100):
            if not mem.is_compacting:
                break
            time.sleep(0.01)
        assert mem.summary == ""
        assert mem.last_error and "网络断了" in mem.last_error
        assert mem.turns == 4, "失败时不能丢历史"
        notice = mem.take_notice()
        assert notice and "失败" in notice
        print("PASS 摘要失败保留原对话")


def test_persistence_and_rebuild():
    def summarizer(messages):
        return "## 要记住的事实\n用户名字叫小林"

    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(td, summarizer)
        mem.remember("用户喜欢美式咖啡")
        for i in range(4):
            mem.add_user(f"问题{i}")
            mem.add_assistant(f"回答{i}")
        mem.wait()

        loaded = make_memory(td, summarizer)
        assert loaded.summary == mem.summary
        assert [m["content"] for m in loaded.recent] == [
            m["content"] for m in mem.recent
        ]
        assert any("美式咖啡" in f["text"] for f in loaded.facts)

        # 快照损坏 → 从 events.jsonl 重建
        mem.state_path.unlink()
        rebuilt = make_memory(td, summarizer)
        assert rebuilt.summary == mem.summary
        assert [m["content"] for m in rebuilt.recent] == [
            m["content"] for m in mem.recent
        ]
        assert any("美式咖啡" in f["text"] for f in rebuilt.facts)
        print("PASS 持久化 + 从事件日志重建")


def test_facts_and_reset():
    def summarizer(messages):
        return "摘要"

    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(td, summarizer)
        mem.remember("用户喜欢美式咖啡")
        mem.remember("用户叫小林")
        system = mem.build_messages()[0]["content"]
        assert "美式咖啡" in system and "小林" in system

        assert mem.forget("咖啡") == 1
        assert "美式咖啡" not in mem.build_messages()[0]["content"]

        mem.reset(keep_facts=True)
        assert mem.recent == []
        assert any("小林" in f["text"] for f in mem.facts)

        mem.reset(keep_facts=False)
        assert mem.facts == []
        print("PASS 长期事实与清空")


def test_compaction_is_non_blocking():
    def slow_summarizer(messages):
        time.sleep(0.4)
        return "## 摘要\n慢慢压缩"

    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(td, slow_summarizer, compact_every_turns=2)
        mem.add_user("第一轮")
        mem.add_assistant("第一轮回答")
        started = time.monotonic()
        mem.add_user("第二轮")
        mem.add_assistant("第二轮回答")
        elapsed = time.monotonic() - started
        assert elapsed < 0.25, f"add_assistant 不应等待摘要，实际 {elapsed:.2f}s"
        assert mem.is_compacting
        mem.wait(timeout=5)
        assert mem.summary
        print(f"PASS 压缩不阻塞（add_assistant {elapsed*1000:.0f} ms）")


def test_drop_last_user():
    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(td, lambda messages: "摘要")
        mem.add_user("hi")
        mem.drop_last_user()
        assert mem.turns == 0

        mem.add_user("a")
        mem.add_assistant("b")
        mem.add_user("c")
        mem.drop_last_user()
        assert [m["content"] for m in mem.recent] == ["a", "b"]

        rebuilt = Memory(td, "sys", summarizer=None)
        assert [m["content"] for m in rebuilt.recent] == ["a", "b"]
        print("PASS 失败时撤回最后一句用户输入")


def test_reset_during_compaction_discards_summary():
    def slow_summarizer(messages):
        time.sleep(0.3)
        return "## 旧摘要\n不该出现"

    with tempfile.TemporaryDirectory() as td:
        mem = make_memory(td, slow_summarizer, compact_every_turns=2)
        mem.add_user("u1")
        mem.add_assistant("a1")
        mem.add_user("u2")
        mem.add_assistant("a2")  # 触发压缩
        mem.reset(keep_facts=True)
        mem.wait(timeout=5)
        assert mem.summary == "", "清空后旧摘要不能被写回"
        assert mem.recent == []
        print("PASS 压缩期间清空记忆会丢弃旧摘要")


def test_no_summarizer_disables_auto_compact():
    with tempfile.TemporaryDirectory() as td:
        mem = Memory(td, "sys", summarizer=None, compact_every_turns=1)
        for i in range(10):
            mem.add_user(f"u{i}")
            mem.add_assistant(f"a{i}")
        assert mem.summary == ""
        assert mem.turns == 10
        assert not mem.is_compacting
        print("PASS 没有摘要器时关闭自动压缩")


def main() -> None:
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
    print(f"\n{len(tests)} 个记忆测试全部通过 ✅")


if __name__ == "__main__":
    main()
