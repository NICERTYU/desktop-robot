# GPT-SoVITS 御姐音接入方案

> 目标：让桌面机器人用**克隆出来的御姐音**说话，替换掉 edge-tts 的"轻熟"折中方案。
>
> 结论先说：**GPT-SoVITS 不适合跑在树莓派上，也不适合在 M1 Pro 上训练**。正确分工是——
> **训练在云 GPU（一次性，约 ¥5），推理跑在你的 Mac / 云 GPU 上，树莓派只当客户端。**
> 机器人侧的客户端和双引擎回退我已经写好并联调过了（`starter/tts_gptsovits.py`、`starter/tts.py`）。

---

## 0. 架构

```
树莓派 5（机器人）                      你的 Mac / 云 GPU
┌────────────────────┐   HTTP POST    ┌─────────────────────────┐
│ voice_loop.py      │ ─────────────► │ GPT-SoVITS api_v2 :9880 │
│  ├─ ASR（本地）     │   /tts (wav)   │  ├─ GPT 模型（韵律）      │
│  ├─ LLM（云端）     │ ◄───────────── │  └─ SoVITS 模型（音色）   │
│  └─ tts.py         │                └─────────────────────────┘
│      ├─ 主：GPT-SoVITS（局域网）
│      └─ 备：edge-tts（离线兜底）
└────────────────────┘
```

- GPT-SoVITS 服务不可用 / 超时 / 没配置 → 自动回退 edge-tts，机器人不会哑掉
- 换音色、调语速只改参考音频和 prompt，机器人代码不用动

---

## 1. 先看清你的机器（MacBook Pro M1 Pro / 16 GB）

| 任务 | 能不能做 | 现实预期 |
|---|---|---|
| 推理（已训练好的模型） | ✅ 能，CPU | 一句话 1.5–5 s，首次请求更慢；16 GB 内存够 |
| 训练（1–5 分钟数据） | ⚠️ 能但极慢 | M1 Pro CPU 训练要数小时到一整天，不划算 |
| 常驻当 TTS 服务器 | ✅ 可以 | 笔记本合盖会断；适合开发调试，不适合 7×24 |
| 树莓派上跑 | ❌ 不行 | 算力和内存都不够，别试 |

> 所以路线是：**租 GPU 训练 1 小时 → 把几十 MB 的模型拉回 Mac → Mac 做推理服务**。
> 如果 Mac 不能常开，再考虑云 GPU 常驻，或者"固定台词预生成 + 动态回复用云 TTS"。

---

## 2. 三种部署路线

| 路线 | 成本 | 延迟 | 适合 |
|---|---|---|---|
| **A. Mac CPU 推理**（推荐先做） | ¥0（训练另算） | 1.5–5 s | 开发阶段、桌面演示、每天用几小时 |
| **B. 云 GPU 常驻推理** | ≈ ¥2/小时 | 0.3–1 s | 要低延迟、要 7×24、能接受按小时计费 |
| **C. 有 NVIDIA 显卡的 PC** | 一次性 | 0.5–1.5 s | 家里有游戏本/台式机，长期最舒服 |

我建议的顺序：**先 A 跑通，用真实延迟数据决定要不要升级到 B/C。**

---

## 3. 第一步：Mac 上把环境装起来

> 只做推理可以跳过训练。命令以官方 README 为准，版本更新后可能有变化。

```bash
# 依赖
brew install ffmpeg
# 建议用 conda/miniforge 建独立环境（Python 3.10）
conda create -n gptsovits python=3.10 -y
conda activate gptsovits

git clone https://github.com/RVC-Boss/GPT-SoVITS.git
cd GPT-SoVITS
pip install -r requirements.txt

# 按 README 下载预训练模型到 GPT_SoVITS/pretrained_models
# （用整合包的话，模型一般已经带好）

python webui.py        # 启动 WebUI，终端会打印地址
```

