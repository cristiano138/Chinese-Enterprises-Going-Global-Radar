# 数据库文本乱码治理工具集

2026-10-18 版。用于修复 `regulations.sqlite3` 中由 PDF 字体映射导致的 `Ð` / `±` 乱码。

- 治理对象：`documents.full_text`、`units.body`、`documents_fts`
- 不改：`blobs` 中的原始 PDF／XML／JSON 字节、表结构、法规标题／编号／日期等其他字段
- 不包含：数据库本体（约 2.1 GB）和治理前备份（约 2.1 GB），二者另行分发
- 详细字段说明与治理记录：同目录 `数据库字段说明与治理记录.md`

---

## 给成员：三步应用

> 完整步骤、常见问题、回滚方法见同目录 `数据库乱码治理_成员操作手册.md`。
> 可直接转发的通知文案见 `成员通知_可直接转发.txt`。

1. 关闭所有数据库工具（DB Browser、DBeaver、Navicat、VS Code SQLite 插件等），暂停网盘同步。
2. 确认数据库所在磁盘至少有 3 GB 可用空间。
3. 在本目录运行：

```bash
python apply_db_governance.py --db "你的数据库路径/regulations.sqlite3"
```

看到最后一行 **`结果：成功`** 即完成。脚本会自动生成
`regulations.sqlite3.bak-governance-<时间戳>` 备份。

先试运行（不写数据）：

```bash
python apply_db_governance.py --db "你的数据库路径/regulations.sqlite3" --dry-run
```

只做校验：

```bash
python apply_db_governance.py --db "你的数据库路径/regulations.sqlite3" --verify-only
```

### 预期结果

```text
applied: 325
mismatch: 0
error: 0
units_updated: 1179
fts_updated: 325
quick_check: ok
fts_body_mismatch: 0
eth_docs: [('EU-DOC:31994L0011', 2)]
patch_docs_ok: 325
patch_docs_bad: 0
结果：成功
```

`EU-DOC:31994L0011` 的希腊文在 EUR-Lex 提供的原始 HTML 中就已损坏，无法从库内资料恢复；
补丁有意保留，因此仍会显示 2 个 `Ð`。这是预期结果。

---

## 文件清单

| 文件 | 说明 |
|---|---|
| `apply_db_governance.py` | 成员用单库应用脚本；仅 Python 标准库，无需第三方包 |
| `governance_patch.json.gz` | 325 篇文档、15,249 处单字符修正的补丁 |
| `治理补丁包_成员版_20261018.zip` | 可直接分发的压缩包（脚本＋补丁＋手册） |
| `治理补丁包_SHA256.txt` | 分发包的大小与 SHA256 |
| `数据库乱码治理_成员操作手册.md` | 逐步操作、预期输出、常见问题、回滚 |
| `成员通知_可直接转发.txt` | 群通知文案 |
| `数据库字段说明与治理记录.md` | 全部表／字段含义、用途及本次治理记录 |
| `maintainer/` | 维护者用的补丁生成、PDF 重抽取、诊断脚本及校验报告 |

### 校验值

```text
governance_patch.json.gz
  size   78,624 bytes
  sha256 cd5374f37cf5f49b30389bccfc5a76cbfe72048538b9f57bab3731a4cabfab8a

治理补丁包_成员版_20261018.zip
  size   88,712 bytes
  sha256 b22255352c36a09ac5581e48f2ef6ba3eea771f96e3e419d694edcedb9ce6e1b
```

---

## 安全设计

1. **逐篇哈希校验**：每篇文档先比较 `documents.full_text` 的 SHA256。
   - 与治理前一致 → 应用该篇；
   - 与治理后一致 → 跳过（已经修过）；
   - 两者都不一致 → 跳过并报告，绝不强行修改。
2. **自动备份**：写入前用 SQLite backup API 生成完整备份。
3. **只改三处**：`documents.full_text`、`units.body`、`documents_fts`。
4. **幂等**：重复运行显示 `applied: 0, already: 325`，不会重复修改。
5. **可回滚**：删除当前库及 `-wal`／`-shm`，把备份改名回 `regulations.sqlite3`。
6. **无第三方依赖**：应用脚本只用 `sqlite3`、`gzip`、`json`、`hashlib` 等标准库。

---

## 治理范围与结果

| 项目 | 结果 |
|---|---:|
| 受影响文档 | 325 篇 |
| `Ð` 字符 | 1,498 个（处理后受影响文档中为 0） |
| `±` 字符 | 13,888 个（连接号／连字符／合法容差分别处理） |
| 同步修改的 `units` 行 | 1,179 行 |
| FTS 重建 | 325 行；全库 1,635 行校验无不一致 |
| 最终残留 `Ð` | 仅 `EU-DOC:31994L0011` 的 2 个字符（源文件损坏） |
| 完整性校验 | `integrity_check = ok`、`quick_check = ok`、`foreign_key_check` 为空 |

修复方法：从 `blobs` 解压原始 PDF，用 PyMuPDF 重新抽取文本，与旧正文去空白对齐，
逐字确定应替换的字符；无法唯一定位时按上下文规则保守处理。详见
`数据库字段说明与治理记录.md` 第 3 节。

---

## 维护者入口

`maintainer/` 下保留了补丁生成、PDF 重抽取、诊断和校验报告。这些脚本**不是**成员日常
操作所需，且部分脚本假定原始工作目录中存在：

```text
sqlite/regulations.sqlite3                 治理后／待治理的主库
sqlite/regulations.sqlite3.bak-20261018    治理前备份
```

说明见 `maintainer/README.md`。

---

## 不纳入本仓库的内容

- `regulations.sqlite3`（约 2.1 GB）——通过既有分包／网盘分发；
- `regulations.sqlite3.bak-20261018`（约 2.1 GB）——治理前备份，另行保存；
- `regulations.sqlite3.part001`—`part005` 与 `manifest.json`——既有传输包，属于治理前版本；
- 任何 `-wal`／`-shm` 临时文件。

若重新分发治理后的数据库，应基于当前库重新生成分包和 `manifest.json`，
不能把旧分片与当前库混用。
