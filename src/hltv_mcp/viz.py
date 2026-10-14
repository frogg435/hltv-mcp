"""把选手数据画成一个网页。

为什么最后落成网页
------------------
一开始想过出 SVG / PNG 文件，真用起来才发现**想要的形态是「一个能直接打开的网页」**：

* 十位选手的面板图要排成网格，网页的 `flex` / `grid` 天然会说这件事；
  硬拼成一张大 SVG 就得自己算每个小图的坐标和留白
* 鼠标悬停看数值、窄屏自动换行、深色模式，在网页里基本是白送的
* 图仍然是 SVG 画的（矢量、清晰、可缩放），只是**装在一个网页里**交付，
  不再单独产出 svg / png 文件

页面上三块
----------
1. **六边形面板图** —— 每人一张，按队伍排成网格（2 队 × 5 人 = 10 张）
2. **指标柱状图** —— 每人一组、组内六根柱子，鼠标悬停看数值
3. **原始数值表** —— 图上看到的是形状，精确数字在这里

关于「归一化」
--------------
六个指标量纲完全不同（Rating 是 0.5–2 的比值，ADR 几十到一百多，Swing 还带正负号），
画进同一个坐标系必须先映射到 0–1，参考区间写在 `METRICS` 里。
所以**图形只用来横向比强弱，精确数值一律以原始形式给出**（柱状图悬停提示 + 数值表）。
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# 指标
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Metric:
    """一个可画进图里的指标。

    `lo` / `hi` 是**归一化参考区间**，不是数据边界：低于 lo 记 0、高于 hi 记 1。
    取值参考职业赛事里「很糟」到「很好」的常见区间。
    """

    key: str
    label: str
    lo: float
    hi: float
    color: str
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


# 顺序即面板图上的顺时针顺序，从正上方开始。
#
# 参考区间特意贴着**职业比赛的常见跨度**取（而不是理论上限到下限）：
# 取宽了十个人会全挤在六边形中间、图形看不出差别；取窄了又会让常见数据顶到外圈。
# 这组值是按「偏差一点就会明显变形、但正常发挥不会撞到边界」调的。
METRICS: tuple[Metric, ...] = (
    Metric("kd", "K/D", 0.6, 1.8, "#2563eb"),
    Metric("rating", "Rating 3.0", 0.6, 1.8, "#7c3aed"),
    Metric("kast", "KAST", 50, 85, "#0891b2", "%"),
    Metric("swing", "Swing", -8, 8, "#ea580c"),
    Metric("adr", "ADR", 40, 110, "#059669"),
    Metric("hs", "爆头率", 30, 65, "#db2777", "%"),
)

METRIC_BY_KEY = {m.key: m for m in METRICS}

# 队伍配色：（主色, 浅色）—— 用来区分两支队伍
TEAM_COLORS: tuple[tuple[str, str], ...] = (
    ("#2563eb", "#bfdbfe"),
    ("#ea580c", "#fed7aa"),
    ("#059669", "#a7f3d0"),
    ("#7c3aed", "#ddd6fe"),
)

INK = "#0f172a"
INK_SOFT = "#64748b"
LINE = "#e2e8f0"
PAPER = "#ffffff"
BG = "#f1f5f9"

FONT = (
    "'Noto Sans CJK SC','Source Han Sans SC','PingFang SC','Microsoft YaHei',"
    "'Hiragino Sans GB',system-ui,-apple-system,'Segoe UI',sans-serif"
)


# ---------------------------------------------------------------------------
# 数据
# ---------------------------------------------------------------------------


@dataclass
class Series:
    """一位选手的一组指标原始值。"""

    name: str
    team: str = ""
    values: dict[str, float] = field(default_factory=dict)

    def get(self, key: str) -> float | None:
        value = self.values.get(key)
        return None if value is None else float(value)


@dataclass
class TeamBlock:
    """一支队伍的展示信息。"""

    name: str
    color: str
    light: str
    players: list[Series] = field(default_factory=list)


def _number(text: object) -> float | None:
    """从 "69.0%"、"+7.46%" 这类文本里取第一个数。"""
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
# SVG 片段（会被内联进网页）
# ---------------------------------------------------------------------------


def _esc(text: object) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _axis_points(cx: float, cy: float, radius: float) -> list[tuple[float, float]]:
    """六个轴顶点，从正上方开始顺时针。"""
    points = []
    for i in range(len(METRICS)):
        angle = math.tau * i / len(METRICS) - math.pi / 2
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points


def radar_svg(item: Series, *, color: str, light: str, size: int = 200) -> str:
    """一位选手的六边形面板图。

    六个顶点顺时针依次是 K/D、Rating、KAST、Swing、ADR、爆头率 ——
    十张图轴的顺序完全一致，所以**不在每张图上重复标注轴名**，
    统一由页面顶部的一张「轴示意」说明（见 `axis_legend_svg`）。
    """
    cx = cy = size / 2.0
    radius = size * 0.37
    parts = [f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" role="img">']

    # 三层同心网格
    for level in (1 / 3, 2 / 3, 1.0):
        pts = _axis_points(cx, cy, radius * level)
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        width = 1.3 if level == 1.0 else 0.9
        parts.append(f'<polygon points="{points}" fill="none" stroke="{LINE}" stroke-width="{width}"/>')
    # 轴线
    for x, y in _axis_points(cx, cy, radius):
        parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.2f}" y2="{y:.2f}" stroke="{LINE}" stroke-width="0.9"/>')

    # 数据多边形
    coords = []
    for i, metric in enumerate(METRICS):
        value = item.get(metric.key)
        ratio = metric.norm(value) if value is not None else 0.0
        angle = math.tau * i / len(METRICS) - math.pi / 2
        coords.append((cx + radius * ratio * math.cos(angle), cy + radius * ratio * math.sin(angle)))
    parts.append(
        f'<polygon points="{" ".join(f"{x:.2f},{y:.2f}" for x, y in coords)}" '
        f'fill="{light}" fill-opacity="0.72" stroke="{color}" stroke-width="2.2" stroke-linejoin="round"/>'
    )
    for i, (x, y) in enumerate(coords):
        metric = METRICS[i]
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3.2" fill="{color}">'
            f"<title>{_esc(metric.label)} {_esc(metric.fmt(item.get(metric.key)))}</title></circle>"
        )

    parts.append("</svg>")
    return "".join(parts)


def axis_legend_svg() -> str:
    """轴示意：一张标了六个轴名字的空面板图，用来说明上面那些图怎么读。

    尺寸比选手图大一档，因为要把轴名和参考区间写在六边形外侧 ——
    半径给大了标签就会被裁掉。
    """
    width, height = 300.0, 252.0
    cx, cy = 150.0, 126.0
    radius = 72.0
    parts = [
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" xmlns="http://www.w3.org/2000/svg" font-family="{FONT}">'
    ]

    for level in (1 / 3, 2 / 3, 1.0):
        pts = _axis_points(cx, cy, radius * level)
        points = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        parts.append(f'<polygon points="{points}" fill="none" stroke="{LINE}" stroke-width="1"/>')

    for i, (x, y) in enumerate(_axis_points(cx, cy, radius)):
        metric = METRICS[i]
        parts.append(f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.2f}" y2="{y:.2f}" stroke="{LINE}" stroke-width="1"/>')
        dx, dy = (x - cx) / radius, (y - cy) / radius
        lx, ly = x + dx * 14, y + dy * 16
        anchor = "middle"
        if dx > 0.35:
            anchor = "start"
        elif dx < -0.35:
            anchor = "end"
        parts.append(
            f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="13.5" font-weight="700" fill="{INK}" '
            f'text-anchor="{anchor}">{_esc(metric.label)}</text>'
        )
        parts.append(
            f'<text x="{lx:.1f}" y="{ly + 15:.1f}" font-size="11" fill="{INK_SOFT}" '
            f'text-anchor="{anchor}">{metric.lo:g} – {metric.hi:g}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def bars_svg(teams: list[TeamBlock]) -> str:
    """指标柱状图：每位选手一组，组内六根柱子对应六个指标。

    为什么按「选手」分组而不是按「指标」分组：一场比赛两队加起来十个人，
    按指标分组的话每组要塞十根柱子、而且没地方写名字；按选手分组则每组
    只有六根、下面还能写上昵称。跨选手比同一指标也不难 —— 颜色跟着指标走。
    """
    players_total = sum(len(t.players) for t in teams)
    if not players_total:
        raise ValueError("没有可绘制的选手")

    group_w = 76.0
    gap_between_teams = 26.0
    left = 62.0
    right = 26.0
    top = 34.0
    plot_h = 330.0
    bottom = top + plot_h
    label_band = 84.0

    width = left + players_total * group_w + max(0, len(teams) - 1) * gap_between_teams + right
    height = bottom + label_band

    parts = [
        f'<svg viewBox="0 0 {width:.0f} {height:.0f}" xmlns="http://www.w3.org/2000/svg" font-family="{FONT}">'
    ]

    for level in range(0, 101, 25):
        y = bottom - plot_h * level / 100.0
        parts.append(f'<line x1="{left:.0f}" y1="{y:.2f}" x2="{width - right:.0f}" y2="{y:.2f}" stroke="{LINE}" stroke-width="1"/>')
        parts.append(f'<text x="{left - 9:.0f}" y="{y + 4:.2f}" font-size="10.5" fill="{INK_SOFT}" text-anchor="end">{level}</text>')

    bar_w = group_w * 0.78 / len(METRICS)
    cursor = left
    for team_index, team in enumerate(teams):
        if team_index:
            cursor += gap_between_teams
            parts.append(
                f'<line x1="{cursor - gap_between_teams / 2:.1f}" y1="{top - 6:.0f}" '
                f'x2="{cursor - gap_between_teams / 2:.1f}" y2="{bottom:.0f}" stroke="{LINE}" '
                f'stroke-width="1" stroke-dasharray="3 3"/>'
            )
        for player in team.players:
            # 组底色：一眼看出这一列属于哪支队
            parts.append(
                f'<rect x="{cursor - 6:.1f}" y="{top - 8:.0f}" width="{group_w * 0.78 + 12:.1f}" '
                f'height="{plot_h + 8:.0f}" rx="6" fill="{team.color}" fill-opacity="0.07"/>'
            )
            for mi, metric in enumerate(METRICS):
                value = player.get(metric.key)
                ratio = metric.norm(value) if value is not None else 0.0
                bar_h = max(1.5, plot_h * ratio)
                x = cursor + mi * bar_w
                parts.append(
                    f'<rect x="{x:.2f}" y="{bottom - bar_h:.2f}" width="{bar_w * 0.86:.2f}" '
                    f'height="{bar_h:.2f}" rx="2" fill="{metric.color}" fill-opacity="0.85">'
                    f"<title>{_esc(player.name)} · {_esc(metric.label)} "
                    f"{_esc(metric.fmt(value))}</title></rect>"
                )

            label_x = cursor + group_w * 0.78
            parts.append(
                f'<text x="{label_x:.1f}" y="{bottom + 15:.0f}" font-size="11.5" font-weight="600" fill="{INK}" '
                f'text-anchor="end" transform="rotate(-42 {label_x:.1f} {bottom + 15:.0f})">{_esc(player.name)}</text>'
            )
            cursor += group_w

    parts.append(
        f'<line x1="{left:.0f}" y1="{bottom:.0f}" x2="{width - right:.0f}" y2="{bottom:.0f}" '
        f'stroke="{INK_SOFT}" stroke-width="1.4"/>'
    )
    parts.append("</svg>")
    return "".join(parts)


def metrics_legend_html() -> str:
    """柱状图的指标色图例。"""
    items = "".join(
        f'<span class="chip"><i style="background:{m.color}"></i>{_esc(m.label)}</span>'
        for m in METRICS
    )
    return f'<div class="chips">{items}</div>'


def table_html(team: TeamBlock) -> str:
    """一支队伍的原始数值表。"""
    head = "".join(f"<th>{_esc(m.label)}</th>" for m in METRICS)
    rows = []
    for player in team.players:
        cells = "".join(
            f'<td class="num">{_esc(m.fmt(player.get(m.key)))}</td>' for m in METRICS
        )
        rows.append(f'<tr><th class="who">{_esc(player.name)}</th>{cells}</tr>')
    return (
        f'<table><caption><i style="background:{team.color}"></i>{_esc(team.name)}</caption>'
        f'<thead><tr><th class="who">选手</th>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
    )


# ---------------------------------------------------------------------------
# 页面
# ---------------------------------------------------------------------------

_CSS = """
:root{--ink:#0f172a;--soft:#64748b;--line:#e2e8f0;--paper:#fff;--bg:#f1f5f9}
*{box-sizing:border-box}
body{margin:0;padding:26px 18px;background:var(--bg);color:var(--ink);
     font-family:FONT_STACK;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:21px;margin:0 0 5px}
.sub{margin:0 0 20px;color:var(--soft);font-size:13px}
section{background:var(--paper);border-radius:14px;padding:18px 20px 20px;margin-bottom:16px;
        box-shadow:0 1px 2px rgba(15,23,42,.06),0 10px 26px rgba(15,23,42,.06)}
h2{font-size:14px;margin:0 0 14px;font-weight:700;letter-spacing:.02em}
h2 .note{font-weight:400;color:var(--soft);font-size:12px;margin-left:8px}
.legend-row{display:flex;align-items:center;gap:22px;flex-wrap:wrap;margin-bottom:16px}
.legend-row .cap{font-size:12px;color:var(--soft);max-width:520px;line-height:1.6}
.legend-row svg{width:250px;height:250px;flex:none}
.team-title{display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;
            margin:18px 0 10px}
.team-title:first-of-type{margin-top:0}
.team-title i{width:11px;height:11px;border-radius:3px;display:inline-block}
.team-title span{color:var(--soft);font-weight:400}
.grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px}
.cell{border:1px solid var(--line);border-radius:11px;padding:10px 8px 9px;text-align:center;
      background:linear-gradient(180deg,rgba(255,255,255,0),rgba(15,23,42,.015))}
