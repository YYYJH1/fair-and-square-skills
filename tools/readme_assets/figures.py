"""HTML for the README figures.

Every figure is a function that returns one complete HTML page. The page holds a single
``<main class="card">`` of fixed width. ``style.css`` gives it a rounded card background in the
colors of the theme (light or dark, set by ``data-theme`` on ``<html>``). The text of a figure
comes in English and Chinese (``lang`` on ``<html>``). Numbers are never typed in here: the
functions receive them from ``build.py``, which runs the skill scripts.

Standard library only, Python 3.9 or later.
"""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WIDTH = 880
LANGS = ("en", "zh")
THEMES = ("light", "dark")

# 24 by 24 line icons drawn from simple shapes. Stroke and color come from the CSS.
ICONS = {
    "rent-split": (
        '<path d="M3.5 11 12 4l8.5 7"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-5.5h4V20"/>'
    ),
    "bill-split": (
        '<path d="M6 3.5h12V21l-3-2-3 2-3-2-3 2z"/><path d="M9.5 8h5M9.5 12h5"/>'
        '<path d="M9.5 16h2"/>'
    ),
    "ride-split": (
        '<path d="M3 16.5v-3.7l2.4-1.8 2-3.5h9.2l2 3.5 2.4 1.8v3.7H19a2.5 2.5 0 0 0-5 0h-4a2.5 '
        '2.5 0 0 0-5 0z"/><path d="M6.2 11h11.6"/>'
        '<circle cx="7.5" cy="16.5" r="1.9"/><circle cx="16.5" cy="16.5" r="1.9"/>'
    ),
    "group-vote": (
        '<rect x="4.5" y="3.5" width="15" height="17" rx="2.5"/><path d="M8 8h8"/>'
        '<path d="m8.4 14 2.4 2.4 4.8-5.2"/>'
    ),
    "chore-split": (
        '<path d="M19.5 11.5a7.5 7.5 0 0 0-13-4.6"/><path d="M6.5 3.5v4h4"/>'
        '<path d="M4.5 12.5a7.5 7.5 0 0 0 13 4.6"/><path d="M17.5 20.5v-4h-4"/>'
    ),
    "slot-lottery": (
        '<rect x="4" y="4" width="16" height="16" rx="3.5"/>'
        '<circle cx="8.6" cy="8.6" r="1.1" fill="currentColor"/>'
        '<circle cx="15.4" cy="8.6" r="1.1" fill="currentColor"/>'
        '<circle cx="12" cy="12" r="1.1" fill="currentColor"/>'
        '<circle cx="8.6" cy="15.4" r="1.1" fill="currentColor"/>'
        '<circle cx="15.4" cy="15.4" r="1.1" fill="currentColor"/>'
    ),
    "gift-exchange": (
        '<rect x="3.5" y="8" width="17" height="4" rx="1"/><path d="M5 12v8h14v-8"/>'
        '<path d="M12 8v12"/><path d="M12 8C10 8 8.2 7.2 8.2 5.8S10.5 4 12 8z"/>'
        '<path d="M12 8c2 0 3.8-.8 3.8-2.2S13.5 4 12 8z"/>'
    ),
    "stuff-split": (
        '<path d="M12 3.5 19.5 7.7v8.6L12 20.5 4.5 16.3V7.7z"/>'
        '<path d="M4.5 7.7 12 12l7.5-4.3"/><path d="M12 12v8.5"/>'
    ),
    "check": '<circle cx="12" cy="12" r="9"/><path d="m8 12.3 2.6 2.6L16.2 9.2"/>',
    "arrow": '<path d="M4 12h15"/><path d="m13.5 6.5 5.5 5.5-5.5 5.5"/>',
}

SKILL_ORDER = (
    "rent-split",
    "bill-split",
    "ride-split",
    "group-vote",
    "chore-split",
    "slot-lottery",
    "gift-exchange",
    "stuff-split",
)


def esc(value: Any) -> str:
    """Escape text for HTML."""
    return html.escape(str(value), quote=True)


def icon(name: str, size: int = 24, extra: str = "") -> str:
    """Return an inline SVG for the icon ``name``."""
    return (
        f'<svg class="ico" viewBox="0 0 24 24" width="{size}" height="{size}" '
        f'aria-hidden="true"{extra}>{ICONS[name]}</svg>'
    )