Mac 注意事项：
- `device` 必须是 `cpu`，`is_half` 必须是 `false`（MPS 支持不完整，别开）
- 内存 16 GB 跑 v2/v2Pro 推理够用，同时开浏览器 + 别的会紧张
- 用最新稳定版（v2Pro / v4 或更新，以仓库 README 为准）；版本不同，模型文件名和配置项会变

---

## 4. 第二步：训练一个御姐音（租 GPU，约 ¥5）

### 4.1 准备数据（最关键的一步）

- **1–5 分钟**干净人声：无 BGM、无混响、无噪声、单一说话人
- 音色方向：低沉、语速稳、气息足（御姐感来自"低音高 + 慢半拍 + 不飘"）
- 切成 3–10 秒的小段；采样率 32 kHz 或以上更好

### 4.2 租 GPU（AutoDL 为例）

1. 选 **RTX 4090 / 24G**，镜像选 PyTorch 2.x + CUDA，按量计费（约 ¥2.2/小时）
2. 上传音频，clone 仓库，`pip install -r requirements.txt`
3. 启动 `python webui.py`，用 AutoDL 的"自定义服务"打开 6006 端口
4. WebUI 流程：**语音切分 → ASR 标注 → 文本校对 → 训练 SoVITS → 训练 GPT → 推理试听**
   - 数据少：SoVITS 8 epoch、GPT 15 epoch 起步
   - 试听不满意就换参考音频/调整 epoch，别急着下载
5. 训练完下载两组权重：
   - `SoVITS_weights_*/xxx.pth`（音色）
   - `GPT_weights_*/xxx.ckpt`（韵律）
6. **关机**（按量实例不用就关，别挂机烧钱）

全程 1–2 小时，成本约 **¥5**。

### 4.3 没素材怎么办？

- 最稳：找朋友/自己录一段授权人声（男声变御姐不行，别硬来）
- 开源语音库：找**许可允许克隆**的中文女声数据
- ⚠️ **不要克隆真人**（尤其是公众人物、主播、艺人）。自己听没事，一旦发布视频/产品就有肖像权和声音权风险。商用前看清仓库 LICENSE（代码是 MIT，但**声音素材版权归你自己负责**）

---

## 5. 第三步：启动 API 服务

```bash
# 在 Mac（或云 GPU）上，GPT-SoVITS 目录内
python api_v2.py -a 0.0.0.0 -p 9880 -c GPT_SoVITS/configs/tts_infer.yaml
```

编辑 `tts_infer.yaml`，把权重和推理设备指对：

```yaml
custom:
  device: cpu          # Mac 用 cpu；GPU 用 cuda:0
  is_half: false       # Mac 必须 false；GPU 可以 true
  t2s_weights_path: GPT_weights_v2Pro/你的模型.ckpt
  vits_weights_path: SoVITS_weights_v2Pro/你的模型.pth
  version: v2Pro       # 与你训练的版本一致
```

自测：

```bash
curl -X POST http://127.0.0.1:9880/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "你好呀，今天想让我帮你做点什么呢？",
    "text_lang": "zh",
    "ref_audio_path": "/Users/gw/gpt_sovits/refs/yujie.wav",
    "prompt_text": "参考音频里说的那句话",
    "prompt_lang": "zh",
    "streaming_mode": false,
    "media_type": "wav"
  }' -o test.wav

afplay test.wav
```

> 参考音频 3–10 秒即可，但 **`prompt_text` 必须和音频逐字一致**，差一个字音色就会飘。

---

## 6. 第四步：接进机器人（已完成，直接用）

机器人侧代码：

| 文件 | 作用 |
|---|---|
| [tts_gptsovits.py](starter/tts_gptsovits.py) | HTTP 客户端，纯标准库，请求 `/tts` 拿 wav |
| [tts.py](starter/tts.py) | 双引擎调度：GPT-SoVITS 为主，失败自动回退 edge-tts |
| [voice_loop.py](starter/voice_loop.py) | 已改成调用 `tts.synthesize()`，按环境变量切换引擎 |
| [test_tts_client.py](starter/test_tts_client.py) | mock 测试，不需要真实服务也能验证客户端 |

启用：

