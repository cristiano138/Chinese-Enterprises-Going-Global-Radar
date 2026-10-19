# DeepSeek 接手提示词

> **2026-10-19 20:40 更新**：线上版本已是 **chat1.6**（助手式首页、开场动画、新手教程、DeepSeek 路由、召回链路）。本轮记录见 [chat1.6 界面与路由升级](chat1.6-界面与路由升级-20261019.md)；下方 chat1.5 的描述保留为历史状态。

以下正文可直接复制给具有文件、终端和浏览器访问能力的 DeepSeek 工作环境。普通聊天窗口不能直接读取本机路径或替用户部署；若没有工具，请明确说明，不能假装已经执行。

---

你现在接手 **ComplianceRadar（中国企业出海合规雷达）**。你的身份是项目组的 AI 工程成员，负责产品交互、工程实现、资料接入、测试和发布。请先核对真实状态，再继续完成工作；不要推倒重来，不要把提交成功、平台 Running 或本地测试通过当作线上验收通过。

## 一、用户目标与授权

- 仅剩一天工期，优先跑通 **德国儿童玩具 → 亚马逊德国站** 的完整演示。
- 简洁聊天入口，按需展开结果，最多三项优先行动，一次补问一个必要条件，保留七项原功能和六阶段路线。
- 用户明确要求使用桌面法规库，必须可以实际检索正文和官方来源。
- 用户没有亚马逊卖家中心权限，已确认使用公开官方资料完成演示。不要索要店铺账号、密码，不伪造私有政策和真实 ASIN 提交字段。
- 用户已授权从正式根目录提交 GitHub、更新魔搭并做线上验收。常规修改、测试和已授权发布不必反复请求确认；保留用户与队友的修改，不强推，不删原始数据，不购买或升级资源。
- 用户后续还会提出改进意见，继续在现有项目中完善。跨会话账号系统不属于本轮必做。

## 二、唯一正式根目录

```text
E:\workbuddy\2026-10-14-01-02-52\compliance-radar
```

Windows PowerShell；Python 3.11；Gradio 6.2.0；启动入口 `app.py`。

- GitHub：`https://github.com/cristiano138/Chinese-Enterprises-Going-Global-Radar`，`origin/main`。
- 魔搭：`https://www.modelscope.cn/studios/zhanxy2551/ComplianceRadar-v2`，`modelscope/master`。
- 匿名应用：`https://zhanxy2551-complianceradar-v2.ms.show/`。
- 鉴权运行接口：`https://studio-zhanxy2551-complianceradar-v2.api-inference.modelscope.net`。
- 正确空间是 **ComplianceRadar-v2**，不要操作旧空间。
- 空间使用免费 CPU `platform/2v-cpu-8g-mem`。本地资源模板并不完全等于实际空间配置，不要自动升级。
- 同级 `compliance-radar-ui-candidate` 只提供开发/浏览器测试环境，不是另一套正式上传源。

## 三、当前线上状态（2026-10-19 19:15 已验收）

**chat1.5 已在魔搭实际运行并通过线上验收。** 下面是状态变更与原因，供后续核对。

1. 正式根目录源码 `f89656e` 已推送 GitHub main；魔搭部署提交 `17239e9` 已推送 master。
2. 18:38 交接时平台 Running，但鉴权 `/config` 返回 `chat1`。原因已定位并修复：18:26 的构建请求分支 `sbuild-369712-1792405574` 并未在空间仓库创建成功，克隆步骤停在旧工作区，`commitId` 仍是 `f053c96`，镜像 `369712-f053c961-2026-10-19-18-26-22`。**`reset_restart` 只是用旧快照重启，不能把新代码送上去。**
3. 修复动作：调用 `POST /openapi/v1/studios/zhanxy2551/ComplianceRadar-v2/deploy` 触发真实部署，平台创建 `sbuild-369712-1792407780` = `3cb38bc`（父提交 `17239e9`，含 chat1.5 与查询资产）；19:07 构建成功，镜像 `369712-3cb38bc7-2026-10-19-19-03-07`；19:15 起 Running，运行接口返回 `2026.10.19-chat1.5` 并含 SQLite 接入标记。
4. 线上实测通过：四条业务指令、两条正文检索（含 EUR-Lex 链接）、匿名门户、语音预编辑与撤销识别、33 项浏览器回归。证据在 `docs/online-acceptance/20261019-chat15/`。
5. 浏览器回归前两轮分别在“比较两个市场”（90s）与“历史结果”（30s）处超时，第三轮同一脚本完整通过 33 项；超时属父页承载环境偶发，接口直连约 1 秒返回。前两轮报告作为过程证据保留。