def page(body: str, *, lang: str, theme: str) -> str:
    """Wrap a card in a complete HTML page.

    A small script writes the height of the card into ``data-height`` of ``<html>``, so that
    ``build.py`` can size the browser window to the card. Another one lets a page opened in a
    browser switch the theme with ``?theme=dark`` or ``?theme=light`` in the address.
    """
    style = (HERE / "style.css").read_text(encoding="utf-8")
    return (
        "<!doctype html>\n"
        f'<html lang="{lang}" data-theme="{theme}">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<script>\n"
        "var theme = new URLSearchParams(location.search).get('theme');\n"
        "if (theme === 'light' || theme === 'dark') {\n"
        "  document.documentElement.setAttribute('data-theme', theme);\n"
        "}\n"
        "</script>\n"
        f"<style>\n{style}\n</style>\n</head>\n<body>\n{body}\n"
        "<script>\n"
        "window.addEventListener('load', function () {\n"
        "  var r = document.getElementById('card').getBoundingClientRect();\n"
        "  document.documentElement.setAttribute('data-height', String(Math.ceil(r.bottom)));\n"
        "});\n"
        "</script>\n</body>\n</html>\n"
    )


# --------------------------------------------------------------------------------------
# Banner: the wordmark beside a square cut into four equal parts. No words, so one file
# per theme serves both READMEs.
# --------------------------------------------------------------------------------------


