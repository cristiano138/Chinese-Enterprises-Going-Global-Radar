# 原型 vs 改造后：逐路由像素比对

采集：Playwright Chromium，`device_scale_factor=2`，`locale=zh-CN`，`color_scheme=light`，`reduced_motion=reduce`。
视口：移动端 390×844（截图 780×1688），桌面端 1440×900（截图 2880×1800）。
比对：REA `compare-web-screenshots`（非交错 8-bit RGB/RGBA PNG，不做 OCR / 语义布局 / 感知色彩校正）。

- 原型基准：`docs/ui-preview/prototype-baseline/shots`（32 张）
- 改造后：`docs/ui-preview/rebuilt/shots`（32 张）
- 两套截图与 `web-report.json` 都是可复现的中间产物，**不入库**；复现命令见文末。
- 32 对全部完成比对，没有缺失截图、没有 REA 报错。

平台默认阈值 `--threshold 0.02` 会计入 `over_threshold`：本次 16 对，全部是桌面端。移动端 16 对中 15 对完全一致。

## 结论

| 视口 | 对数 | 完全一致 | 有差异 | 判定 |
| --- | --- | --- | --- | --- |
| `@mobile` 390×844 | 16 | 15 | 1（assistant，0.61%） | 移动端基本逐像素一致；唯一差异为渲染抖动，见「待修」 |
| `@desktop` 1440×900 | 16 | 0 | 16（76.0%–82.1%） | 规格允许：桌面端按规格 §7 刻意去掉手机壳 |

## 桌面端（`@desktop`）：规格允许的预期差异

差异原因（对全部 16 条路由一致，属同一个产品决策）：

1. **去掉手机壳（规格 §7）**：原型在桌面端仍是居中的手机外框（约 640px 宽、圆角、投影），两侧是大面积留白；改造后为全宽响应式布局。差异像素的绝大部分来自壳体外的背景区域，壳体内部内容逐行一致。
2. **移除原型演示件**：原型右下角的「可点击原型 · 数据为示例」浮层（`.proto-note`）不再出现在正式界面。
3. 因桌面端整页宽度不同，内容横坐标整体平移，故差异占比必然很高——这是**预期差异，不作为缺陷**。

| 路由 | changed_ratio | 判定 |
| --- | --- | --- |
| home@desktop | 0.821093 | 规格允许（去壳 + 移除原型演示浮层） |
| result@desktop | 0.778197 | 规格允许（同上） |
| freshness@desktop | 0.812188 | 规格允许（同上） |
| assistant@desktop | 0.794435 | 规格允许（同上） |
| regulations@desktop | 0.798096 | 规格允许（同上） |
| regulations/search@desktop | 0.760270 | 规格允许（同上） |
| regulations/map@desktop | 0.780471 | 规格允许（同上） |
| regulations/timeline@desktop | 0.762290 | 规格允许（同上） |
| action@desktop | 0.777795 | 规格允许（同上） |
| action/todo@desktop | 0.781295 | 规格允许（同上） |
| action/readiness@desktop | 0.774332 | 规格允许（同上） |
| action/journey@desktop | 0.774414 | 规格允许（同上） |
| action/compare@desktop | 0.779472 | 规格允许（同上） |
| action/multi@desktop | 0.777434 | 规格允许（同上） |
| profile@desktop | 0.795991 | 规格允许（同上） |
| profile/tutorial@desktop | 0.776974 | 规格允许（同上） |

## 移动端（`@mobile`）：应为低差异

15 条路由 `status=identical`、`changed_ratio=0`，与原型逐像素一致：

`home`、`result`、`freshness`、`regulations`、`regulations/search`、`regulations/map`、
`regulations/timeline`、`action`、`action/todo`、`action/readiness`、`action/journey`、
`action/compare`、`action/multi`、`profile`、`profile/tutorial`。

唯一有差异的一条：

| 路由 | changed_ratio | 最大通道差 | 差异像素 | 判定 | 原因 |
| --- | --- | --- | --- | --- | --- |
| assistant@mobile | 0.006059 | 5 | 7,977 / 1,316,640 | **待修（低优先，疑似渲染抖动）** | 差异全部落在页首「雷达」同心圆环区域（CSS 坐标约 x 134–212、y 93–152），无像素通道差 > 10。同一构建连续重采 3 次，同区域最大通道差可达 37，而跨构建仅 5——说明是同构建内的抗锯齿/合成抖动，不是产品差异。仍按「无法归因于产品决策」列入待修，原因待查（优先排查圆环渐变/合成层的确定性渲染，必要时在该区域固定截图时序）。 |

> 说明：`assistant` 与 `home` 共用同一个 `section.home` 标记；`home@mobile` 本次为 0 差异，进一步佐证 `assistant@mobile` 的差异来自渲染抖动而非标记差异。

## 复现命令

截图目录与报告为可复现中间产物，不提交；需要时按以下命令重新生成（工作区根目录执行）：

```bash
# 1) 原型基准
python -m http.server 8899 --bind 127.0.0.1 --directory docs/ui-preview &
python scripts/check_web_browser.py \
  --url http://127.0.0.1:8899/prototype-v2.html \
  --out docs/ui-preview/prototype-baseline

# 2) 改造后（需先启动本工作区的 app.py，默认 7899）
python scripts/check_web_browser.py \
  --url http://127.0.0.1:7899 --out docs/ui-preview/rebuilt

# 3) REA 像素比对
python scripts/compare_web_screenshots.py \
  --prototype docs/ui-preview/prototype-baseline/shots \
  --rebuilt   docs/ui-preview/rebuilt/shots \
  --out       docs/ui-preview/web-pixel-diff.json

# 4) 清理中间产物
rm -rf docs/ui-preview/prototype-baseline docs/ui-preview/rebuilt
```

> 首次冷启动时 Chromium 可能在同一 400ms 等待内尚未完成首帧绘制，导致整页空白；等 HTTP 服务预热后重跑即可得到稳定结果（本次重跑为 32 路由、0 结构失败）。
