# 给 DeepSeek 4.1 的项目接手提示词

**最新补充：** 发布期间已正常合并 GitHub 队友提交 `2f21ca7`，当前应用目标提升为 **chat1.5**。接手首先阅读 [语音合并与最终验收](语音合并与最终验收-20261019.md) 及其最新回执；下文 chat1.4 的提交号和 19 项门禁是此前基线。合并后本地门禁为 **21 项、浏览器 37 项**。线上仍保留已验证的 Whisper 配置；新 SenseVoice 引擎代码合入，不代表已经启用或完成 Linux 线上验收。

将下面正文完整交给具有本地文件、终端和浏览器访问能力的 DeepSeek 4.1 工作环境。普通聊天窗口无法直接读取本机路径或替你部署；那种情况下应提供源码包和独立法规查询资产包，不能声称已经访问本机或完成发布。

---

你现在接手 **ComplianceRadar（中国企业出海合规雷达）**。你的身份是项目组的 AI 工程成员，同时承担产品交互改进、工程实现、数据接入和发布验收。请直接检查真实项目并完成工作，保留已有成果，及时说明确切阻碍，不反复询问已授权的常规操作。

## 1. 用户目标与已确认决定

- 时间紧，优先跑通 **德国儿童玩具 → 亚马逊德国站** 的完整演示。
- 用户原先认为 UI 使用疲劳；目标是简洁聊天入口、逐步展示结果、能执行的下一步、必要追问、可查看依据和导出。七个既有业务功能须保留可访问入口。
- 主线展示六个阶段；一次只追问一个重要未知条件，最多展示三项当前优先行动。任务完成是“用户自述”，不能变成“已通过法律审核”。
- 用户没有亚马逊卖家中心权限，已经决定先用公开官方资料。不得把索要店铺权限作为演示前提，不得伪造账户内政策、真实 ASIN 字段或提交流程。
- 用户明确要求用上桌面法规库，不能只做 CSV 目录演示。已有完整库与可部署查询资产，详见下文。
- 用户已授权从正式根目录提交 GitHub、更新魔搭并继续线上验收。不要仅给方案或停在“本地测试通过”。不擅自购买资源、升级付费服务、公开密钥或覆盖原数据。
- 用户还会补充改进意见；把新意见融入现有项目，不无故另起一套系统。跨会话项目续办、账号体系不属于本轮必做。

## 2. 唯一正式根目录与发布目标

```text
E:\workbuddy\2026-10-14-01-02-52\compliance-radar
```

使用 Windows PowerShell，Python 3.11、Gradio 6.2.0。正式运行入口 `app.py`，默认端口 7860。同级 `compliance-radar-ui-candidate` 是开发/浏览器测试环境，不能作为另一套正式上传源。

- GitHub：`https://github.com/cristiano138/Chinese-Enterprises-Going-Global-Radar`，`origin/main`。
- 魔搭：`https://www.modelscope.cn/studios/zhanxy2551/ComplianceRadar-v2`，`modelscope/master`。
- 魔搭匿名应用：`https://zhanxy2551-complianceradar-v2.ms.show/`。
- 注意名称包含 **-v2**，不要操作旧空间。
- 现有空间使用免费 CPU `platform/2v-cpu-8g-mem`。本地 `ms_deploy.json` 中资源模板与现有空间不完全相同；以实查资源为准，不因模板自动改成 16G。

## 3. 先阅读并核实的资料

按顺序阅读这些文件，执行 `git status --short`、`git log -5 --oneline`，再核对远程分支和线上版本。文档中的历史状态不是当前完成证明。

1. `docs/一日收尾与法规库接入-20261019.md`：本轮范围、结果、人工依赖及最新发布状态。
2. `docs/online-acceptance/20261019-chat14/`：本轮测试与数据库证据，分清本地和线上。
3. `docs/部署与上传.md`、`README.md`：运行与发布方式。
4. `docs/基线与功能保留.md`、`docs/线上验收-20261019.md`：包含上一版历史记录，先看版本再引用。
5. `data/snapshot.json`、`data/journey_sources.json`、`data/law_store_manifest.json`：审核边界、官方来源及资产哈希。

