"""多轮对话记忆的单元测试（不需要网络/API key）。

运行：
    python starter/test_dialogue.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dialogue import Conversation  # noqa: E402


def test_trim_by_turns() -> None:
    conv = Conversation("sys", max_turns=3, max_chars=10_000)
    for i in range(6):
        conv.add_user(f"用户{i}")
        conv.add_assistant(f"回答{i}")
    assert conv.turns == 3
    assert conv.messages[0]["content"] == "用户3"
    assert conv.messages[-1]["content"] == "回答5"
    assert conv.build_messages()[0]["role"] == "system"


def test_trim_by_chars() -> None:
    conv = Conversation("sys", max_turns=100, max_chars=100)
    conv.add_user("长" * 60)
    conv.add_assistant("回" * 60)
    conv.add_user("新" * 10)
    conv.add_assistant("答" * 10)
    # 至少保留最近一问一答，哪怕仍然超过预算
    assert conv.turns == 1
    assert conv.messages[-1]["content"] == "答" * 10
    assert conv.char_count() <= 20


def test_pending_user_is_kept() -> None:
    conv = Conversation("sys", max_turns=2, max_chars=10_000)
    for i in range(3):
        conv.add_user(f"u{i}")
        conv.add_assistant(f"a{i}")
    conv.add_user("正在等待回答的一句")
    assert conv.messages[-1]["role"] == "user"
    assert conv.turns <= 2


def test_drop_last_user() -> None:
    conv = Conversation("sys")
    conv.add_user("hi")
    conv.drop_last_user()
    assert conv.messages == []

    conv.add_user("a")
    conv.add_assistant("b")
    conv.add_user("c")
    conv.drop_last_user()
    assert conv.messages[-1]["content"] == "b"


def test_persistence_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "mem.json"
        conv = Conversation("sys", max_turns=5)
        conv.add_user("你好")
        conv.add_assistant("你好呀")
        conv.save(path)

        loaded = Conversation.load(path, "sys", max_turns=5)
        assert loaded.messages == conv.messages

        loaded.reset()
        loaded.save(path)
        empty = Conversation.load(path, "sys")
        assert empty.messages == []


def test_corrupt_memory_file() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "bad.json"
        path.write_text("{not json", encoding="utf-8")
        conv = Conversation.load(path, "sys")
        assert conv.messages == []


def main() -> None:
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} 个测试全部通过 ✅")


if __name__ == "__main__":
    main()
