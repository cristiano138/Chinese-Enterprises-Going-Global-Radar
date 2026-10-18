# 维护者脚本与报告

本目录用于**审计和复现**本次乱码治理，不是成员日常操作所需。
成员只需要上级目录的 `apply_db_governance.py` 和 `governance_patch.json.gz`。

---

## 1. 脚本清单

| 文件 | 作用 | 是否只读 |
|---|---|---|
| `repair_with_pdf.py` | 主修复脚本：从 `blobs` 解压原始 PDF，用 PyMuPDF 重新抽取，逐字校正 `documents.full_text`，同步 `units.body` 和 FTS | 否 |
| `fix_pm_residual.py` | 收尾：修复 CAS 号、ASTM 标准号、ZIP+4、法条号等高度确定的 `±` 伪影 | 否 |
| `fix_pm_final.py` | 收尾：恢复被误伤的 `22.86±0.64`，修复 3 处跨行伪影 | 否 |
| `make_governance_patch.py` | 比较治理前备份与治理后主库，生成成员用 `governance_patch.json.gz` | 是（只读两个库） |
| `repair_mojibake.py` | 第一轮纯规则 `Ð` 修复；已被 PDF 重抽取取代，保留用于追溯 | 否 |
| `diagnose_encoding.py` | 扫描所有文本列的 `�`／mojibake／控制字符等 | 是 |
| `schema_stats.py` | 输出各表取值分布、字段空值统计 | 是 |
| `pdf_align_probe2.py` | 验证“去空白上下文对齐”的命中率原型 | 是 |

### 依赖

- Python 3.8+
- `pymupdf`（仅 `repair_with_pdf.py` 和 `pdf_align_probe2.py` 需要）：

```bash
pip install pymupdf
```

- 其他脚本只用标准库。

---

## 2. 原始工作目录假设

`repair_with_pdf.py`、`fix_pm_residual.py`、`fix_pm_final.py`、`make_governance_patch.py`
顶部的常量假定当前工作目录下存在：

```text
sqlite/regulations.sqlite3                 治理后／待治理的主库
sqlite/regulations.sqlite3.bak-20261018    治理前备份
```

`diagnose_encoding.py` 接受数据库路径参数；`schema_stats.py` 同样假定
`sqlite/regulations.sqlite3`。

这些数据库**不在本仓库**。复现时请在原工作目录运行，或修改脚本顶部的
`OLD_DB` / `NEW_DB` / `DB` 常量。

---

## 3. 复现顺序

> 以下操作会修改数据库。务必先保留治理前备份，并在副本上练习。

```bash
# 0. 准备：原库放到 sqlite/regulations.sqlite3，
#    治理前备份放到 sqlite/regulations.sqlite3.bak-20261018

# 1. 主修复：以原始 PDF 重新抽取为准，逐字校正
python repair_with_pdf.py

# 2. 收尾：CAS 号、ASTM 标准号、ZIP+4、法条号等
python fix_pm_residual.py

# 3. 收尾：恢复误伤、修复跨行伪影
python fix_pm_final.py

# 4. 生成成员补丁
python make_governance_patch.py

# 5. 诊断与统计（只读）
python diagnose_encoding.py sqlite/regulations.sqlite3 encoding_report.txt
python schema_stats.py

# 6. 完整性校验
python -c "import sqlite3; c=sqlite3.connect('sqlite/regulations.sqlite3'); print(c.execute('PRAGMA integrity_check').fetchone()); print(c.execute('PRAGMA foreign_key_check').fetchall())"
```

注意：

- `repair_mojibake.py` 是第一轮的中间方案，最终文本以 `repair_with_pdf.py` 的结果为准；
  单独重跑它不会得到当前主库的最终状态。
- `fix_pm_residual.py` 的 `section` 正则曾误伤 `22.86±0.64`；`fix_pm_final.py` 已恢复。
  如果重新调整规则，务必检查 eCFR 16 CFR 1630/1631 的容差文本。
- `make_governance_patch.py` 生成的是**逐字符等长替换**补丁。若修改后出现长度变化，
  脚本会退化为整篇替换并报告；此时应检查是否吃掉了换行。

---

## 4. 报告清单

| 文件 | 内容 |
|---|---|
| `pdf_repair_report.txt` | 325 篇文档的逐篇修复统计、替换字符分布、未决样本 |
| `verify_after.txt` | 第一轮 `Ð` 规则修复后的校验 |
| `verify_after_pdf.txt` | PDF 重抽取后的校验 |
| `verify_final.txt` | 最终校验（残留 `Ð`、FTS、`quick_check`、`foreign_key_check`） |
| `integrity_final.txt` | 最终 `PRAGMA integrity_check` |
| `encoding_report.txt` | 初始编码异常扫描结果 |
| `schema_stats.txt` | 各表字段取值分布 |
| `remaining_pm2.txt` | 最终保留的 `±` 上下文（用于人工复核） |

这些报告是 2026-10-18 治理过程的快照；重新运行脚本后应重新生成，不要手动编辑。

---

## 5. 校验值

```text
governance_patch.json.gz
  sha256 cd5374f37cf5f49b30389bccfc5a76cbfe72048538b9f57bab3731a4cabfab8a
```

治理后主库（团队基准）：

```text
size   2,233,716,736 bytes
sha256 8324386b657d3a897e96c8b0efac397224bb193dc3646122b4db0653d50948c6
```

治理前备份：

```text
size   2,233,716,736 bytes
sha256 bfb145a5c8ccf6a65809ddc237bdf0e463efc4e03e1b6e52dee64c0f9150012b
```