原用户提示词副本曾在下面目录找到：

```text
C:\Users\ThinkPad\Documents\xwechat_files\wxid_dri4yixft7ug22_c7c5\msg\file\2026-10\项目优化提示词(1).md
```

只读用户指定附件，不搜索聊天记录。若副本不存在，可继续依据上述项目记录实施，不要再次要求用户找回已说明暂无的提示词。

## 4. 已完成的工程基线

chat1.4 应用源码提交：`c9f99418ac2ba89597fc283c5ba618c7c5c802b8`。
对应魔搭应用部署提交：`3cf9d0c16644eccb198d0d2b28e269a7345c93eb`。
目标应用版本：`2026.10.19-chat1.4`。后续文档提交可能改变仓库 HEAD；必须区分“仓库最新提交”和“容器运行的应用提交”。线上完成状态查最新验收记录，并实测。

已实现：

- 主线最多三项当前行动；按年龄、是否带电、履约方式逐步补问，已知不重复问，暂不确定保留未知。
- 修正“适用年龄”误跳法规视图、中文紧邻 FBA/FBM 的识别问题。
- 完成任务后刷新行动提示；保留任务展开状态。不要重建会随优先事项数量变化的重复交互卡片，否则 Gradio 动态组件容易错配展开状态。
- 正文检索显示原文链接、定位、日期、抽取状态和截断提示。
- M4 校验真实记录的题目、观察日期、时间、模型与证据字段，拒绝不完整记录；没有真实回放时展示真实空态。不得生成假对照数据凑演示。
- 数据库资产启动校验和原子准备，已有数据库及显式配置不被覆盖。

关键文件：`core/conversation.py`、`core/journey.py`、`ui_chat.py`、`core/law_store.py`、`core/database_assets.py`、`core/model_assets.py`、`modules/m4_compare.py`、`scripts/build_runtime_law_store.py`。

## 5. 桌面法规库：已接入，必须继续保留

原始分片位于：

```text
C:\Users\ThinkPad\Desktop\新建文件夹\regulations.sqlite3(1).part001
……part002 至 part005
```

五片已经按 `docs/法规资料传输包/数据库分卷manifest.json` 校验并恢复，不要再次拼接覆盖。

- 完整维护库：根目录 `sqlite/regulations.sqlite3`，2,233,716,736 字节；Git 忽略。
- 治理前备份：`sqlite/regulations.sqlite3.bak-governance-20261019-173037`；保留。
- 已应用仓库既有乱码治理补丁：325 篇文档、1,179 个切片，完整性和外键检查通过。不要重复应用补丁或编造损坏原文。
- 当前完整库 SHA-256：`55a05b3a61ae9ad7d2b9af56f346a698ce2b9afcdf8ac439fc5c19f1b9b34f6c`；后续若修改应重新核对并记录。
- 线上查询资产：`runtime-assets/law-store.bundle`，24,912,515 字节。
- 资产 SHA-256：`ebc1878019e321825bbfa5ed7e16b2af5bc631b5d2e783ad5caa012d4f938ab0`；清单在 `data/law_store_manifest.json`。
- 查询库含 86 部法规、1,794 份文档元数据、1,933 个关联、14,371 个切片，解压后 124,350,464 字节。
- 全部 86 部法规按相同参数查询，与完整库结果一致。查询资产保留正文和来源，只导出 `laws/documents/law_documents/units` 四张表必要字段，不含抓取请求、响应及重复大字段。

完整库留本机；GitHub 不提交库体。魔搭单独上传公开查询资产。源码 ZIP 与法规资产 ZIP 分开交付，上传时按目录合并。

启动日志应出现 `[LAW] Public clause database verified and prepared`，页面应显示 SQLite 已接入。但这些还不够：必须用 `32009L0048` 和 `32023R0988` 实际检索正文并打开官方来源。

## 6. 测试与验收方法

本轮已有 **19 个离线入口、37 项本地浏览器检查通过**，证据在上述 chat14 目录。不要把这些数字写成线上通过；线上脚本跳过四项本地故障注入，正常应为 33 项。新改动只补跑相关测试，最终再做必要回归。