.cell svg{width:100%;height:auto;display:block}
.cell .name{font-weight:700;font-size:13px;margin-top:7px;white-space:nowrap;overflow:hidden;
            text-overflow:ellipsis}
.cell .val{font-size:11.5px;color:var(--soft);margin-top:2px}
.cell .val b{color:var(--ink)}
.chart-scroll{overflow-x:auto}
.chart-scroll svg{min-width:760px;width:100%;height:auto;display:block}
.chips{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:14px}
.chip{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--soft)}
.chip i{width:10px;height:10px;border-radius:2px;display:inline-block}
table{width:100%;border-collapse:collapse;font-size:12.5px}
table caption{text-align:left;font-weight:700;font-size:13px;padding:0 0 9px;
              display:flex;align-items:center;gap:7px}
table caption i{width:10px;height:10px;border-radius:3px;display:inline-block}
table + table{margin-top:18px}
th,td{padding:7px 9px;text-align:right;border-bottom:1px solid var(--line);white-space:nowrap}
thead th{color:var(--soft);font-weight:600;font-size:11.5px;text-align:right}
th.who,td.who{text-align:left;font-weight:700}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:none}
tbody tr:hover{background:rgba(37,99,235,.045)}
td.num{font-variant-numeric:tabular-nums}
footer{color:var(--soft);font-size:11.5px;text-align:center;padding:6px 0 2px}
@media(max-width:1000px){.grid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:640px){.grid{grid-template-columns:repeat(2,1fr)}
  .legend-row svg{width:190px;height:190px}}
