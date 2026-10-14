"""把选手数据画成图：六边形面板图（雷达图）与柱状图。

为什么自己拼 SVG 而不用 matplotlib
-----------------------------------
1. **不引入重依赖** —— matplotlib 有几十 MB，而这个项目要能在 Termux 上装
2. **矢量、可控** —— 拼出来的 SVG 是纯文本，能直接内联、能无损缩放、能随手改
3. **输出即最终产物** —— 图是给人和 AI 看的，不需要交互，SVG 足够

三种输出格式，按优先级
----------------------
* **SVG**（默认）—— 纯文本生成，零依赖，矢量不失真
* **PNG** —— 由 SVG 转出来，方便贴进聊天窗口与文档
* **HTML** —— 把 SVG 包一层，方便双击直接看

PNG 需要一个转换器，按 `cairosvg` → `rsvg-convert` → ImageMagick `convert`
的顺序尝试，都没有就只给 SVG（不算失败）。

两种图
------
* **六边形面板图**：K/D、Rating、KAST、Swing、ADR、爆头率，六个轴
* **柱状图**：同样六个指标，按指标分组横比选手

关于「归一化」
--------------
六个指标量纲完全不同（Rating 是 0.5–2 的比值，ADR 是几十到一百多，
Swing 是有正负的百分比），画在同一个坐标系里必须先映射到 0–1。
映射用的参考区间写在 `METRICS` 里，**图上的形状只用于横向比较强弱，
真实数值一律照原样标出来** —— 柱子顶端标的是原始值，不是归一化值。
"""

from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    """一个可画进图里的指标。

    `lo` / `hi` 是**归一化参考区间**，不是数据边界：低于 lo 记 0，高于 hi 记 1。
    取值参考职业赛事里「很糟」到「很好」的常见区间。
    """

    key: str
    label: str
    lo: float
    hi: float
    suffix: str = ""

    def norm(self, value: float) -> float:
        span = self.hi - self.lo
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (value - self.lo) / span))

    def fmt(self, value: float | None) -> str:
        if value is None:
            return "—"
        if self.key == "swing":
            return f"{value:+.1f}%"
        if self.key in ("kd", "rating"):
            return f"{value:.2f}"
        if self.key == "adr":
            return f"{value:.1f}"
        return f"{value:.0f}{self.suffix}"


# 顺序即雷达图上的顺时针顺序，从正上方开始
METRICS: tuple[Metric, ...] = (
    Metric("kd", "K/D", 0.5, 2.0),
    Metric("rating", "Rating 3.0", 0.5, 2.0),
    Metric("kast", "KAST", 40, 90, "%"),
    Metric("swing", "Swing", -10, 10),
    Metric("adr", "ADR", 30, 120),
    Metric("hs", "爆头率", 20, 80, "%"),
)

METRIC_BY_KEY = {m.key: m for m in METRICS}

# 一组区分度足够的颜色（深色描边 + 浅色填充）
PALETTE: tuple[tuple[str, str], ...] = (
    ("#2563eb", "#93b4f8"),
    ("#ea580c", "#fbab6b"),
    ("#059669", "#6ddba8"),
    ("#7c3aed", "#bda2f5"),
    ("#dc2626", "#f79a9a"),
    ("#0891b2", "#67cfe4"),
)

INK = "#0f172a"        # 主文字
INK_SOFT = "#64748b"   # 次要文字
GRID = "#e2e8f0"       # 网格
PAPER = "#ffffff"      # 背景

# 字体栈把中文字体排在前面。原因很具体：cairosvg（负责 SVG→PNG）**不做逐字符
# 回退**，font-family 里没有一个装了中文字体的族名时，中文会整片变成方块 ——
# 而 `system-ui` 在它的解析结果里指向 Noto Sans（不含汉字）。浏览器则按顺序挑
# 第一个存在的，所以在各平台上也都是合适的。
FONT = (
    "'Noto Sans CJK SC','Source Han Sans SC','PingFang SC','Microsoft YaHei',"
    "'Hiragino Sans GB',system-ui,-apple-system,'Segoe UI',sans-serif"
)


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------


@dataclass
class Series:
    """一个选手（或一支队伍）的一组指标原始值。"""

    name: str
    team: str = ""
    values: dict[str, float] = field(default_factory=dict)

    def get(self, key: str) -> float | None:
        value = self.values.get(key)
        return None if value is None else float(value)


def _number(text: object) -> float | None:
    """从 "69.0%"、"+7.46%"、"26 (9)" 这类文本里取第一个数。"""
    if isinstance(text, (int, float)):
        return float(text)
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(text or ""))
    return float(match.group()) if match else None