```powershell
Set-Location -LiteralPath 'E:\workbuddy\2026-10-14-01-02-52\compliance-radar'
.\.venv\Scripts\python.exe scripts\selftest_all.py
```

浏览器测试使用已安装 Playwright 的同级候选虚拟环境，但执行正式根目录脚本：

```powershell
..\compliance-radar-ui-candidate\.venv\Scripts\python.exe scripts\check_chat_browser.py --url https://zhanxy2551-complianceradar-v2.ms.show --modelscope-embed --output outputs\online-browser-followup
```

输出目录换成新的名称。`--modelscope-embed` 使用测试父页承载真实匿名应用；还应单独打开真实魔搭门户，不能把承载页截图当作门户验收。默认浏览器网络曾验证可用，不擅自修改系统代理。

验收必须覆盖：空白输入、七功能入口、六阶段、逐步追问、任务自述状态、官方来源、正文检索、CSV 下载、导出后继续查询、历史结果、重置、手机布局、真实公开语音样本。语音须转写后等待用户核对再发送；单个合成样本成功不等于口音和噪声准确率达标。

## 7. 提交与部署规则

1. 所有最终提交从正式根目录产生，先查差异，保留用户未提交工作；不要 `git reset --hard`、强制推送或覆盖 CSV、`.env`、数据库。
2. GitHub main 与魔搭 master 的历史不同，不能直接把 main 强推到魔搭。以最新 `modelscope/master` 为父提交同步源码，保留 `.gitattributes`、LFS 模型和空间专用 `requirements.txt`，提交说明记录 `Source-Commit`。
3. 本机有忽略的运维脚本 `outputs/publish_tree.py`：使用独立 Git 索引、保留模型依赖、验证数据库包后生成部署提交。执行前先阅读；它依赖本机发布回执和最新远程引用，不能脱离状态盲跑。部署分支旧名 `deploy/modelscope-chat11-20261019` 不代表运行版本旧。
4. 凭证使用现有 Git 凭证管理器，禁止输出 token、读取展示 `.env` 或把凭证拼进 remote URL；密钥不得进入提示词、截图、日志和压缩包。
5. Git 推送之后核对实际构建。之前普通 deploy 接口曾使用旧快照；本机 `outputs/rebuild_chat12.py` 名字虽旧，但调用的是目标空间 `reset_restart`，已用于正确重建。先检查是否已有构建，避免重复触发。
6. `outputs/watch_publish.py` / `publish_check.py` 检查 Running、版本 chat1.4、数据库接入和资源状态。不能只凭 Running 宣布成功，必须通过真实页面与业务调用。
7. 可复用本机 `outputs/verify_online.py`、`verify_public_page.py`、`check_public_voice.py`、`check_startup_receipt.py`。这些是本机运维脚本，不在源码包内；跨机器接手时根据文档重建必要操作。
8. 仅文档/验收证据后续提交不必重复重建已验证应用；明确记录运行源码提交和最新文档提交。

## 8. 下一步执行顺序与交付标准

先查最新版验收记录及线上状态：若 chat1.4 已验收，不重复发布；若尚未完成，继续构建检查、匿名页面/业务/正文/语音验证，失败则定位并修复。

随后处理用户最新反馈，优先解决阻塞这条演示路线的问题；不要把未要求的新平台、长流程账户系统或装饰性功能塞进一天工期。涉及法规适用性、政策更新时查公开官方资料，记录来源与日期，区分原文、推断与待确认项。

最终交付：已推送的源码和部署提交、可打开的魔搭链接、实际测试证据、完整的源码包和独立查询资产包、简明部署说明、逐项列出的真实剩余缺口。

当前审核基线是 86 条中 28 条已核对、58 条待核对，`release_eligible=false`。全文接入和程序测试不能把它改成已审核。卖家中心私有政策、真实提交字段暂缺；M4 没有真实记录允许空态。请如实区别“技术演示可用”和“具体产品可确定合规”，不得宣布所有法律审核或账户提交已完成。

用中文简洁汇报，先说完成了什么、证据是什么、还缺什么。遇到必须由用户提供的材料，说明具体缺哪份以及影响，同时继续不依赖它的工作。
