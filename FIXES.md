# 修复说明（FIXES）

> 本目录（`compliance-radar-v2/`）是依据 [`docs/代码审查报告.md`](docs/代码审查报告.md)
> 与 [`docs/代码审查报告-补充.md`](docs/代码审查报告-补充.md) 对原仓库做的**修完版**。
> 原仓库未改动，本目录为独立副本，可对照 diff。
>
> 生成时间：2026-10-14

---

## 一、修复结果一图看

| 指标 | 修复前 | 修复后 |
|---|---|---|
| 语料表行数 / 唯一键 | 88 行 / **仅 86 唯一**（2 条重复） | **86 行 / 86 唯一** |
| 美国原始抓取文件 | 69 行（含 2 条重复） | **67 行（已去重）** |
| 列数 | 18 列 | **20 列**（新增 `监管机构`、`现行效力`）|
| 体检报告口径 | 「88 条（欧盟 29 + 美国 69）」→ 29+69≠88 | **「86 条（欧盟 29 + 美国 57）」+ 原始条数单列** |
| 链接结论 | 报告里 5 条 429，主表却写「复测通过」→ **自相矛盾** | **报告与主表同源：57 首次 200 + 29 人机墙 + 0 有问题** |
| 欧盟官方编号 | `R2025/2509`（非官方写法） | **`Regulation (EU) 2025/2509`** |
| 失效法规 | 4 条混在清单里，仅备注一行小字 | **独立 `现行效力` 列，4 条显式标「已废止」** |
| 硬编码 | 本机绝对路径、固定日期、写死条数 | **全部参数化 / 动态生成** |

---

## 二、逐条修复对照

### 对应《代码审查报告》

| # | 问题 | 改在哪 | 怎么改 |
|---|---|---|---|
| 1 | 语料表有重复行（88→实际 86） | `scripts/merge_corpus.py`、`scripts/fetch_us.py` | ① `fetch_us` 合并重叠 TARGETS + 全局 `seen` 去重；② `merge_corpus` 按 `(机构, 编号)` 去重兜底。数据层面 88→86 |
| 2 | 体检报告数字自相矛盾 | `scripts/merge_corpus.py` | 总数统一取「筛选后」口径，原始条数另起一行说明 |
| 3 | README 让跑不存在的 `app.py` | `README.md` | 「运行」章节改为：明确标注 Web 入口未建立 + 给出真实可跑的管线命令 |
| 4 | `audit_guide.py` 硬编码外部路径/日期 | `scripts/audit_guide.py` | `GUIDE` 改为命令行参数 / 环境变量；eCFR 日期从 `titles.json` 动态取 |
| 5 | 文档字段规范与实现不符 | 全链 | 现为 **20 列**，README / 数据总览 / 脚本 COLS 三处已对齐 |
| 6 | `docs/06` 数据量过时（40 vs 88） | `docs/06-数据通路验证清单.md` | 顶部加「过程快照」声明，指明最终以 data/ 为准（86 条）|
| 7 | 合并丢失美国监管机构粒度 | `scripts/merge_corpus.py` | 新增 `监管机构` 列，保留 CPSC/FDA/FCC/FTC |
| 8 | 引入 RAG 依赖却声明不用 RAG | `requirements.txt` | 移除 `numpy` / `scikit-learn`，加注说明 |
| 9 | 生成物硬编码时间/条数 | `make_overview.py`、`audit_guide.py`、`make_todo_eu.py` | 全部改 `datetime.now()` / `len(rows)` 动态生成 |
| 10 | 欧盟官方编号格式非标准 | `scripts/fetch_eu.py` | 新增 `official_number()`：R→`Regulation (EU) y/n`，L→`Directive y/n` |
| 11 | `input()` 在非交互环境阻塞 | `test_connection.py`、`list_models.py` | 新增 `pause()`，仅 `sys.stdin.isatty()` 时才等待 |
| 12 | 文档提到不存在的 `list_models.bat` | `list_models.py` | 文档字符串改为「python list_models.py」 |
| 13 | 调用方式不统一、`tenacity` 未用 | `scripts/enrich_cn.py` | 改 openai SDK 调用，重试交给 `tenacity` |
| 14 | 默认模型名前后不一致 | `.env.example` | 统一为 `Qwen/Qwen2.5-72B-Instruct`，并注明推理模型注意事项 |
| 15 | 管线无总入口 | 新增 `run_pipeline.bat` | 一键按 `fetch→merge→check→enrich→overview` 重跑 |
| 16 | 晦涩三元表达式 | `scripts/merge_corpus.py` | 改为显式 `if/else` |
| 17 | 部分法规分类存疑 / 失效未标 | `scripts/fetch_eu.py`、`merge_corpus.py` | 新增 `现行效力` 列，4 条已废止显式标注（分类归属仍留人工复核）|
| 18 | README 未列 FTC | `README.md` | 来源与致谢、痛点表均补 FTC |