```bash
export TTS_ENGINE=gptsovits
export GPTSOVITS_URL=http://192.168.1.10:9880        # Mac 的局域网 IP
export GPTSOVITS_REF_AUDIO=/Users/gw/gpt_sovits/refs/yujie.wav
export GPTSOVITS_PROMPT_TEXT="今天想让我帮你做点什么呢"
export GPTSOVITS_SPEED=1.05

python starter/voice_loop.py
```

注意 `GPTSOVITS_REF_AUDIO` 是**服务器上的路径**（Mac 或云端的路径），不是树莓派的。

已验证：
- `python starter/test_tts_client.py` → 成功路径 / 连接失败 / 缺参数 全部通过
- GPT-SoVITS 没开时，`voice_loop` 会自动回退 edge-tts（日志里能看到 `回退 edge-tts`）

---

## 7. 延迟与体验优化

| 手段 | 效果 |
|---|---|
| **预热**：启动后先合成一句"嗯" | 避免第一次请求等模型加载（可能 5–10 s） |
| 短句 + `text_split_method: cut5` | 一次合成 10–20 字，快且稳 |
| `speed_factor: 1.05–1.15` | 御姐音稍快一点更自然，也省时间 |
| 缓存固定台词 | "你好呀""我在呢"预生成 wav，0 延迟 |
| 填充音 | 等 TTS 时先播"嗯…"或让表情切到 thinking，用户感知延迟减半 |
| 流式 | `streaming_mode: true` 可以边生成边播，但客户端要改写成分块播放，建议第 9 周再做 |
| 局域网有线 / 5GHz | 别让 WiFi 成为瓶颈 |

**延迟预算（目标）**：ASR 0.5 s + LLM 0.5–1 s + TTS 0.5–1.5 s ≈ **2–3 s**。超过 4 s 体验就会明显变差，那时再上云 GPU。

---

## 8. 口型同步（换音色不影响）

表情屏现在用**音量包络**驱动嘴型，和 TTS 引擎无关：

```
播放 wav → 每 50 ms 算一次 RMS → 映射到 mouth_open(0~1) → 推给表情屏
```

以后要做精确口型，再考虑音素对齐（viseme），但那是第 10 周之后的优化。

---

## 9. 验收清单

- [ ] Mac 上 `python webui.py` 能打开，参考音频推理出**像御姐**的声音
- [ ] `api_v2.py` 启动，`curl` 能拿到 wav
- [ ] 机器人执行 `test_tts_client.py` 全绿
- [ ] 设 `TTS_ENGINE=gptsovits`，`voice_loop.py` 说出御姐音
- [ ] 拔掉 GPT-SoVITS 服务，机器人自动回退 edge-tts，不崩溃
- [ ] 记录端到端延迟（录音结束 → 开口），目标 < 3 s

---

## 10. 常见问题

| 现象 | 原因 / 解决 |
|---|---|
| `HTTP 400: ref_audio_path not found` | 路径是**服务器**上的路径，不是机器人的 |
| 音色不像、忽高忽低 | `prompt_text` 与参考音频不一致；或参考音频有噪声/多人 |
| 第一次请求特别慢 | 模型加载，做预热；或加大超时 |
| Mac 上极慢 | 确认 `device: cpu`、`is_half: false`；关掉其他大程序 |
| 端口连不上 | `api_v2.py` 绑 `0.0.0.0`；macOS 防火墙放行；同一局域网 |
| 声音断续/破音 | 降低 `temperature`、换参考音频、缩短单次文本 |
| 返回 JSON 而不是 wav | API 版本参数变了，对照该版本 `api_v2.py` 的请求字段调整客户端 |

---

## 11. 下一步

1. **先确认训练路线**：租 GPU（约 ¥5）还是找现成模型？我建议租 4090 一次训到位
2. 训练好后把两个权重 + 参考音频路径填进 `tts_infer.yaml`
3. 跑 `test_tts_client.py`，再跑 `voice_loop.py`，记录延迟
4. 如果 Mac 不能常开，告诉我，我再帮你把推理搬到云 GPU（或做"固定台词预生成缓存"的混合方案）
