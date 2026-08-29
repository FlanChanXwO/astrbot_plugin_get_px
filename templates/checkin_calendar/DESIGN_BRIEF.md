# 签到日历模板 · v1 定稿契约与合并说明

> **定稿（2026-08-29）**：产线模板为 **v1 玻璃壁纸版**，设计源文件在 `templates/checkin_calendar/_dev/index_v1.html` + `_dev/style_v1.css`。
> 生产落地为 `templates/checkin_calendar/index.html` + `style.css`（命名不带 v1 后缀）。
> 旧版（左右分栏信息面板 + 背景模糊）已整体归档至 `_dev/deprecated/`，仅历史参考，不再进入管线。

本文档是 v1 模板的**唯一视觉与数据契约**。执行者（或未来接手的模型）合并模板时按「合并转换清单」机械转换，按「数据契约」实现 `build_checkin_calendar_data()`，不重做视觉设计。

## 视觉结构（v1，1600×900 横版）

- **L1 背景层**「`.background-layer`」：`background_url` 有图时铺 16:9 邻域横图，`object-fit: cover` + `object-position: right center`（优先保留右侧人物主体），**高清原图、无模糊**；其上叠「`.bg-gradient-scrim`」中性白横向渐变纱（左 0.78 → 36% 0.55 → 55% 0.18 → 右 0），负责左侧文字可读性托底。无图时走「`.bg-fallback`」135° 暖白渐变，整卡布局不变。
- **L2 内容区**：左右布局——左侧 600px「`.glass-calendar-card`」毛玻璃日历卡，右侧大面积留白直接展示原图。
- **毛玻璃卡片**：`backdrop-filter: blur(10px) saturate(1.1)`（卡片）/ `blur(16px)`（右下署名徽章），**保留 `-webkit-` 前缀**。卡片自带 `rgba(255,255,255,0.66)`、署名徽章 `rgba(255,255,255,0.72)` 半透明白底兜底：T2I Chromium 若不支持 blur，退化为半透明卡片，可读性不受影响。
  > 状态：backdrop-filter **暂保留，待用户在产线 T2I 实测兼容性**。若实测失效，按替换方案 R1（卡片与徽章改为纯半透明白底 + 边框阴影，其余不动）执行，不重做视觉。
- **卡片内部**：头部（`.month-title` 月份标题 + `.as-of-text` 截至日期）→ 两行统计 `.stat-row`（已签到 N 天 / 获得金币 +N，金币带内联 SVG 金币图标）→ 日历主体（星期行 + 6×7 `.week-row` 去表格化网格）→ 底部 `.card-footer`（`.events-bar` 节气/节日胶囊条 + 可选的 `.empty-tip` 空月提示）。
- **日格四态**「`.day-cell`」：`.checked` 白色轻胶囊 + 金币角标 `.coins-badge` + 赤金圆章勾 `.check-mark`（微旋转手印感）；`.missed` 淡褐底 + 灰数字（不堆文字）；`.future` 浅色数字无底；`.outside` 空白占位（不渲染 day/state 内容）。今日额外叠加 `.today`：赤金 2.5px outline。
- **署名**：右下角 `.artwork-credit-badge` 独立徽章（图章图标 + `{{ background_credit }}` 文字），`background_credit` 为空时不渲染该徽章。

## 合并转换清单（产线必须，机械步骤）

源 `_dev/index_v1.html` / `_dev/style_v1.css` → 目标 `index.html` / `style.css`：

1. **CSS 注入**：`<link rel="stylesheet" href="style_v1.css" />`（`index_v1.html:5`）→ `<style>/*__CHECKIN_CALENDAR_CSS__*/</style>`。后端 `get_checkin_calendar_template()` 会把 `style.css` 内容（已内联字体）塞进该 marker；样式必须全部走 CSS 文件，不散写内联 `style=""`。
2. **字体内联**：`@font-face` 的 `src: url("../checkin_themes/default/fonts/LXGWWenKaiLite-GB2312.woff2")` → `url("data:font/woff2;base64,__CHECKIN_CALENDAR_FONT_DATA__")`。字体仍是 `templates/checkin_themes/default/fonts/LXGWWenKaiLite-GB2312.woff2` 那一份，不复制。
3. 依赖相对路径与 `<link>` 的写法仅限 `_dev/` 本地预览；生产 HTML 必须是自包含单一字符串。

## 数据契约（Jinja2 变量）

`build_checkin_calendar_data()` 产出的顶层 dict（模板只消费以下字段）：