def _kills_and_hs(text: object) -> tuple[float | None, float | None]:
    """解析统计表里的 `eK (hs)` 字段，形如 "26 (9)"。"""
    numbers = re.findall(r"\d+(?:\.\d+)?", str(text or ""))
    kills = float(numbers[0]) if numbers else None
    hs = float(numbers[1]) if len(numbers) > 1 else None
    return kills, hs


def series_from_match_stats(team: str, players: list[dict]) -> list[Series]:
    """把 `hltv_get_match_stats` 里的选手行转成可绘制的序列。

    六个指标里五个直接来自表格，**爆头率需要自己算**：表里给的是
    `eK (hs)`（击杀数（爆头数）），所以 HS% = hs / kills。
    """
    out: list[Series] = []
    for row in players or []:
        kills, hs = _kills_and_hs(row.get("kills"))
        deaths = _number(row.get("deaths"))
        values: dict[str, float] = {}
        if kills is not None and deaths:
            values["kd"] = kills / deaths
        for key, source in (
            ("rating", "rating"),
            ("kast", "kast"),
            ("swing", "round_swing"),
            ("adr", "adr"),
        ):
            parsed = _number(row.get(source))
            if parsed is not None:
                values[key] = parsed
        if kills and hs is not None:
            values["hs"] = hs / kills * 100.0
        out.append(Series(name=str(row.get("nickname") or "?"), team=team, values=values))
    return out


# ---------------------------------------------------------------------------
# SVG 基础
# ---------------------------------------------------------------------------


def _esc(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _svg_open(width: float, height: float) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" height="{height:.0f}" '
        f'viewBox="0 0 {width:.0f} {height:.0f}" font-family="{FONT}">',
        f'<rect width="{width:.0f}" height="{height:.0f}" fill="{PAPER}"/>',
    ]


def _legend(series: list[Series], *, x: float, y: float, gap: float = 30) -> list[str]:
    """右侧图例：色块 + 昵称（队伍名用小字跟在后面）。"""
    parts: list[str] = []
    for index, item in enumerate(series):
        stroke, light = PALETTE[index % len(PALETTE)]
        cy = y + index * gap
        parts.append(f'<rect x="{x:.0f}" y="{cy - 11:.0f}" width="22" height="12" rx="3" fill="{light}" stroke="{stroke}" stroke-width="1.6"/>')
        team = f'<tspan font-size="12" font-weight="400" fill="{INK_SOFT}"> {_esc(item.team)}</tspan>' if item.team else ""
        parts.append(f'<text x="{x + 30:.0f}" y="{cy:.0f}" font-size="14" font-weight="600" fill="{INK}">{_esc(item.name)}{team}</text>')
    return parts


# ---------------------------------------------------------------------------
# 六边形面板图
# ---------------------------------------------------------------------------

RADAR_W = 780
RADAR_H = 640


