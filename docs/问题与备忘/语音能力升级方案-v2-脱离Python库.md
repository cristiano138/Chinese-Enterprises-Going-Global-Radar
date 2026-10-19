# 语音能力升级方案 v2：不用 Python 库，换独立开源引擎

> 约束更新（比 v1 更强）：**不引入 Python ASR 库**，引擎从 GitHub 取成熟项目。
> 形成日期：2026-10-19

---

## 0. 先对齐一句话

"语音功能太薄弱"其实是**三个层面的薄弱**，换模型只能解决第一层：

| 层面 | 现状 | 用户体感 |
| --- | --- | --- |
| **精度层** | `small` + `int8` + `beam_size=1` + 零热词 | 说「毛绒玩具」出「猫绒玩具」，路由直接归零 |
| **能力层** | 只能录 **1 句 / 60 秒**、不能中英混说、无热词、无置信度、无纠错 | "玩具级功能" |
| **部署层** | `faster-whisper` 在 `requirements-asr.txt`，而创空间只装 `requirements.txt` | **线上大概率根本没有本地引擎**，云端一抖就"不可用" |

> 第 3 条是最致命的：`ms_deploy.json` 是 `sdk_type: gradio` + `platform/2v-cpu-16g-mem`，
> 平台只读 `requirements.txt`。也就是说部署到创空间后，`_local_importable()` 大概率返回 False，
> 语音要么靠云端 ASR 撑着，要么整个入口是灰的。这解释了为什么"功能薄弱"——它不是弱，是**根本没真正上过线**。

---

## 1. 方案选型：GitHub 上的三个候选

| 候选 | 许可证 | 交付形态 | 中文 CER | CPU 速度 | 与现有代码的距离 |
| --- | --- | --- | --- | --- | --- |
| **sherpa-onnx**<br>`k2-fsa/sherpa-onnx` | Apache-2.0 | 预编译 **Windows/Linux x64 二进制**，`sherpa-onnx-offline` 可执行文件 | SenseVoice int8 **7.81%** | 官方 CPU 17x 实时 | 需新增一个引擎适配层（约 150 行，纯标准库） |
| **whisper.cpp**<br>`ggml-org/whisper.cpp` | MIT（5.3w star） | `whisper-bin-x64.zip`，含 `whisper-cli` + **`whisper-server`** | large-v3 约 8-12%（短句） | 2 vCPU 上 large 偏慢，turbo 可用 | **几乎为零**：`whisper-server` 暴露 OpenAI 兼容 `/v1/audio/transcriptions`，现有 `_transcribe_cloud()` 改个 BASE 就能接 |
| FunASR runtime | MIT | Docker 镜像 / WebSocket 服务 | SenseVoice 7.81% | 最快 | 创空间**没有 Docker**，直接排除 |

### 结论

**主引擎 sherpa-onnx + SenseVoice int8；whisper.cpp `whisper-server` 作为"半天先通"的过渡和备用通道。**

选 sherpa-onnx 的四个决定性理由：

1. **它自带了我上一轮建议手写的东西** —— SenseVoice 支持同音词替换
   （`lexicon.txt` + `replace.fst`），把「猫绒玩具→毛绒玩具」这类纠错变成**配置**而不是代码；
2. 模型原生支持 **中/英/日/韩/粤**，中英混说（"把 wireless earbuds 卖到德国"）不用切语言；
3. 内置 **Silero VAD**，长音频分段、伪流式出字都靠它，不必自己实现；
4. 纯 ONNX Runtime，**不依赖 PyTorch / CTranslate2**，2 vCPU 够用，包体可控。

---

## 2. 目标架构

```
浏览器录音（前端 16k 单声道 WAV）
        │
        ▼
app_main.py  ── 录音/回显/纠错 chips/置信度着色
        │
        ▼
core/asr.py  三层后端（保留现有契约）
   ├─ ① cloud   : OpenAI 兼容 /audio/transcriptions（已有，不动）
   ├─ ② engine  : ★新增 —— 外部二进制，subprocess 调用
   └─ ③ off     : 全不可用 → 入口置灰，打字不受影响
        │
        ▼
core/asr_engine.py  ★新增（**只用标准库**：subprocess / urllib / json / hashlib / shutil）
   ├─ ensure_engine()  首次下载二进制 + 模型（SHA256 校验，失败即返 None）
   ├─ transcribe(wav)  调 sherpa-onnx-offline，解析结果
   └─ warmup()         启动预热，避免第一次点录音等 3 秒
        │
        ▼
sherpa-onnx-offline  ← SenseVoice int8 模型（229MB）+ Silero VAD
        │
        ▼
词表校验（lexicon.txt / replace.fst）→ modules/m15_router.py（一行不改）
```

