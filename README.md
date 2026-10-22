# 桌面机器人：机械臂 + 鲸鱼娘表情屏 + 语音对话

一个从零搭建的桌面陪伴机器人项目：**5 自由度总线舵机机械臂 + 7 寸表情屏 + 语音识别 + LLM 多轮对话**。

> 当前状态：软件骨架可运行，硬件方案已定（¥2550 清单），机械臂待采购装配。

![鲸鱼娘·开心](starter/face/whale_happy.png)

## 现在能跑什么

| 能力 | 实现 |
|---|---|
| 语音闭环 | 录音 → faster-whisper → LLM → edge-tts / GPT-SoVITS 播放 |
| 多轮记忆 | 事件日志 + 状态快照 + 后台自动摘要压缩（失败不丢历史） |
| 表情屏 | 抽象机器人脸、鲸鱼娘（同人风格）各 8 种情绪，纯 Canvas |
| 文档 | 学习路线、3 千元采购清单、GPT-SoVITS 接入、记忆系统设计 |

## 快速开始

```bash
pip install -r starter/requirements.txt

export LLM_API_KEY=sk-xxxx          # 任意 OpenAI 兼容 API
export TTS_ENGINE=edge              # 或 gptsovits

python starter/voice_loop.py
```

表情屏不需要任何依赖，浏览器直接打开：

```bash
open starter/face/whale_face.html
# 键盘 1–8 切换情绪，点击画面轮换
```

## 目录结构

```
starter/                    软件骨架
  voice_loop.py             主程序：录音 → ASR → 多轮对话 → TTS
  memory.py                 记忆：事件日志 + 自动摘要压缩
  dialogue.py               旧版滑动窗口记忆（参考）
  tts.py / tts_gptsovits.py TTS 双引擎（GPT-SoVITS 主，edge-tts 兜底）
  tts_audition.py           生成音色试听样本
  face/face.html            抽象机器人表情屏
  face/whale_face.html      鲸鱼娘表情屏（同人风格）
  test_memory.py            记忆 / 自动压缩测试（9 个）
  test_dialogue.py          旧版记忆测试（6 个）
  test_tts_client.py        TTS 客户端 mock 测试（3 个）

机械臂表情屏_学习路线.md      完整知识地图 + 12 周计划
你的学习计划_零硬件基础.md    针对会 Python 的人重排的 10 周计划
执行方案_3000元桌面版.md      ¥3000 桌面版：BOM、供电、装配、下单节奏
GPT-SoVITS接入方案.md        御姐音克隆：训练、API、延迟优化
机器人记忆系统设计.md         参考 DSH 的轻量记忆架构
```

## 硬件方案（摘要）

| 部分 | 内容 | 预算 |
|---|---|---|
| 手臂 | 5× Feetech STS3215-C018（12V 30KG）+ PETG 打印件 | ¥810 |
| 大脑 | 树莓派 5 8GB 全套 | ¥785 |
| 表情屏 | 7 寸 HDMI 1024×600 | ¥260 |
| 音频 | USB 麦克风 + 小音箱 | ¥225 |
| 电控安全 | 12V/10A、5V 降压、保护件、急停、万用表、线材、底座 | ¥470 |

详见 [执行方案_3000元桌面版.md](执行方案_3000元桌面版.md)，以及可直接下单的 [采购清单_最终版.md](采购清单_最终版.md)（¥2550，分两批）。

## Roadmap

- [x] 语音闭环（ASR + LLM + TTS）
- [x] 多轮记忆 + 自动摘要压缩
- [x] 两套表情屏（8 情绪、眨眼、嘴型、气泡/水花）
- [ ] 表情屏与语音状态机联动（listen / think / speak + 音量嘴型）
- [ ] 机械臂采购与装配
- [ ] 运动学 / 轨迹规划 / 技能库
- [ ] 摄像头视觉
- [ ] 树莓派 kiosk 部署

## 说明

- 鲸鱼娘形象为 **Canvas 手绘的同人风格设计**，非 DeepSeek 官方素材；DeepSeek 名称与商标归其所有。请勿直接商用官方形象。
- 仓库暂未添加开源许可证（默认保留所有权利）。如需开源，请自行添加 `LICENSE`。
- **不要把 API Key、`.credentials.yaml`、个人记忆数据提交到仓库。**