def radar_svg(series: list[Series], *, title: str, subtitle: str = "") -> tuple[str, int, int]:
    """六边形面板图。返回 (SVG, 宽, 高)。"""
    if not series:
        raise ValueError("至少需要一个选手才能画雷达图")

    cx = 286.0
    cy = 336.0
    radius = 186.0

    parts = _svg_open(RADAR_W, RADAR_H)

    # 标题
    parts.append(f'<text x="32" y="46" font-size="22" font-weight="700" fill="{INK}">{_esc(title)}</text>')
    if subtitle:
        parts.append(f'<text x="32" y="70" font-size="13" fill="{INK_SOFT}">{_esc(subtitle)}</text>')

    def point(index: int, ratio: float) -> tuple[float, float]:
        angle = math.tau * index / len(METRICS) - math.pi / 2
        return cx + radius * ratio * math.cos(angle), cy + radius * ratio * math.sin(angle)

    # 三层同心网格 + 轴线
    for level in (1 / 3, 2 / 3, 1.0):
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in (point(i, level) for i in range(len(METRICS))))
        width = 1.4 if level == 1.0 else 1.0
        parts.append(f'<polygon points="{points}" fill="none" stroke="{GRID}" stroke-width="{width}"/>')
    for i in range(len(METRICS)):
        x, y = point(i, 1.0)
        parts.append(f'<line x1="{cx:.2f}" y1="{cy:.2f}" x2="{x:.2f}" y2="{y:.2f}" stroke="{GRID}" stroke-width="1"/>')

    # 数据多边形
    for index, item in enumerate(series):
        stroke, light = PALETTE[index % len(PALETTE)]
        coords = []
        for i, metric in enumerate(METRICS):
            value = item.get(metric.key)
            coords.append(point(i, metric.norm(value) if value is not None else 0.0))
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in coords)
        parts.append(f'<polygon points="{points}" fill="{light}" fill-opacity="0.30" stroke="{stroke}" stroke-width="2.4" stroke-linejoin="round"/>')
        for x, y in coords:
            parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.6" fill="{stroke}"/>')

    # 轴标签：指标名 + 该轴的参考区间
    for i, metric in enumerate(METRICS):
        x, y = point(i, 1.0)
        # 沿轴向外推一点，避免压到图形
        dx, dy = (x - cx) / radius, (y - cy) / radius
        lx, ly = x + dx * 46, y + dy * 30
        anchor = "middle"
        if dx > 0.35:
            anchor = "start"
        elif dx < -0.35:
            anchor = "end"
        parts.append(f'<text x="{lx:.0f}" y="{ly:.0f}" font-size="14" font-weight="700" fill="{INK}" text-anchor="{anchor}">{_esc(metric.label)}</text>')
        parts.append(f'<text x="{lx:.0f}" y="{ly + 17:.0f}" font-size="11" fill="{INK_SOFT}" text-anchor="{anchor}">{_esc(f"{metric.lo:g} – {metric.hi:g}")}</text>')

    # 图例
    parts.extend(_legend(series, x=RADAR_W - 190, y=118))

    # 底部说明
    parts.append(
        f'<text x="32" y="{RADAR_H - 34}" font-size="12" fill="{INK_SOFT}">'
        f"形状按各指标的常见区间归一化后绘制，仅用于横向比较强弱；真实数值见柱状图或数据表。"
        f"</text>"
    )
    parts.append(
        f'<text x="32" y="{RADAR_H - 16}" font-size="12" fill="{INK_SOFT}">'
        f"归一化参考区间：{_esc(' / '.join(f'{m.label} {m.lo:g}–{m.hi:g}' for m in METRICS))}</text>"
    )

    parts.append("</svg>")
    return "".join(parts), RADAR_W, RADAR_H


# ---------------------------------------------------------------------------
# 柱状图
# ---------------------------------------------------------------------------

BAR_W = 780
BAR_H = 600


def bar_svg(series: list[Series], *, title: str, subtitle: str = "") -> tuple[str, int, int]:
    """柱状图：按指标分组，每组内每选手一根柱子。返回 (SVG, 宽, 高)。"""
    if not series:
        raise ValueError("至少需要一个选手才能画柱状图")

    left, right, top, bottom = 64.0, BAR_W - 232.0, 108.0, BAR_H - 92.0
    plot_w = right - left
    plot_h = bottom - top

    parts = _svg_open(BAR_W, BAR_H)
    parts.append(f'<text x="32" y="46" font-size="22" font-weight="700" fill="{INK}">{_esc(title)}</text>')
    if subtitle:
        parts.append(f'<text x="32" y="70" font-size="13" fill="{INK_SOFT}">{_esc(subtitle)}</text>')

    # 横向网格 + 刻度（归一化 0–100）
    for level in range(0, 101, 25):
        y = bottom - plot_h * level / 100.0
        parts.append(f'<line x1="{left:.0f}" y1="{y:.2f}" x2="{right:.0f}" y2="{y:.2f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{left - 10:.0f}" y="{y + 4:.2f}" font-size="11" fill="{INK_SOFT}" text-anchor="end">{level}</text>')

    group_w = plot_w / len(METRICS)
    bar_gap = 4.0
    count = len(series)
    bar_w = max(6.0, (group_w * 0.72 - bar_gap * (count - 1)) / count)

    for gi, metric in enumerate(METRICS):
        group_x = left + gi * group_w
        block_w = bar_w * count + bar_gap * (count - 1)
        start_x = group_x + (group_w - block_w) / 2

        for si, item in enumerate(series):
            stroke, light = PALETTE[si % len(PALETTE)]
            value = item.get(metric.key)
            ratio = metric.norm(value) if value is not None else 0.0
            h = max(2.0, plot_h * ratio)
            x = start_x + si * (bar_w + bar_gap)
            y = bottom - h
            parts.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" rx="3" fill="{light}" stroke="{stroke}" stroke-width="1.6"/>')
            # 柱顶标原始值（旋转一下，免得横排挤在一起）
            label = metric.fmt(value)
            parts.append(
                f'<text x="{x + bar_w / 2:.2f}" y="{y - 6:.2f}" font-size="11" font-weight="600" fill="{INK}" '
                f'text-anchor="end" transform="rotate(-90 {x + bar_w / 2:.2f} {y - 6:.2f})">{_esc(label)}</text>'
            )

        # 分组标题
        cx = group_x + group_w / 2
        parts.append(f'<text x="{cx:.0f}" y="{bottom + 26:.0f}" font-size="13.5" font-weight="700" fill="{INK}" text-anchor="middle">{_esc(metric.label)}</text>')

    # 基线
    parts.append(f'<line x1="{left:.0f}" y1="{bottom:.0f}" x2="{right:.0f}" y2="{bottom:.0f}" stroke="{INK_SOFT}" stroke-width="1.4"/>')

    parts.extend(_legend(series, x=BAR_W - 200, y=150))
    parts.append(
        f'<text x="32" y="{BAR_H - 22}" font-size="12" fill="{INK_SOFT}">'
        f"柱顶数字是原始值；柱高按归一化参考区间换算，跨指标比较的是相对高低，不是绝对量。</text>"
    )

    parts.append("</svg>")
    return "".join(parts), BAR_W, BAR_H