**关键收益：`requirements-asr.txt` 整个文件可以删掉。**
连带 `av<19` 那个版本锁死坑、CTranslate2、PyTorch 依赖链一起消失。

---

## 3. 引擎调用（唯一需要实测的地方）

```bash
sherpa-onnx-offline \
  --tokens=<model>/tokens.txt \
  --sense-voice-model=<model>/model.int8.onnx \
  --sense-voice-use-itn=true \
  --sense-voice-hr-lexicon=<model>/lexicon.txt \
  --sense-voice-hr-rule-fsts=<model>/replace.fst \
  input.wav
```

- 输出走 stdout（文本行），`--debug=false` 关掉日志噪声；
- 参数名以 `v1.13.x --help` 实测为准（本方案给出的是官方示例的写法，落地前必须跑一遍确认）；
- Python 侧用 `subprocess.run([...], capture_output=True, timeout=N, env=...)`，
  **不 shell=True**，路径全部列表传参，避免注入与空格问题；
- 现有 `_work_slots`（`BoundedSemaphore(2)`）复用，但在 2 vCPU 上建议降到 **1**，
  否则两路并发互相抢占，单片延迟翻倍。

### 媒体依赖怎么办？

引擎自己读 WAV（我们 `_read_wav()` 已保证是合法 PCM WAV）。
`_read_wav` 里那句"必须是普通 WAV"的校验正好成了天然护城河，不需要 ffmpeg。

---

## 4. "功能太薄弱"的正面补齐（这部分比换引擎更影响观感）

| # | 现状 | 升级后 | 实现位置 |
| --- | --- | --- | --- |
| 1 | 单句 60s 上限 | **180s**，VAD 分段后逐段转写拼接 | `_read_wav` 放宽 + 引擎侧 VAD |
| 2 | 转写完才一次性出字 | **伪流式**：每段 VAD 结束就回填一段，首字 <2s | `app_main.py` 分段回调 |
| 3 | 零热词 | 从 `m15_router.CATEGORY_WORDS/MARKET_WORDS` + 法规缩写**自动生成**热词与同音替换表 | `scripts/build_asr_lexicon.py` |
| 4 | 中英混说易崩 | SenseVoice 原生多语，不强制 `language=zh` | 引擎参数 |
| 5 | 无置信度 | meta 增加 `confidence`，<0.6 回声块变黄提示核对 | `core/asr.py` + `app_main.py:1092` |
| 6 | 错了只能整句重说 | 识别后给「可能是这些词」chips，点击替换 | `app_main.py` 回声块 |
| 7 | 超时=失败 | 超时按"段"计，已出的段不丢 | `transcribe()` 契约扩展 |
| 8 | 太小声/没录到无提示 | 峰值/RMS 质检，**不发引擎**直接提示 | `_read_wav` 之后 |

> 第 3 条是这次真正的"免费午餐"：项目词表本来就存在且封闭（7 品类 + 2 市场），
> 现在第一次真正喂给识别引擎，而且是**硬偏置**（FST 同音替换），比 Whisper 的 soft prompt 强。

---

## 5. 落地步骤（预计 1.5–2 天）

| 步 | 动作 | 产出 | 工时 |
| --- | --- | --- | --- |
| 1 | 本机跑通：下 `sherpa-onnx-win-x64` + SenseVoice int8，命令行转 3 条真实录音，记录耗时与准确率 | 一份实测结论（决定是否继续） | 2h |
| 2 | 写 `core/asr_engine.py`，接入 `core/asr.py` 的 `engine` 后端 | 代码 + `python core/asr.py` 自检通过 | 3h |
| 3 | `scripts/build_asr_lexicon.py`：从路由词表生成 `lexicon.txt` / 热词表 | 生成物 + 覆盖率检查 | 2h |
| 4 | Linux 侧：`scripts/prepare_asr_engine.py` 下载 linux-x64 二进制与模型到 `~/.cache/compliance-radar/asr/`，带 SHA256 | 一条命令准备环境 | 2h |
| 5 | UI：置信度着色 + 纠错 chips + 180s | `app_main.py` 三处小改 | 3h |
| 6 | 评测：30 条真实口述（不进仓库），算 CER / **槽位准确率** / 幻觉率 / P95 延迟 | `scripts/eval_asr.py` + 前后对比表 | 3h |