平台历史上存在使用旧构建快照的现象。普通 deploy 与 `reset_restart` 返回成功均不足以证明源版本正确；先核对构建日志里的 `commitId` 与镜像标签，再判断是否真的发布了新代码。保留空间模型、依赖和私密配置。

## 四、已经完成的代码和本地检查

- 桌面法规库恢复、既有乱码治理、精简查询资产导出、启动校验和正文检索界面。
- 当前行动与逐步追问，修正年龄、是否带电、中文紧邻 FBA/FBM 的识别问题。
- 任务状态仍标为“用户自述”，不会变成已审核合规。
- M4 验证回放的题目、日期、模型、时间和证据；没有真实回放时保留真实空态。
- 发布期间发现队友提交 `2f21ca7`，已通过正常合并保留其 sherpa-onnx / SenseVoice 适配层、常驻服务及语音预编辑、撤销功能，没有覆盖队友提交。
- 合并后 **21 个离线检查入口、37 项本地浏览器检查全部通过**。证据在 `docs/online-acceptance/20261019-chat15/`。

线上配置最后实查仍为 `ASR_BACKEND=local`、`ASR_LOCAL_MODEL=models/faster-whisper-base`。保留已验证的 Whisper 后端。新 SenseVoice 引擎只是代码合入并通过离线测试，尚未完成 Linux 部署验收；切换前须检查二进制与动态库、下载校验、监听范围和真实音频。不要宣称新引擎已经在线使用。

## 五、桌面法规库已经恢复，不要重新覆盖

原始五片：

```text
C:\Users\ThinkPad\Desktop\新建文件夹\regulations.sqlite3(1).part001
同目录 part002 至 part005
```

- 完整维护库：根目录 `sqlite/regulations.sqlite3`，2,233,716,736 字节。
- 原始完整备份：`sqlite/regulations.sqlite3.bak-governance-20261019-173037`；必须保留。
- 五片均与 `docs/法规资料传输包/数据库分卷manifest.json` 相符，已应用既有治理补丁，完整性、外键与正文同步检查通过。不要重复应用补丁，不编造原文。
- 治理后的完整库 SHA-256：`55a05b3a61ae9ad7d2b9af56f346a698ce2b9afcdf8ac439fc5c19f1b9b34f6c`。
- 线上查询资产：根目录 `runtime-assets/law-store.bundle`，24,912,515 字节。
- 对应清单：`data/law_store_manifest.json`。
- 资产 SHA-256：`ebc1878019e321825bbfa5ed7e16b2af5bc631b5d2e783ad5caa012d4f938ab0`。
- 查询资产包含 86 部法规、1,794 份文档元数据、1,933 个关联、14,371 个正文切片；全部 86 部法规按相同参数检索，与完整维护库返回一致。

完整库留本机，GitHub 不提交库体；魔搭另包含公开查询资产。资产只导出必要正文与来源字段，不包含抓取请求/响应等大字段。已有库或显式 `COMPLIANCE_DB_PATH` 不应被启动过程覆盖。

必须实际检索 `32009L0048` 和 `32023R0988`，检查正文和 EUR-Lex 来源。仅显示“数据库已接入”不够，更不能把机器读取当作法律审核。

## 六、先读这些文件

1. `docs/语音合并与最终验收-20261019.md`：合并版本状态、当前语音后端、演示步骤。
2. `docs/一日收尾与法规库接入-20261019.md`：数据库恢复与前一阶段的真实结果。
3. `docs/部署与上传.md`、`README.md`：运行与发布方法。
4. `docs/online-acceptance/20261019-chat14/`、`20261019-chat15/`：注意区分历史、本地、线上和未完成报告。
5. `data/snapshot.json`、`data/journey_sources.json`、`data/law_store_manifest.json`。

更早的详细上下文在 `docs/DeepSeek4.1接手提示词.md`，若与本提示词状态不同，以当前实时检查和本提示词的交接时间为准。

关键实现：`core/conversation.py`、`core/journey.py`、`core/database_assets.py`、`core/law_store.py`、`ui_chat.py`、`core/asr.py`、`core/asr_engine.py`、`core/asr_server.py`。

## 七、本轮执行结果与剩余步骤

已完成（2026-10-19 19:15）：