| 变量 | 类型 | 含义 | 示例 |
| --- | --- | --- | --- |
| `month_label` | str | 标题月份 | `2026 年 08 月` |
| `checked_days` | int | 已签到天数 | `2` |
| `coins_earned` | int | 当月获得金币合计 | `140` |
| `as_of_date` | str | 截至日期 | `2026-08-15` |
| `empty` | bool | 当月无任何签到记录 | `true` / `false` |
| `background_url` | str | 背景图 data URL；取图失败为 `""` | `data:image/jpeg;base64,...` |
| `background_credit` | str | 背景作品署名；无背景为 `""` | `背景：夜樱 / 画师名 (ID: 12345)` |
| `today_key` | str | 今日 ISO 日期，用于 `.today` 金描边判断 | `2026-08-15` |
| `events` | list[dict] | 本月事件（节气/节日）展示列表，规则见下节 | `[{"day": 7, "name": "立秋"}]` |
| `events_hidden_count` | int | 超出展示上限被折叠的事件条数 | `2` |
| `weeks` | list[list[dict]] | 固定 6 行 × 7 列，周一起始 | 见下 |

每个单元格 `cell`（`weeks` 的元素）：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `day` | int 或 `""` | 当月几号；月外为 `""` |
| `date_key` | str 或 `""` | ISO 日期；月外为 `""`（与 `today_key` 比较用） |
| `state` | str | `checked` / `missed` / `future` / `outside` |
| `state_label` | str | `已签到` / `未签到` / `未到` / `""`（v1 模板未直接渲染此字段，但契约保留，与测试断言一致） |
| `coins_label` | str | `+60`（checked）/ `—` / `—` / `""` |

状态对应：`checked` 显示 ✓ 圆章 + `+N`；`missed` 弱化数字；`future` 更淡；`outside` 完全空白。字符串字段后端已转义，模板直接 `{{ ... }}` 输出。

## events 数据契约（v1 新增，计划外字段）

数据源为仓内现成四类，**无需新增算法或依赖**：

1. **节气**：`lunar_python` 的 `Solar.fromYmd(y, m, d).getLunar().getJieQi()`（如立秋、处暑）；
2. **农历节日**：同对象 `.getFestivals()`（如七夕节，`checkin/content.py` 已在用此库解析农历节日）；
3. **法定节假日**：`checkin/holiday.py` 的 `HolidayCalendar.lookup(date_key)`，`is_off_day=False`（调休上班）不入列表；
4. **自定义事件**：`checkin.store.list_global_events()`，`annual`（MM-DD，每月日历都出现）与 `once`（YYYY-MM-DD，仅当月）均按目标月过滤。

归一化规则（升格自 `_dev/render_preview_v1.py:apply_event_rules`，产线原样实现）：

1. 调休日（`is_off_day=False`）不入列表；
2. 同名事件折叠为一条（`start` 取最早、`end` 取最晚，显示首日）；
3. 当前月只显示未开始的（`start >= today_key`，按首日判断），历史月全保留；
4. 按日期升序截断 `EVENT_LIMIT = 6` 条，超出的折叠进 `events_hidden_count`。

实现位置约定：`checkin/calendar.py` 提供收集函数（消费 2/3/4 号数据源并按月扫描产出原始事件列表）与规则归一化函数；`build_checkin_calendar_data(..., events=())` 内部对原始事件应用规则，输出 `events`（`[{"day": int, "name": str}]`）与 `events_hidden_count`。

## 渲染与管线（不变部分）

- 画布固定 1600×900；`html_render` 输出 JPEG，`quality=CHECKIN_JPEG_QUALITY`，`clip/viewport` 1600×900，`animations="disabled"`。
- 无 JS：任何关键信息不得只在 hover/动画态可见。
- 背景管线：`_fetch_source_candidates(aspect_ratio="gt1.7lt1.8")` 端上筛 16:9 邻域横图 + 本地 16:9±0.1 复核，只读去重不 claim；下载后转 data URL 内联；失败降级无图兜底。
- 缓存：复用 `CheckinCardCache`，`CALENDAR_TEMPLATE_VERSION` 键区分；模板或样式每次改动递增 `checkin/calendar.py` 的 `CALENDAR_TEMPLATE_VERSION`（目前 `"calendar:1"`），使旧缓存图失效强制重渲。
- `events` 归一化规则、模板视觉、字段契约任一变化，必须同步本文件与 `docs/superpowers/specs/2026-08-29-checkin-calendar-design.md`。

## 验收点（合并后必查）

1. 生产 HTML 含 `/*__CHECKIN_CALENDAR_CSS__*/` marker，不含 `<link>`/相对路径；CSS 含 `__CHECKIN_CALENDAR_FONT_DATA__` 占位；渲染结果无外链、无系统字体栈（`system-ui`/微软雅黑/Noto 等一律禁止）。
2. 用真实数据跑 `_dev/render_preview_v1.py` 或正式管线出 1600×900 预览，核对：四态可辨、今日金描边、events 胶囊与「等 N 项」折叠（可用 `october` 模式压力数据）、署名徽章、无图兜底版式一致。
3. backdrop-filter 在产线 T2I 的兼容性待用户实测；实测前保持现状，实测失败按 R1 执行。
4. `python -m compileall -q main.py checkin tests` 与 `pytest -q` 全绿后方可合入执行计划。