**验收线**：槽位准确率 ≥ 95%，幻觉率 = 0，5 秒语音 P95 ≤ 2s，60 秒语音 ≤ 8s。

---

## 6. 风险与待确认（这三点不定，方案没法落地）

1. **创空间能否访问 GitHub / ModelScope？**
   - 能 → 启动时下载（推荐，仓库干净）
   - 不能 → 二进制 + 229MB 模型必须随包分发，可能撞 git 单文件限制，需改走 ModelScope 数据集挂载
2. **229MB 模型体积能否接受？**
   - 可接受 → SenseVoice int8（推荐）
   - 不可接受 → 退 Paraformer-small / Whisper-tiny，精度会掉一档
3. **是否需要保留离线能力？**
   - 是（当前卖点）→ 走本条路线
   - 否 → 直接接阿里云/讯飞 HTTP ASR，只要 `requests`，2 小时能上，但会破坏"零密钥可跑"

---

## 7. 与 v1 方案的关系

v1（`语音识别精度-诊断与解决方案.md`）的技术判断仍成立，但实施方式整体替换：

| v1 做法 | v2 做法 | 原因 |
| --- | --- | --- |
| `pip install faster-whisper` | 下载预编译二进制 | 用户明确要求不用 py 库 |
| 改 `beam_size=1→5` | 换 SenseVoice（非自回归，无 beam 概念） | 换引擎后参数问题消失 |
| 手写 `core/asr_lexicon.py` 纠错 | 用 SenseVoice 的 `lexicon.txt + replace.fst` | 现成的、更快、效果更硬 |
| 保留 `av<19` 锁 | 删掉整个 `requirements-asr.txt` | 依赖链消失 |
| 置信度/热词/质检 | **保留不变** | 与引擎无关，仍要做 |

---

## 8. 备选快车道（如果只有半天时间）

只做这一件事：**`whisper.cpp` 的 `whisper-server`**。

```bash
whisper-server.exe -m ggml-large-v3-turbo-q5_0.bin --host 127.0.0.1 --port 8080 --convert
```

然后把 `.env` 里改成：

```
ASR_BACKEND=cloud
ASR_API_BASE=http://127.0.0.1:8080/v1
ASR_API_KEY=not-needed
ASR_MODEL=whisper-1
```

现有云端代码**一行不改**就能工作 —— 这是"最小代价先让线上有语音"的路径。
缺点是中文精度不如 SenseVoice、2 vCPU 上 turbo 也偏慢，属于应急而非终局。

---

## 9. 实施结果（2026-10-19，已落地）

方案已按「sherpa-onnx + SenseVoice」实施完毕，基线为上游 `2a2fcdc`（2026-10-19 15:23）。

### 9.1 新增与改动

| 文件 | 变更 |
|---|---|
| `core/asr_engine.py` | **新增**。引擎定位/下载/解包/调用，只用标准库（`subprocess`/`urllib`/`tarfile`/`hashlib`） |
| `core/asr.py` | 新增 `engine` 后端；`auto` 顺序改为 云端 → engine → local → off；新增 `prewarm()`；引擎异常统一折成 `_ASRFailure` |
| `scripts/prepare_asr_engine.py` | **新增**。一条命令准备引擎与模型，支持 `--check` / `--force` / `--mirror` |
| `scripts/selftest_asr_engine.py` | **新增**。17 项离线测试（路径、下载闸门、压缩包逃逸、输出解析、后端降级） |
| `scripts/selftest_all.py` | 门禁从 16 个入口扩到 17 个 |
| `scripts/selftest_asr_safety.py` | 固定 `_engine_ready` 让用例确定；修正 Windows 上 50ms 预算导致的误判（见 9.4） |
| `app_main.py` / `ui_chat.py` | 启动预热 `asr.prewarm()`；禁用态文案改为指向准备脚本 |
| `requirements-asr.txt` | 清空依赖，改为说明文件（不再 `pip install`） |
| `.env.example` / `README.md` / `docs/07-运行指南.md` / `THIRD_PARTY_NOTICES.md` | 同步引擎说明与许可（sherpa-onnx Apache-2.0；SenseVoice 权重单独许可） |

