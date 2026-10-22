# starter：机器人的软件骨架

按依赖从少到多排列，每个模块都能单独跑、单独测。

## 目录

| 文件 | 作用 | 依赖 |
|---|---|---|
| `voice_loop.py` | 主程序：录音 → ASR → 多轮对话（自动压缩）→ TTS → 播放 | 见 requirements.txt |
| `memory.py` | 记忆：事件日志 + 快照 + 后台自动摘要压缩 | 无 |
| `dialogue.py` | 旧版滑动窗口记忆（Phase 1，保留作参考） | 无 |
| `tts.py` | 双引擎 TTS：GPT-SoVITS 为主，edge-tts 兜底 | edge-tts |
| `tts_gptsovits.py` | GPT-SoVITS HTTP 客户端 | 无 |
| `tts_audition.py` | 生成一批 edge-tts 音色样本供试听 | edge-tts |
| `face/face.html` | 抽象机器人表情屏（浏览器直接打开） | 无 |
| `face/whale_face.html` | 鲸鱼娘（同人风格）表情屏 | 无 |
| `test_memory.py` | 记忆 / 自动压缩测试 | 无 |
| `test_dialogue.py` | 旧版记忆测试 | 无 |
| `test_tts_client.py` | GPT-SoVITS 客户端 mock 测试 | 无 |

## 快速开始

```bash
pip install -r starter/requirements.txt

export LLM_API_KEY=sk-xxxx
export LLM_BASE_URL=https://api.deepseek.com/v1   # 可选
export LLM_MODEL=deepseek-chat                    # 可选

python starter/voice_loop.py
```

默认用 edge-tts（轻熟女声参数）。想换 GPT-SoVITS 御姐音：

```bash
export TTS_ENGINE=gptsovits
export GPTSOVITS_URL=http://192.168.1.10:9880
export GPTSOVITS_REF_AUDIO=/abs/path/ref_yujie.wav
export GPTSOVITS_PROMPT_TEXT=参考音频里说的那句话
```

## 记忆与自动压缩

记忆存在 `~/.robot_memory/`（可用 `MEMORY_DIR` 改）：

```
events.jsonl   只追加的事实日志，可回放
state.json     快照：摘要、最近对话、长期事实
```

压缩规则：

| 条件 | 默认值 |
|---|---|
| 距上次压缩的轮数 | `COMPACT_EVERY_TURNS=6` |
| 上下文 token 估算 | `CONTEXT_TOKEN_BUDGET=6000` |
| 压缩时保留最近几轮 | `KEEP_RECENT_TURNS=4` |
| 自动压缩开关 | `AUTO_COMPACT=1` |

- 满足任一条件就在**后台线程**摘要，不阻塞说话
- 摘要失败只提示，原对话保留
- 快照损坏会从 `events.jsonl` 重建
- 压缩会多一次 LLM 调用（约 200–300 字输出）

命令：

| 输入 | 作用 |
|---|---|
| 回车 | 开始录音 |
| `q` / `退出` | 退出（等待后台压缩完成） |
| `clear` / `清空` | 清空对话，保留长期事实 |
| `compact` / `整理记忆` | 立即压缩 |
| `history` / `历史` | 看摘要 + 事实 + 最近对话 |
| `记住 xxx` | 写入长期事实 |
| `忘记 xxx` | 删除匹配的长期事实 |

## 测试

```bash
python starter/test_memory.py        # 9 个记忆测试
python starter/test_dialogue.py      # 6 个旧版测试
python starter/test_tts_client.py    # 3 个客户端测试
```

都不需要网络和 API key。