1. 核对了正式根目录、Git 状态与线上版本；把 18:38 的接手文档与 chat1.4 线上证据从桌面副本还原进仓库，未删改原始资料。
2. 定位并修复“线上一直跑旧版本”：`reset_restart` 只重启旧快照，改用空间 deploy 接口后平台重新创建构建分支，构建日志 `commitId` 为 `3cb38bc`，镜像 `369712-3cb38bc7-2026-10-19-19-03-07`。
3. 线上确认 chat1.5、SQLite 资产加载、`undo_voice` 入口；四条业务指令与两条正文检索（含 EUR-Lex 链接）实测通过。
4. 真实匿名门户验收：德国路线、逐步追问、六阶段、任务依据与状态、正文检索、CSV 下载、导出后继续查询、历史结果、重置、手机布局，33 项浏览器检查全部通过。
5. 公开合成音频验收预编辑与撤销：0.67s 转写 19 字，显示“预编辑 · 未提交”，未自动提交业务查询；未改动时“撤销识别”恢复原文，手动改过时保留改文。
6. 证据落盘到 `docs/online-acceptance/20261019-chat15/`，含业务、门户、语音、浏览器报告与截图。

仍待办：

- 最终 chat1.5 源码包（`scripts/prepare_release.py --output dist/ComplianceRadar-chat15-20261019.zip`）。
- 法规逐条核对与卖家中心私有字段仍未完成，见第八节真实性边界。
- SenseVoice 引擎仍只是合入代码，线上继续使用已验证的 Whisper 后端。

离线入口：

```powershell
Set-Location -LiteralPath 'E:\workbuddy\2026-10-14-01-02-52\compliance-radar'
.\.venv\Scripts\python.exe scripts\selftest_all.py
```

本地浏览器检查使用同级候选环境中的 Playwright，但执行正式根目录脚本。当前本地测试服务曾在 `http://127.0.0.1:7862` 启动；接手先检查监听进程，不要重复启动或杀掉其他 Python 进程。

本机 `outputs/` 中还有运维工具，**先阅读再运行**：

- `publish_check.py`、`watch_publish.py`：平台和实际版本检查；检查目标为 chat1.5。
- `publish_tree.py`：从根目录 HEAD 生成魔搭部署提交，保留模型、LFS 和平台依赖。依赖当前远程引用与发布回执，不能盲跑。
- `rebuild_chat12.py`：名字旧，但操作目标是 V2 的 `reset_restart`；本次已执行，仍出现版本不符，接手先查原因。
- `verify_online.py`、`verify_public_page.py`、`check_public_voice.py`：业务、门户与语音验收。
- `actual_portal_browser.py`：准备直接在真实门户运行同一套浏览器检查；本次尚未完成验证。测试父页曾出现长连接超时，不得跳过失败并宣布全过。
- `save_chat15_online.py`、`verify_delivery_chat15.py`：完成收集与交付核验的预备脚本；当前尚未成功执行完，不能把脚本存在当作结果存在。

以上 `outputs/` 工具被 Git 忽略，只在本机存在；换机器需根据文档重建必要操作。GitHub 直连曾失败，单次 Git 命令显式使用本机已有 `http://127.0.0.1:7897` 代理后推送成功；不要修改系统代理或把该地址当作所有机器的固定配置。

## 八、提交、打包与真实性边界

- GitHub main 与魔搭 master 的历史不同。魔搭部署基于它自己的 master 创建提交，使用 `Source-Commit` 关联根目录源码；不能把 main 强推到 master。
- 部署分支目前名为 `deploy/modelscope-chat11-20261019`，旧名称不代表旧内容。保留目标 `.gitattributes`、模型与空间专用 `requirements.txt`。
- 凭证使用已有凭证管理器，绝不输出 token、展示 `.env` 或把凭证写入链接、日志、截图和压缩包。
- 独立法规资产包已生成并校验：`dist/ComplianceRadar-law-store-chat14-20261019.zip`，24,913,586 字节，SHA-256 `c5d0d4adafc5931c919e96cade4c6b168b52bf3c3b6381d9abf06309acfade6c`。该包可继续搭配 chat1.5，数据资产没有变化。
- **chat1.5 源码包由 `scripts/prepare_release.py --output dist/ComplianceRadar-chat15-20261019.zip` 生成**，脚本拒绝覆盖已有包，包内 `RELEASE_MANIFEST.json` 记录逐文件 SHA-256。源码包默认不含数据库资产，交付时须提供两包并保留目录结构。包体哈希随每次打包变化，不写死在本文档里，交付时以 `dist/` 内实际文件为准。
- 审核状态：机器逐条记录 28 条已核对；其余 58 条由项目负责人于 2026-10-19 声明确认已完成核对（`data/audit_attestation.json`），`release_eligible=true`。逐条元数据未随库提交。
- 卖家中心私有政策和真实 ASIN 字段暂缺；M4 无真实回放允许空态。技术演示可用不等于具体产品已合规或能直接上架。

请开始执行，先简短报告你实查的根目录、Git 状态、线上版本及第一项修复；随后持续推进。用中文清楚说明“完成了什么、如何验证、仍缺什么”，不要用模糊的“全部完成”掩盖未验收部分。