def _emblem() -> str:
    cell, gap, radius = 52, 8, 11
    fills = (
        ("var(--primary)", "1"),
        ("var(--primary)", "0.62"),
        ("var(--primary)", "0.38"),
        ("var(--accent-fill)", "1"),
    )
    rects = []
    for index, (fill, opacity) in enumerate(fills):
        x = (index % 2) * (cell + gap)
        y = (index // 2) * (cell + gap)
        rects.append(
            f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="{radius}" '
            f'fill="{fill}" fill-opacity="{opacity}"/>'
        )
    size = 2 * cell + gap
    return (
        f'<svg class="mark" viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
        f'aria-hidden="true">{"".join(rects)}</svg>'
    )


def _cells() -> str:
    """A faint grid of equal squares on the right edge, a few of them filled."""
    size, gap = 20, 8
    columns, rows = 6, 6
    marked = {(3, 1): "p", (4, 3): "a", (5, 1): "p", (5, 4): "p", (2, 4): "p"}
    parts = []
    for col in range(columns):
        for row in range(rows):
            x = col * (size + gap)
            y = row * (size + gap) + 4
            kind = marked.get((col, row))
            fade = 0.25 + 0.75 * (col / (columns - 1))
            if kind == "p":
                style = f'fill="var(--primary)" fill-opacity="{0.55 * fade + 0.1:.2f}"'
            elif kind == "a":
                style = f'fill="var(--accent-fill)" fill-opacity="{0.9 * fade + 0.1:.2f}"'
            else:
                style = f'fill="var(--rule)" fill-opacity="{fade:.2f}"'
            parts.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="5" {style}/>')
    width = columns * (size + gap) - gap
    height = rows * (size + gap) + 4
    return (
        f'<svg class="cells" viewBox="0 0 {width} {height}" preserveAspectRatio="xMaxYMid slice" '
        f'aria-hidden="true">{"".join(parts)}</svg>'
    )


def banner(lang: str, theme: str, data: Any = None) -> str:
    icons = "".join(icon(name, 24) for name in SKILL_ORDER)
    body = (
        '<main class="card banner" id="card">'
        f"{_cells()}{_emblem()}"
        '<div><div class="word">fair <span class="and">and</span> '
        '<span class="sq">square</span></div>'
        f'<div class="icons">{icons}</div></div>'
        "</main>"
    )
    return page(body, lang=lang, theme=theme)


# --------------------------------------------------------------------------------------
# Result card: the output of rent-split for three roommates
# --------------------------------------------------------------------------------------


def money(value: Any, *, small_cents: bool = True) -> str:
    """Format an exact amount like the scripts do: thousands commas and two decimals."""
    cents = int(value * 100)
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    head = f"{sign}{whole:,}"
    if small_cents:
        return f"{head}<small>.{rest:02d}</small>"
    return f"{head}.{rest:02d}"


RENT_TEXT = {
    "en": {
        "title": "Three roommates, one flat",
        "sub": "Everybody bids privately on every room. The bids of one person add up to the total rent.",
        "total": "Total rent per month",
        "lives": "lives in",
        "per": "per month",
        "bid": "bid",
        "rent": "rent",
        "gain": "gain",
        "foot": "The rents add up to the total. Largest envy after rounding to the cent: {envy}.",
    },
    "zh": {
        "title": "三个室友，一套房",
        "sub": "每个人对每间房私下报价，同一个人的几个报价加起来等于总租金。",
        "total": "每月总租金",
        "lives": "住",
        "per": "每月",
        "bid": "报价",
        "rent": "房租",
        "gain": "赚到",
        "foot": "三间房租加起来等于总租金。取整到分后的最大羡慕：{envy}。",
    },
}


def rent_card(lang: str, theme: str, data: dict[str, Any]) -> str:
    text = RENT_TEXT[lang]
    top = max(row["bid"] for row in data["rows"])
    rows = []
    for row in data["rows"]:
        bar_rent = float(row["rent"] / top) * 100
        bar_gain = float(row["gain"] / top) * 100
        rows.append(
            '<article class="rc-row panel"><div class="rc-main">'
            f'<div class="who"><span class="avatar">{esc(row["person"][0])}</span>'
            f'<div><div class="name">{esc(row["person"])}</div>'
            f'<div class="room">{text["lives"]} <b>{esc(row["room"])}</b></div></div></div>'
            f'<div><div class="rent">{money(row["rent"])}</div>'
            f'<div class="rent-cap">{text["per"]}</div></div>'
            f'<div><div class="bar"><i class="b-rent" style="width:{bar_rent:.2f}%"></i>'
            f'<i class="b-gain" style="width:{bar_gain:.2f}%"></i></div>'
            f'<div class="eq"><span class="k-rent">{text["rent"]}</span> '
            f"{money(row['rent'], small_cents=False)} + "
            f'<span class="k-gain">{text["gain"]}</span> {money(row["gain"], small_cents=False)}'
            f" = {text['bid']} {money(row['bid'], small_cents=False)}</div></div></div>"
            f'<p class="proof">{icon("check", 18)}<span>{esc(row["line"])}</span></p>'
            "</article>"
        )
    foot = text["foot"].format(envy=money(data["max_envy"], small_cents=False))
    body = (
        '<main class="card" id="card">'
        '<header class="rc-head"><span class="tag">rent-split</span>'
        f'<div style="flex:1"><h2>{text["title"]}</h2><div class="sub">{text["sub"]}</div></div>'
        f'<div class="rc-total"><div class="label">{text["total"]}</div>'
        f"<b>{money(data['total'], small_cents=False)}</b></div></header>"
        f"{''.join(rows)}"
        f'<footer class="foot"><span>{esc(foot)}</span>'
        f'<span class="mono">{esc(data["input_file"])}</span></footer>'
        "</main>"
    )
    return page(body, lang=lang, theme=theme)


# --------------------------------------------------------------------------------------
# The eight skills
# --------------------------------------------------------------------------------------

SKILL_TEXT = {
    "en": {
        "rent-split": (
            "Who gets which room, and what does each person pay?",
            "Envy-free rent division",
        ),
        "bill-split": (
            "Who owes whom after a shared bill?",
            "Exact cents, fewest transfers, Shapley value",
        ),
        "ride-split": (
            "What does each rider pay when people get off in turn?",
            "Shapley value of the airport game",
        ),
        "group-vote": (
            "Which option wins, and under which counting rule?",
            "Seven counting rules, Schulze and Borda among them",
        ),
        "chore-split": (
            "Who does which chore this week?",
            "Round-robin picking, envy-free up to one chore",
        ),
        "slot-lottery": (
            "Who gets one of the limited slots?",
            "Lottery, probabilistic serial, deferred acceptance",
        ),
        "gift-exchange": (
            "Who gives a gift to whom?",
            "Hall's theorem check, uniform draw of a legal plan",
        ),
        "stuff-split": (
            "Who takes which shared item?",
            "Envy-free with cash, Knaster, maximum Nash welfare",
        ),
    },
    "zh": {
        "rent-split": ("谁住哪间房，各付多少？", "无嫉妒分房租"),
        "bill-split": ("一笔账单，谁转给谁？", "精确到分，最少转账\n拼单优惠按 Shapley 值分摊"),
        "ride-split": ("打车费怎么分？", "按下车先后分摊\n机场博弈的 Shapley 值"),
        "group-vote": ("投票选哪个，怎么计票？", "七种计票规则并列\n含 Schulze 和 Borda"),
        "chore-split": ("这周谁做哪件家务？", "轮流挑选\n去掉一件后无嫉妒"),
        "slot-lottery": ("名额不够，谁拿到？", "公开随机源抽签\n概率序列，延迟接受"),
        "gift-exchange": ("交换礼物，谁送给谁？", "Hall 定理预检\n合法方案等概率抽取"),
        "stuff-split": ("共同的东西，谁拿哪件？", "无嫉妒加转账\nKnaster，最大纳什福利"),
    },
}


def skills_overview(lang: str, theme: str, data: Any = None) -> str:
    cards = []
    for name in SKILL_ORDER:
        question, method = SKILL_TEXT[lang][name]
        cards.append(
            '<article class="skill panel">'
            f'<div class="top"><span class="ibox">{icon(name, 22)}</span>'
            f'<span class="nm">{name}</span></div>'
            f'<div class="q">{esc(question)}</div>'
            f'<div class="m">{"<br>".join(esc(line) for line in method.split(chr(10)))}</div>'
            "</article>"
        )
    body = f'<main class="card" id="card"><div class="skills">{"".join(cards)}</div></main>'
    return page(body, lang=lang, theme=theme)


# --------------------------------------------------------------------------------------
# How it works: the agent talks and the script computes
# --------------------------------------------------------------------------------------

FLOW_TEXT = {
    "en": {
        "agent": "agent",
        "script": "script",
        "title": "The agent talks. A bundled script computes.",
        "steps": (
            ("Hear the situation", "Rent, a bill, a vote or a draw, in plain words."),
            ("Collect the numbers", "Asks for what is missing and never guesses a number."),
            ("Write the input", "Reads the table back and waits for a yes."),
            ("Run the script", "Python standard library. Exact fractions, rounded to the cent."),
            ("Quote the result", "One private line per person, one summary for the group."),
        ),
        "routes": (
            (
                "Claude Code",
                (
                    "The input goes into a file in the session scratchpad. The script runs with "
                    "<code>--delete-input</code> and deletes the file as soon as it has read it."
                ),
            ),
            (
                "Codex and other tools",
                "The input goes to the script on standard input. No input file is created.",
            ),
        ),
    },
    "zh": {
        "agent": "Agent",
        "script": "脚本",
        "title": "Agent 负责对话，随包附带的脚本负责计算。",
        "steps": (
            ("听情况", "用大白话说清\n房租、账单、\n投票或抽签。"),
            ("收数字", "缺什么问什么，\n不替人猜数字。"),
            ("写输入", "整理成表读回，\n等组织者确认。"),
            ("跑脚本", "只用标准库，\n精确分数计算，\n取整到分。"),
            ("转述结果", "每人一句私信，\n群里一份汇总。"),
        ),
        "routes": (
            (
                "Claude Code",
                (
                    "输入写进会话 scratchpad 里的文件，运行时加 <code>--delete-input</code>，"
                    "脚本读完立刻删除。"
                ),
            ),
            ("Codex 等其他工具", "输入从标准输入传给脚本，不产生输入文件。"),
        ),
    },
}


def how_it_works(lang: str, theme: str, data: Any = None) -> str:
    text = FLOW_TEXT[lang]
    steps = []
    for index, (title, line) in enumerate(text["steps"]):
        is_script = index == 3
        who = text["script"] if is_script else text["agent"]
        arrow = f'<span class="arrow">{icon("arrow", 18)}</span>' if index < 4 else ""
        steps.append(
            f'<article class="step panel{" script" if is_script else ""}">'
            f'<span class="who-badge">{who}</span><div class="n">{index + 1}</div>'
            f"<h3>{esc(title)}</h3><p>{'<br>'.join(esc(part) for part in line.split(chr(10)))}</p>"
            f"{arrow}</article>"
        )
    routes = "".join(
        f'<div class="route panel"><b>{esc(name)}</b>{note}</div>' for name, note in text["routes"]
    )
    body = (
        '<main class="card" id="card">'
        f'<div class="flow-title">{esc(text["title"])}</div>'
        f'<div class="steps">{"".join(steps)}</div><div class="routes">{routes}</div></main>'
    )
    return page(body, lang=lang, theme=theme)


# --------------------------------------------------------------------------------------
# Mechanism 1: the eating schedule of probabilistic serial (slot-lottery)
# --------------------------------------------------------------------------------------


def frac(value: Any) -> str:
    """Write an exact fraction the way the scripts do: 1/2, 13/18, 0 and 1."""
    return (
        str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    )


PS_TEXT = {
    "en": {
        "title": "Probabilistic serial: everybody eats at once",
        "sub": (
            "Each person eats the best slot on their list that is not used up yet. Everybody eats "
            "at the same speed from time 0 to time 1. The share of a slot a person has eaten is "
            "their chance of getting it."
        ),
        "seats": "{n} seats",
        "none": "nothing left to eat",
        "rank": ("Ranking", "best first"),
        "dots": "A dot marks the slot that is used up at that time",
        "time": "time",
        "foot": "{people} people, {slots} slots, {seats} seats. Each segment shows the chance of its slot.",
    },
    "zh": {
        "title": "概率序列：所有人同时开吃",
        "sub": (
            "每个人从自己志愿里还没吃完的最好时段开始吃，所有人速度相同，时间从 0 走到 1。"
            "吃掉的份额，就是拿到这个时段的概率。"
        ),
        "seats": "{n} 个名额",
        "none": "没东西可吃了",
        "rank": ("志愿", "最想要的在前"),
        "dots": "圆点标出此刻吃完的时段",
        "time": "时间",
        "foot": "{people} 个人，{slots} 个时段，共 {seats} 个名额。每段上标的是拿到该时段的概率。",
    },
}


def seat_note(text: dict[str, Any], seats: int) -> str:
    """The seat count after a slot name, only for a slot with more than one seat."""
    if seats <= 1:
        return ""
    note = text["seats"].format(n=seats)
    return f"（{note}）" if text["seats"].endswith("名额") else f" ({note})"


def ps_timeline(lang: str, theme: str, data: dict[str, Any]) -> str:
    text = PS_TEXT[lang]
    slots = data["slots"]
    order = {slot["id"]: index + 1 for index, slot in enumerate(slots)}
    width, x0, span = 816, 142, 640
    top, pitch, bar = 58, 36, 24
    people = data["people"]
    bottom = top + pitch * len(people)

    def x_of(moment: Any) -> float:
        return x0 + float(moment) * span

    parts = [
        f'<text class="col-head" x="72" y="12">{esc(text["rank"][0])}</text>',
        f'<text class="col-head" x="72" y="27">{esc(text["rank"][1])}</text>',
        f'<text class="col-head" x="{width}" y="14" text-anchor="end">{esc(text["dots"])}</text>',
        (
            f'<text class="col-head" x="{x0 - 14}" y="{bottom + 22}" text-anchor="end">'
            f"{esc(text['time'])}</text>"
        ),
    ]
    moments = [event[0] for event in data["events"]]
    for moment in [0, *moments, 1]:
        parts.append(
            f'<line class="grid" x1="{x_of(moment):.1f}" y1="38" x2="{x_of(moment):.1f}" '
            f'y2="{bottom + 4}"/>'
        )
    for moment, slot in data["events"]:
        parts.append(f'<circle class="s{order[slot]}" cx="{x_of(moment):.1f}" cy="38" r="5.5"/>')
    for index, person in enumerate(people):
        centre = top + pitch * index + pitch / 2
        parts.append(
            f'<text class="pname" x="0" y="{centre}" dominant-baseline="central">'
            f"{esc(person['label'])}</text>"
        )
        for rank, slot in enumerate(person["ranking"]):
            parts.append(
                f'<circle class="s{order[slot]}" cx="{78 + rank * 15}" cy="{centre}" r="5"/>'
            )
        for slot, start, end in person["runs"]:
            left = x_of(start) + 1
            size = (float(end) - float(start)) * span - 2
            klass = "none-run" if slot is None else f"s{order[slot]}"
            ink = "t0" if slot is None else f"t{order[slot]}"
            parts.append(
                f'<rect class="{klass}" x="{left:.1f}" y="{centre - bar / 2}" width="{size:.1f}" '
                f'height="{bar}" rx="5"/>'
                f'<text class="frac {ink}" x="{left + size / 2:.1f}" y="{centre}" '
                f'text-anchor="middle" dominant-baseline="central">{frac(end - start)}</text>'
            )
    for moment in [0, *moments, 1]:
        parts.append(
            f'<text class="tick" x="{x_of(moment):.1f}" y="{bottom + 22}" '
            f'text-anchor="middle">{frac(moment)}</text>'
        )
    chart = (
        f'<svg class="chart" viewBox="0 0 {width} {bottom + 32}" width="{width}" '
        f'height="{bottom + 32}">{"".join(parts)}</svg>'
    )
    legend = (
        "".join(
            f'<span><i class="s{index + 1}"></i>{esc(slot["label"])}'
            f"{seat_note(text, slot['seats'])}</span>"
            for index, slot in enumerate(slots)
        )
        + f'<span><i class="none"></i>{esc(text["none"])}</span>'
    )
    foot = text["foot"].format(
        people=len(people), slots=len(slots), seats=sum(slot["seats"] for slot in slots)
    )
    body = (
        '<main class="card" id="card"><header class="mech-head"><span class="tag">slot-lottery</span>'
        f'<div class="t"><h2>{esc(text["title"])}</h2><p>{esc(text["sub"])}</p></div></header>'
        f'<div class="legend">{legend}</div>{chart}<footer class="foot"><span>{esc(foot)}</span>'
        f'<span class="mono">{esc(data["input_file"])}</span></footer></main>'
    )
    return page(body, lang=lang, theme=theme)


# --------------------------------------------------------------------------------------
# Mechanism 2: one circle of gift-exchange
# --------------------------------------------------------------------------------------

RING_TEXT = {
    "en": {
        "title": "One circle, drawn from a public source",
        "sub": (
            "Everybody gives one gift and gets one. Nobody draws themselves, and the excluded "
            "directions never appear."
        ),
        "gives": "gives to",
        "pair": "may not draw each other",
        "one": "may not give to (one way)",
        "rules": "exclusion rules: {pairs} pairs and {one_way} one-way rule",
        "plans": "legal single circles for these {n} people",
        "drawn": "number of the circle drawn, picked by SHA-256 over the rule name, the names and the public source text",
        "seed": "seed",
        "foot": "The same input and source text give the same circle every time.",
    },
    "zh": {
        "title": "一个大圈，由公开随机源抽出",
        "sub": "每个人送出一份礼物，也收到一份。没有人抽到自己，被排除的方向不会出现。",
        "gives": "送给",
        "pair": "互相不能抽到",
        "one": "不能送给（单向）",
        "rules": "条排除规则：{pairs} 对互相不能抽，{one_way} 条单向",
        "plans": "种合法的单圈方案（{n} 个人）",
        "drawn": "抽中的圈的编号，由规则名、名单和公开随机源文本的 SHA-256 选出",
        "seed": "种子",
        "foot": "同样的输入和随机源文本，每次得到同一个圈。",
    },
}


def _polar(cx: float, cy: float, radius: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


def _ring_svg(data: dict[str, Any]) -> str:
    size, centre, radius, node = 360, 180.0, 122.0, 30.0
    count = len(data["circle"])
    angle = {}
    for index, item in enumerate(data["circle"]):
        angle[item["id"]] = -90.0 + 360.0 * index / count
    point = {key: _polar(centre, centre, radius, deg) for key, deg in angle.items()}
    parts = []
    # excluded directions: dashed chords under the circle
    for left, right in data["pairs"]:
        (x1, y1), (x2, y2) = point[left], point[right]
        parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="var(--accent)" '
            'stroke-width="1.6" stroke-dasharray="5 5" stroke-opacity="0.75"/>'
        )
    for giver, receiver in data["one_way"]:
        (x1, y1), (x2, y2) = point[giver], point[receiver]
        length = math.hypot(x2 - x1, y2 - y1)
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        tip = (x2 - ux * (node + 3), y2 - uy * (node + 3))
        base = (tip[0] - ux * 10, tip[1] - uy * 10)
        parts.append(
            f'<line x1="{x1 + ux * node:.1f}" y1="{y1 + uy * node:.1f}" x2="{base[0]:.1f}" '
            f'y2="{base[1]:.1f}" stroke="var(--accent)" stroke-width="1.6" '
            'stroke-dasharray="5 5" stroke-opacity="0.75"/>'
            f'<polygon fill="var(--accent)" fill-opacity="0.85" points="{tip[0]:.1f},{tip[1]:.1f} '
            f"{base[0] - uy * 5:.1f},{base[1] + ux * 5:.1f} {base[0] + uy * 5:.1f},"
            f'{base[1] - ux * 5:.1f}"/>'
        )
    # the circle: one arc and one arrow head per gift
    gap = math.degrees((node + 5) / radius)
    for item in data["circle"]:
        start = angle[item["id"]] + gap
        end = angle[item["id"]] + 360.0 / count - gap
        sx, sy = _polar(centre, centre, radius, start)
        ex, ey = _polar(centre, centre, radius, end)
        parts.append(
            f'<path d="M{sx:.1f} {sy:.1f} A{radius} {radius} 0 0 1 {ex:.1f} {ey:.1f}" fill="none" '
            'stroke="var(--primary)" stroke-width="2.4" stroke-linecap="round"/>'
        )
        rad = math.radians(end)
        tx, ty = -math.sin(rad), math.cos(rad)
        nx, ny = math.cos(rad), math.sin(rad)
        back = (ex - tx * 11, ey - ty * 11)
        parts.append(
            f'<polygon fill="var(--primary)" points="{ex + tx * 3:.1f},{ey + ty * 3:.1f} '
            f"{back[0] + nx * 6:.1f},{back[1] + ny * 6:.1f} {back[0] - nx * 6:.1f},"
            f'{back[1] - ny * 6:.1f}"/>'
        )
    for item in data["circle"]:
        x, y = point[item["id"]]
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{node}" fill="var(--panel)" '
            'stroke="var(--primary)" stroke-width="2"/>'
            f'<text x="{x:.1f}" y="{y:.1f}" dominant-baseline="central">{esc(item["label"])}</text>'
        )
    return (
        f'<svg class="ring" viewBox="0 0 {size} {size}" width="{size}" height="{size}">'
        f"{''.join(parts)}</svg>"
    )


