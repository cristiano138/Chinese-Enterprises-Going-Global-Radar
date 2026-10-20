# 原型 vs 改造后：逐路由像素比对

采集：Playwright Chromium，`device_scale_factor=2`，`locale=zh-CN`，`color_scheme=light`，`reduced_motion=reduce`；截图前注入
`*, *::before, *::after { animation: none !important; transition: none !important; }` 冻结伪元素动画。
视口：移动端 390×844（截图 780×1688），桌面端 1440×900（截图 2880×1800）。
比对：REA `compare-web-screenshots`（非交错 8-bit RGB/RGBA PNG，不做 OCR / 语义布局 / 感知色彩校正）。

- 原型基准：`docs/ui-preview/prototype-baseline/shots`（32 张）
- 改造后：`docs/ui-preview/rebuilt/shots`（32 张）
- 两套截图与 `web-report.json` 都是可复现的中间产物，**不入库**；复现命令见文末。
- 32 对全部完成比对，没有缺失截图、没有 REA 报错。
- 平台默认阈值 `--threshold 0.02` 会计入 `over_threshold`：本次 16 对，全部是桌面端。

## 结论

| 视口 | 对数 | 完全一致 | 有差异 | 判定 |
| --- | --- | --- | --- | --- |
| `@mobile` 390×844 | 16 | 15 | 1（profile，1.12%） | 唯一差异是产品决定（「我的」页顶栏不再画雷达标记） |
| `@desktop` 1440×900 | 16 | 0 | 16（76.0%–82.1%） | 规格 §7 允许的桌面去壳；profile 另含同一项产品决定 |

## 桌面端（`@desktop`）：规格允许的预期差异

事实核对（原型与改造后一致的部分）：两版都是 `width: min(480px, 100%)`、`margin: 0 auto` 的 **480px 居中窄栏**，`@media (min-width: 700px)` 下窄栏位置相同，**横向没有整体平移**。

差异来自以下几项（对全部 16 条路由一致）：

1. **body 背景换色**：原型桌面端 body 为 `--desk`（`#e7ece8`，灰绿底纹）；改造后按规格 §7 改为 `--paper`（`#fafaf7`）。窄栏外的大面积区域因此整片不同。
2. **垂直位移约 24px**：原型桌面端 body 有 `padding: 24px` 且壳体高度为 `min(900px, 100dvh - 48px)`（900 高视口下为 852px，顶边在 24px）；改造后 body `padding: 0`、壳体 `height: 100dvh`（900px，顶边为 0）。内容整体上移约 24px，壳体底部多出约 24px。
3. **去掉边框/圆角/阴影**：改造后桌面端 `.app-shell` 为 `border: 0; border-radius: 0; box-shadow: none`（原型为 1px 边框、30px 圆角、大投影）。
4. **移除 `.proto-note`**：原型右下角「可点击原型 · 数据为示例」浮层不再渲染。

以上均为规格 §7「桌面端刻意去壳」的预期差异，不作为缺陷。`profile@desktop` 另含下述顶栏雷达标记的产品调整。

| 路由 | changed_ratio | 判定 |
| --- | --- | --- |
| home@desktop | 0.821093 | 规格允许（桌面去壳：背景/垂直位移/边框阴影/`.proto-note`） |
| result@desktop | 0.778197 | 规格允许（同上） |
| freshness@desktop | 0.812188 | 规格允许（同上） |
| assistant@desktop | 0.794400 | 规格允许（同上） |
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
| profile@desktop | 0.795470 | 规格允许（桌面去壳 + 顶栏雷达标记移除） |
| profile/tutorial@desktop | 0.776974 | 规格允许（桌面去壳） |

## 移动端（`@mobile`）：15 对逐像素一致

`status=identical`、`changed_ratio=0`：

`home`、`result`、`freshness`、`assistant`、`regulations`、`regulations/search`、`regulations/map`、
`regulations/timeline`、`action`、`action/todo`、`action/readiness`、`action/journey`、
`action/compare`、`action/multi`、`profile/tutorial`。

冻结伪元素动画后，此前 `assistant@mobile` 因 `.radar-hero::before` 的 `sweep` 动画相位造成的差异已消失，现为完全一致。

唯一有差异的一条：

| 路由 | changed_ratio | 最大通道差 | 差异像素 | 判定 | 原因 |
| --- | --- | --- | --- | --- | --- |
| profile@mobile | 0.011200 | 238 | 14,746 / 1,316,640 | **预期差异（产品决定，非缺陷）** | 提交 `10416ee`「fix(web): show a single radar mark on the profile page」让「我的」页只在 hero 保留一个雷达标记、顶栏不再画标记。差异全部位于顶栏左上角（CSS 坐标约 x 4–155、y 7–63）原标记位置；`profile@desktop` 同理。 |

## 复现命令

截图目录与报告为可复现中间产物，不提交；需要时按以下命令重新生成（工作区根目录执行）：

```bash
# 1) 原型基准
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" -m http.server 8899 --bind 127.0.0.1 --directory docs/ui-preview &
sleep 2
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/check_web_browser.py \
  --url http://127.0.0.1:8899/prototype-v2.html \
  --out docs/ui-preview/prototype-baseline

# 2) 改造后（需先启动本工作区的 app.py，默认 7899）
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/check_web_browser.py \
  --url http://127.0.0.1:7899 --out docs/ui-preview/rebuilt

# 3) REA 像素比对
PYTHONIOENCODING=utf-8 "C:/Users/ymc/Desktop/agent/_recon/probe-venv/Scripts/python.exe" scripts/compare_web_screenshots.py \
  --prototype docs/ui-preview/prototype-baseline/shots \
  --rebuilt   docs/ui-preview/rebuilt/shots \
  --out       docs/ui-preview/web-pixel-diff.json

# 4) 清理中间产物
rm -rf docs/ui-preview/prototype-baseline docs/ui-preview/rebuilt
```

> 离线总闸 `scripts/selftest_all.py` 若与上述 dev server 并行运行，需设 `SELFTEST_WEB_PORT=7900`，避免与 7899 冲突。
>
> 首次冷启动时 Chromium 可能在同一 400ms 等待内尚未完成首帧绘制，导致整页空白；等 HTTP 服务预热后重跑即可得到稳定结果。