"""


def render_page(
    teams: list[TeamBlock],
    *,
    title: str,
    subtitle: str = "",
    notes: list[str] | None = None,
) -> str:
    """把数据渲染成一张完整的网页。"""
    css = _CSS.replace("FONT_STACK", FONT)

    blocks = []
    for team in teams:
        cells = []
        for player in team.players:
            rating = player.get("rating")
            value = f'<b>{rating:.2f}</b>' if rating is not None else "—"
            cells.append(
                '<div class="cell">'
                + radar_svg(player, color=team.color, light=team.light)
                + f'<div class="name">{_esc(player.name)}</div>'
                + f'<div class="val">Rating {value}</div>'
                + "</div>"
            )
        blocks.append(
            f'<div class="team-title"><i style="background:{team.color}"></i>'
            f"{_esc(team.name)} <span>{len(team.players)} 人</span></div>"
            f'<div class="grid">{"".join(cells)}</div>'
        )

    tables = "".join(table_html(t) for t in teams)
    foot = ""
    if notes:
        foot = f'<footer>{" · ".join(_esc(n) for n in notes)}</footer>'

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <h1>{_esc(title)}</h1>
  <p class="sub">{_esc(subtitle)}</p>

  <section>
    <h2>六维面板图<span class="note">每人一张；六个顶点顺时针依次是下面这六个指标</span></h2>
    <div class="legend-row">
      {axis_legend_svg()}
      <div class="cap">
        顶点上标注的是每个轴对应的<b>归一化参考区间</b>（下面那行小字）。
        图形按区间映射后绘制，<b>只用于横向比较强弱</b>，精确数值见最下方的表格。<br><br>
        当选手的某项数据贴近区间的下界时，顶点会贴近中心；顶到最外圈则说明
        该项已经达到或超过参考上界。
      </div>
    </div>
    {"".join(blocks)}
  </section>

  <section>
    <h2>指标柱状图<span class="note">纵轴 0–100 是各指标按参考区间归一化后的相对高度（0 = 区间下界、100 = 上界）；悬停柱子可看原始数值</span></h2>
    {metrics_legend_html()}
    <div class="chart-scroll">{bars_svg(teams)}</div>
  </section>

  <section>
    <h2>原始数值</h2>
    {tables}
  </section>

  {foot}
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