def gift_ring(lang: str, theme: str, data: dict[str, Any]) -> str:
    text = RING_TEXT[lang]
    people = len(data["circle"])
    legend = (
        '<div class="legend key">'
        '<span><svg width="30" height="12"><line x1="1" y1="6" x2="21" y2="6" '
        'stroke="var(--primary)" stroke-width="2.4"/><polygon fill="var(--primary)" '
        f'points="29,6 20,1.5 20,10.5"/></svg>{esc(text["gives"])}</span>'
        '<span><svg width="30" height="12"><line x1="1" y1="6" x2="29" y2="6" '
        'stroke="var(--accent)" stroke-width="1.6" stroke-dasharray="5 4"/></svg>'
        f"{esc(text['pair'])}</span>"
        '<span><svg width="30" height="12"><line x1="1" y1="6" x2="20" y2="6" '
        'stroke="var(--accent)" stroke-width="1.6" stroke-dasharray="5 4"/>'
        '<polygon fill="var(--accent)" points="29,6 20,1.5 20,10.5"/></svg>'
        f"{esc(text['one'])}</span></div>"
    )
    stats = (
        f'<div class="stat"><b>{len(data["pairs"]) + len(data["one_way"])}</b>'
        f"<span>{esc(text['rules'].format(pairs=len(data['pairs']), one_way=len(data['one_way'])))}"
        "</span></div>"
        f'<div class="stat"><b>{data["plan_count"]}</b>'
        f"<span>{esc(text['plans'].format(n=people))}</span></div>"
        f'<div class="stat"><b>{data["plan_number"]}</b>'
        f"<span>{esc(text['drawn'])}</span></div>"
    )
    body = (
        '<main class="card" id="card"><header class="mech-head"><span class="tag">gift-exchange</span>'
        f'<div class="t"><h2>{esc(text["title"])}</h2><p>{esc(text["sub"])}</p></div></header>'
        f'<div class="ring-wrap"><div>{_ring_svg(data)}</div>'
        f'<div class="stats">{stats}'
        f'<div class="seed panel">{esc(text["seed"])} <b>{esc(data["seed"][:24])}…</b></div>'
        f"{legend}</div></div>"
        f'<footer class="foot"><span>{esc(text["foot"])}</span>'
        f'<span class="mono">{esc(data["input_file"])}</span></footer></main>'
    )
    return page(body, lang=lang, theme=theme)