# ---------------------------------------------------------------------------
# 组装与导出
# ---------------------------------------------------------------------------


def stack_svgs(parts: list[tuple[str, int, int]], *, gap: int = 18) -> str:
    """把若干张图纵向拼成一张 SVG。"""
    if not parts:
        raise ValueError("没有要拼接的图")
    width = max(w for _, w, _ in parts)
    height = sum(h for _, _, h in parts) + gap * (len(parts) - 1)

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="{FONT}">',
        f'<rect width="{width}" height="{height}" fill="{PAPER}"/>',
    ]
    y = 0.0
    for svg_text, _w, h in parts:
        inner = svg_text[svg_text.index(">") + 1 : svg_text.rindex("</svg>")]
        out.append(f'<g transform="translate(0,{y:.0f})">{inner}</g>')
        y += h + gap
    out.append("</svg>")
    return "".join(out)


def wrap_html(svg_text: str, *, title: str) -> str:
    """把 SVG 包成一个可以直接双击打开的 HTML。"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; padding: 24px; background: #f1f5f9;
         font-family: {FONT}; display: flex; justify-content: center; }}
  .card {{ background: #fff; border-radius: 14px; padding: 12px;
           box-shadow: 0 1px 3px rgba(15,23,42,.12), 0 8px 24px rgba(15,23,42,.08);
           max-width: 100%; overflow: auto; }}
  svg {{ display: block; max-width: 100%; height: auto; }}
</style>
</head>
<body>
<div class="card">
{svg_text}
</div>
</body>
</html>
"""


def default_out_dir() -> Path:
    """图表输出目录。`HLTV_VIZ_DIR` 可覆盖，默认和浏览器 profile 放一起。"""
    override = os.environ.get("HLTV_VIZ_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    from .launcher import CACHE_DIR

    return CACHE_DIR / "charts"


def svg_to_png(svg_text: str, out_path: Path, *, scale: float = 2.0) -> tuple[bool, str]:
    """把 SVG 转成 PNG。返回 (是否成功, 用了哪个转换器 或 失败原因)。

    按 `cairosvg` → `rsvg-convert` → ImageMagick `convert` 的顺序尝试。
    三条路都不通不算致命错误 —— 调用方给 SVG 就够了。
    """
    try:
        import cairosvg  # noqa: PLC0415 - 可选依赖，用到才导入

        cairosvg.svg2png(
            bytestring=svg_text.encode("utf-8"),
            write_to=str(out_path),
            scale=scale,
            background_color="white",
        )
        if out_path.exists() and out_path.stat().st_size > 0:
            return True, "cairosvg"
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - 缺 cairo 系统库时会在这里炸
        last = f"cairosvg：{exc}"
    else:
        last = "cairosvg 没有产出文件"

    commands = [
        ("rsvg-convert", ["-o", str(out_path), "-"]),
        ("convert", ["-density", "144", "-background", "white", "-flatten", "-", str(out_path)]),
    ]
    for name, args in commands:
        binary = shutil.which(name)
        if not binary:
            continue
        try:
            proc = subprocess.run(  # noqa: S603 - 参数固定，输入是自家生成的 SVG
                [binary, *args],
                input=svg_text.encode("utf-8"),
                capture_output=True,
                timeout=60,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            last = f"{name}：{exc}"
            continue
        if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0:
            return True, name
        last = f"{name}：{proc.stderr.decode('utf-8', 'replace')[:160]}"

    return False, f"没找到可用的 SVG→PNG 转换器（{last}）。装 cairosvg 或 rsvg-convert 即可"