### 对应《代码审查报告-补充》

| # | 问题 | 改在哪 | 怎么改 |
|---|---|---|---|
| 新增 1 | 链接报告与主底表结论打架（P0）| `scripts/check_links.py` + 数据重跑 | `probe()` 支持 429/503 退避复测，新增「限流复测」档；**已真实重跑**，报告与主表同源 |
| 新增 2 | `check_links` 破坏性覆盖已人工结论（P0）| `scripts/check_links.py` | 改为**非破坏写入**：默认只补空值（`待查`等），已有结论保留；需覆盖时显式 `--force` |
| 新增 3 | `来源类型` 取值超出手册 | —（保留，见「暂缓项」）| 数据保留真实取值；建议后续统一数据字典 |
| 新增 4 | `链接可打开` 取值分裂 | `scripts/check_links.py` + 数据 | 收敛为标准两值：`是（程序实测 200）` / `需人工浏览器验证（WAF）` |
| 新增 5 | `docs/03` 类目枚举脱离实际 | —（暂缓，见下）| 属文档枚举，非代码；数据保留 7 类目 |
| 新增 6 | 4 条已失效欧盟法规未标注 | `scripts/fetch_eu.py` + `merge_corpus.py` | 新增 `现行效力` 列，4 条标「已废止」，体检报告单列提示 |
| 新增 7 | `app.py` 全仓多处虚假引用 | `README.md`（已改）；docs/02/03/05 **暂缓** | README 入口已澄清；其余属未建立文件，按要求暂缓 |
| 新增 8 | README 美国条数写错 | `README.md` | 改为「67 条（已去重）」，与文件一致 |
| 新增 9 | `语料核对表.xlsx` 是孤儿资产 | `README.md` | 项目结构中补入 `docs/语料核对表.xlsx` |
| 新增 10 | 标题被静默截断到 300 字符 | `scripts/fetch_eu.py` | 截断时在备注写「⚠️标题超 300 字符已截断，完整标题见官方链接」|

---

## 三、顺带修掉的一个真 bug（报告未提）

修 `check_links.py` 时发现：**HEAD 请求返回 202 挑战页时读不到正文**，导致 WAF 被误判成「待确认」。
已在 `probe()` 中修正（202 + HEAD → 换 GET 读正文），并增加**响应头 `x-amzn-waf-action`** 作为判定依据。
重跑后 29 条欧盟链接被正确识别为「人机验证墙」。

---

## 四、验证结果

在真实网络下重跑全链（`migrate_offline.py`），产出一致：

```
语料核对表_骨架总表.csv   86 行 × 20 列
语料核对表_完整版.csv     86 行 × 20 列   中文名填充 86/86
链接可打开：57 条「是（程序实测 200）」+ 29 条「需人工浏览器验证（WAF）」
骨架表 与 完整版 的「链接可打开」列：完全一致 ✅
链接检查报告.txt：可程序验证 57 / 限流复测 0 / 人机墙 29 / 待确认 0 / 有问题 0 ✅
```

数字全链自洽：README「86 条（29+57）」= 数据总览「合计 86」= 体检报告「86 条」= 实际行数 86。

---

## 五、暂缓项（说明原因，非遗漏）

| 项 | 原因 |
|---|---|
| `app.py` 相关引用（docs/02/03/05） | `app.py` 等文件尚未建立，按要求**暂时忽略** |
| `docs/03` 的数据字典枚举（类目 4 项、来源类型 5 值） | 属文档规范而非代码；正确修法是按 xlsx/csv 重写一版数据字典，建议单列任务 |
| 法规分类归属（REACH/CLP 归「纺织服装」、GPSD 归「标签标识」） | 需领域人工判断，不宜由脚本擅改；已通过 `现行效力` 列至少暴露了失效状态 |
| 未联网的 `fetch_eu` / `fetch_us` 真实重抓 | 本次用离线迁移对齐格式；如需最新数据，联网跑 `run_pipeline.bat` 即可 |

---

## 六、怎么用

```bash
# 一键重跑（联网 + 需 .env 里的模型 Token）
run_pipeline.bat

# 或分步
python scripts/fetch_eu.py
python scripts/fetch_us.py
python scripts/merge_corpus.py
python scripts/check_links.py          # 加 --force 才覆盖已有结论
python scripts/enrich_cn.py
python scripts/make_overview.py
python scripts/make_todo_eu.py
```