### 9.2 实测数据（本机 Windows / 2 线程 / CPU）

| 项目 | 结果 |
|---|---|
| 引擎版本 | sherpa-onnx v1.13.8（win-x64 shared-MT-Release-no-tts，22MB） |
| 模型 | SenseVoice int8 2024-07-17（229MB） |
| 中文 test_wavs/zh.wav（5.6s） | `开饭时间早上9点至下午5点`，计算 0.36s（RTF 0.064） |
| 命令行后端（冷启动） | **3.47s/次**（约 3s 模型加载 + 0.4s 计算） |
| 常驻服务后端（第二轮） | **0.33–0.42s/次**，服务启动 3.15s（只在应用启动时付一次） |
| 端到端（Gradio API 实测） | `/transcribe` 往返 0.82s（含音频上传），内部 0.37s |
| 英文 / 粤语 | `The tribal chieftain called for the boy...` / `呢几个字都表达唔到我想讲嘅意思` |
| 静音 1s | 返回空转写 + "没听清"，**没有幻觉文本** |
| 页面冒烟 | HTTP 200，语音入口为启用态；`/undo_voice` 可撤销回识别前文字 |

### 9.2.1 常驻服务与预编辑（第二轮已落地）

| 文件 | 变更 |
|---|---|
| `core/asr_server.py` | **新增**。管理 `sherpa-onnx-offline-websocket-server` 子进程；**手写最小 WebSocket 客户端**（握手 / 掩码 / 126·127 扩展长度 / 分片 / ping-pong / close），仍然零第三方依赖 |
| `core/asr_engine.py` | 转写优先走常驻服务，失败自动退回命令行；新增 `warmup()` / `server_state()` / `stop_server()` |
| `core/asr.py` | 启动预热由「只下载」升级为「下载 + 拉起常驻服务」 |
| `ui_chat.py` | 预编辑态：识别结果以**未提交草稿**进入输入框，状态条显示「预编辑 · 未提交」；新增「撤销识别」回调，恢复识别前文字（改过字则不覆盖，避免吞掉用户修改） |
| `scripts/selftest_asr_server.py` | **新增** 22 项离线测试：帧长度、分片、ping/pong、close、对端断开、WAV 转换、状态与降级 |
| `scripts/selftest_voice_confirmation.py` / `selftest_chat_ui.py` | 契约从 2 元组升级为「输入框 + 状态 + 预编辑快照」，并补撤销语义用例 |

**协议要点**（照 sherpa-onnx 官方 client 示例实现）：
单条消息 = `采样率(4B LE int32) + 数据字节数(4B LE int32) + float32 采样点`，
超过 10240 字节分片发送；服务端收满即解码，回一条 JSON 文本。

### 9.3 已知限制（下一步）

1. ~~冷启动约 3 秒~~ —— **已解决**：常驻服务把单次转写压到 0.33s。遗留代价是应用启动时
   多一次 3 秒的模型加载（在后台线程里做，不挡首屏）。
2. **热词仍未接入**：SenseVoice 支持 `lexicon.txt + replace.fst` 同音替换，但生成 FST
   需要 `pynini`（会引入 Python 依赖），与「不用 py 库」冲突，暂缓；先用路由层词表兜底。
3. **尚未真正"边说边出字"**：Gradio 6.2 的 `gr.Audio(streaming=True)` 具备流式事件基础，
   但要做成输入法那种 partial 覆盖，需要前端分片上传 + 服务端并发转写节流，
   本轮没做（当前是"说完 0.3 秒出字"）。
4. **60 秒上限未放开**：引擎本身可处理更长音频，但 2 vCPU 上的等待时间与超时预算需重算。
5. **部署侧**：`models/` 被 `.gitignore` 排除，创空间需在部署分支预置引擎与模型，或依赖
   启动预热下载（国内需配 `ASR_ENGINE_BASE_URL` 镜像）。

### 9.4 顺手修掉的一个历史问题

`selftest_asr_safety.py::test_timeout_retains_two_slots...` 在原代码上**本来就失败**（用原始
`core/asr.py` 复现过）：超时预算设 0.05s，而 Windows 上新建缓存文件 + `fsync` 实测要 0.06s，
导致"本该成功的那次"被误判超时。已把预算调到 0.2s 并加注释，测试语义（超时占槽、迟到结果不落缓存）不变。
