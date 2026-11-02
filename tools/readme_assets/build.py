"""Rebuild the figures that the READMEs show, in docs/assets/.

Standard library only, Python 3.9 or later::

    CHROME_BIN=/path/to/chrome-headless-shell python3 tools/readme_assets/build.py

For every figure the script does three things.

1. It runs the skill scripts (``--json``) to get the numbers. Nothing in a figure is typed in
   by hand: the rents, the eating schedule and the circle are the output of the scripts.
2. It writes one HTML page per language and theme (``figures.py`` and ``style.css``).
3. It lets headless Chromium screenshot each page at twice the resolution, on a transparent
   background so that the rounded card corners stay clear.

Options: ``--only`` picks figures, ``--lang`` and ``--theme`` pick variants, ``--workdir`` is the
folder for the HTML and the browser profile, ``--html-only`` stops after step 2 and
``--keep-html`` keeps the pages. See README.md in this folder.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
import os
import re
import shutil
import signal
import struct
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

import figures

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SKILLS = REPO / "plugin" / "skills"
OUT_DIR = REPO / "docs" / "assets"
MAX_BYTES = 400 * 1024
SCALE = 2
CHROME_NAMES = (
    "chrome-headless-shell",
    "chromium",
    "chromium-browser",
    "google-chrome",
    "google-chrome-stable",
)


class BuildError(RuntimeError):
    """Raised when a script, the browser or a check fails."""


# --------------------------------------------------------------------------------------
# Running the skill scripts
# --------------------------------------------------------------------------------------


def run_script(skill: str, script: str, *args: str) -> str:
    """Run ``plugin/skills/<skill>/scripts/<script>`` and return its standard output."""
    path = SKILLS / skill / "scripts" / script
    command = [sys.executable, "-B", str(path), *args]
    done = subprocess.run(
        command,
        cwd=REPO,
        capture_output=True,
        encoding="utf-8",
        check=False,
        timeout=120,
    )
    if done.returncode != 0:
        raise BuildError(f"{script} exited with {done.returncode}: {done.stderr.strip()}")
    return done.stdout


def run_json(skill: str, script: str, *args: str) -> dict[str, Any]:
    """Run a skill script with ``--json`` and parse the envelope."""
    return json.loads(run_script(skill, script, *args, "--json"))


# --------------------------------------------------------------------------------------
# Data for the figures that show script output
# --------------------------------------------------------------------------------------

RENT_CARD = {"en": HERE / "rent_card.en.json", "zh": HERE / "rent_card.zh.json"}
# The Chinese figures run the examples of the skills. The English figures run the same inputs
# with English names, so every figure is the output of a real run.
PS_INPUT = {
    "en": HERE / "ps_holiday_weeks.en.json",
    "zh": SKILLS / "slot-lottery" / "examples" / "ps_holiday_weeks.json",
}
RING_INPUT = {
    "en": HERE / "six_circle.en.json",
    "zh": SKILLS / "gift-exchange" / "examples" / "six_circle.json",
}


def read_rent_card(lang: str) -> dict[str, Any]:
    """Run rent-split on the fixed input of the card and return what the card shows."""
    path = RENT_CARD[lang]
    spec = json.loads(path.read_text(encoding="utf-8"))
    envelope = run_json("rent-split", "rent_split.py", "--input", str(path), "--lang", lang)
    result, certificate = envelope["result"], envelope["certificate"]
    bids = envelope["inputs_echo"]["bids"]
    rows = []
    for person in spec["bids"]:
        room = result["assignment"][person]
        rent = Fraction(result["rent_cents"][room])
        bid = Fraction(bids[person][room])
        gain = Fraction(result["surplus_cents"][person])
        if bid - rent != gain:
            raise BuildError(f"rent card: bid - rent != gain for {person}")
        rows.append(
            {
                "person": person,
                "room": room,
                "room_index": spec["rooms"].index(room),
                "rent": rent,
                "bid": bid,
                "gain": gain,
                "line": certificate["one_liner"][person],
            }
        )
    total = Fraction(envelope["inputs_echo"]["total_rent"])
    if sum(row["rent"] for row in rows) != total:
        raise BuildError("rent card: the rents do not add up to the total")
    return {
        "total": total,
        "rows": rows,
        "max_envy": Fraction(result["max_envy_cents"]),
        "input_file": "/".join(path.parts[-3:]),
    }


def numbers_of_rent_card(card: dict[str, Any]) -> list[tuple[Any, ...]]:
    """The numbers of a card without any label, to compare the two languages."""
    return [(r["room_index"], r["rent"], r["bid"], r["gain"]) for r in card["rows"]] + [
        (card["total"], card["max_envy"])
    ]


def collect_rent_card(lang: str) -> dict[str, Any]:
    """The card of one language. Both language inputs must give the same numbers."""
    card = read_rent_card(lang)
    other = read_rent_card("zh" if lang == "en" else "en")
    if numbers_of_rent_card(card) != numbers_of_rent_card(other):
        raise BuildError("rent card: the English and the Chinese input give different numbers")
    return card


def collect_ps(lang: str) -> dict[str, Any]:
    """Run slot-lottery (probabilistic serial) on the holiday-weeks example."""
    source = PS_INPUT[lang]
    spec = json.loads(source.read_text(encoding="utf-8"))
    envelope = run_json("slot-lottery", "slot_lottery.py", "--input", str(source))
    certificate = envelope["certificate"]
    capacities = envelope["inputs_echo"]["capacities"]
    phases = [
        {
            "start": Fraction(phase["from"]),
            "end": Fraction(phase["to"]),
            "eats": phase["eating"],
            "used_up": phase["used_up"],
        }
        for phase in certificate["eating"]
    ]
    events = [(phase["end"], slot) for phase in phases for slot in phase["used_up"]]
    people = []
    for person in spec["people"]:
        entry = certificate["probabilities"][person]
        chance = {slot: Fraction(value) for slot, value in entry["slots"].items()}
        chance[None] = Fraction(entry["no_slot"])
        # One run per slot: a person eats a slot until it is used up and never goes back.
        runs: list[tuple[Any, Fraction, Fraction]] = []
        for phase in phases:
            slot = phase["eats"][person]
            if runs and runs[-1][0] == slot:
                runs[-1] = (slot, runs[-1][1], phase["end"])
            else:
                runs.append((slot, phase["start"], phase["end"]))
        seen = [run[0] for run in runs]
        if len(seen) != len(set(seen)):
            raise BuildError(f"slot-lottery: {person} eats a slot in two separate stretches")
        # The chance of a slot is the time spent eating it: check our reading of the schedule.
        if {run[0]: run[2] - run[1] for run in runs} != chance:
            raise BuildError(f"slot-lottery: schedule and chances disagree for {person}")
        people.append(
            {
                "id": person,
                "label": person,
                "ranking": list(spec["prefs"][person]),
                "runs": runs,
            }
        )
    slots = [
        {"id": slot, "label": slot, "seats": int(capacities.get(slot, 1))} for _, slot in events
    ]
    if {slot["id"] for slot in slots} != set(spec["slot_names"]):
        raise BuildError("slot-lottery: not every slot is used up in the schedule")
    return {
        "people": people,
        "slots": slots,
        "events": events,
        "input_file": "/".join(source.parts[-3:]),
    }


def collect_ring(lang: str) -> dict[str, Any]:
    """Run gift-exchange (one circle) on the six-people example."""
    source = RING_INPUT[lang]
    spec = json.loads(source.read_text(encoding="utf-8"))
    envelope = run_json("gift-exchange", "gift_exchange.py", "--input", str(source))
    result = envelope["result"]
    circle = list(result["circle"])
    directions = {(d["giver"], d["receiver"]) for d in envelope["inputs_echo"]["forbidden"]}
    pairs = sorted({tuple(sorted(d)) for d in directions if (d[1], d[0]) in directions})
    one_way = sorted(d for d in directions if (d[1], d[0]) not in directions)
    if sorted(circle) != sorted(spec["people"]):
        raise BuildError("gift-exchange: the circle does not hold every person once")
    for index, giver in enumerate(circle):
        receiver = circle[(index + 1) % len(circle)]
        if result["assignments"][giver] != receiver:
            raise BuildError("gift-exchange: the circle does not follow the assignments")
        if (giver, receiver) in directions:
            raise BuildError("gift-exchange: the circle uses a direction that is not allowed")
    return {
        "circle": [{"id": name, "label": name} for name in circle],
        "pairs": pairs,
        "one_way": one_way,
        "plan_count": int(result["plan_count"]),
        "plan_number": int(result["plan_number"]),
        "seed": result["seed_hex"],
        "input_file": "/".join(source.parts[-3:]),
    }


# --------------------------------------------------------------------------------------
# The browser
# --------------------------------------------------------------------------------------


def find_chrome() -> str:
    """Return the browser binary named by CHROME_BIN, or the first one found on PATH."""
    named = os.environ.get("CHROME_BIN", "").strip()
    if named:
        if not (os.path.isfile(named) and os.access(named, os.X_OK)):
            raise BuildError(f"CHROME_BIN is not an executable file: {named}")
        return named
    for name in CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    raise BuildError(
        "no browser found. Set CHROME_BIN to a headless Chromium, for example the "
        "chrome-headless-shell binary of Playwright."
    )


def run_browser(chrome: str, workdir: Path, args: list[str], timeout: int = 90) -> str:
    """Run the browser in its own process group and return its standard output.

    The temporary files of the browser go to ``workdir``. On a timeout the whole group is
    stopped, so no helper process is left behind.
    """
    profile = workdir / "profile"
    scratch = workdir / "tmp"
    profile.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    command = [
        chrome,
        "--headless",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--hide-scrollbars",
        "--default-background-color=00000000",
        f"--user-data-dir={profile}",
        *args,
    ]
    env = dict(os.environ, TMPDIR=str(scratch))
    process = subprocess.Popen(
        command,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        start_new_session=True,
    )
    try:
        out, err = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The group was created for this run (start_new_session), so it holds only our browser.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise BuildError(f"the browser did not finish within {timeout} s") from None
    if process.returncode != 0:
        raise BuildError(f"the browser exited with {process.returncode}: {err.strip()[-400:]}")
    return out


def measure_height(chrome: str, workdir: Path, page: Path, width: int) -> int:
    """Return the height of the card of a page, in CSS pixels."""
    dump = run_browser(
        chrome,
        workdir,
        [f"--window-size={width},1600", "--dump-dom", page.as_uri()],
    )
    found = re.search(r'data-height="(\d+)"', dump)
    if not found:
        raise BuildError(f"could not read the height of {page.name}")
    return int(found.group(1))


def screenshot(chrome: str, workdir: Path, page: Path, png: Path, width: int) -> tuple[int, int]:
    """Screenshot a page at twice the resolution. Return the size of the PNG in pixels."""
    height = measure_height(chrome, workdir, page, width)
    png.parent.mkdir(parents=True, exist_ok=True)
    run_browser(
        chrome,
        workdir,
        [
            f"--force-device-scale-factor={SCALE}",
            f"--window-size={width},{height}",
            f"--screenshot={png}",
            page.as_uri(),
        ],
    )
    size = png_size(png)
    if size != (width * SCALE, height * SCALE):
        raise BuildError(
            f"{png.name} is {size[0]}x{size[1]}, expected {width * SCALE}x{height * SCALE}"
        )
    return size


def png_size(path: Path) -> tuple[int, int]:
    """Read the width and the height from the header of a PNG file."""
    with path.open("rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise BuildError(f"{path.name} is not a PNG file")
    width, height = struct.unpack(">II", header[16:24])
    return width, height


# --------------------------------------------------------------------------------------
# The list of figures
# --------------------------------------------------------------------------------------


class Figure:
    """One figure: its file name, the variants it has and how to build its page."""

    def __init__(
        self,
        name: str,
        builder: Callable[..., str],
        collect: Callable[[str], Any] | None = None,
        languages: tuple[str, ...] = figures.LANGS,
        neutral: bool = False,
    ) -> None:
        self.name = name
        self.builder = builder
        self.collect = collect
        self.languages = languages
        self.neutral = neutral

    def file_name(self, lang: str, theme: str) -> str:
        parts = [self.name] + ([] if self.neutral else [lang]) + [theme]
        return "-".join(parts) + ".png"


FIGURES = [
    Figure("banner", figures.banner, languages=("en",), neutral=True),
    Figure("result-card", figures.rent_card, collect_rent_card),
    Figure("skills", figures.skills_overview),
    Figure("how-it-works", figures.how_it_works),
    Figure("ps-timeline", figures.ps_timeline, collect_ps),
    Figure("gift-ring", figures.gift_ring, collect_ring),
]


def build(args: argparse.Namespace) -> int:
    wanted = set(args.only.split(",")) if args.only else None
    known = {figure.name for figure in FIGURES}
    if wanted and not wanted <= known:
        raise BuildError(f"unknown figure: {', '.join(sorted(wanted - known))}")
    langs = args.lang.split(",") if args.lang else list(figures.LANGS)
    themes = args.theme.split(",") if args.theme else list(figures.THEMES)

    chrome = None if args.html_only else find_chrome()
    if args.workdir:
        workdir = Path(args.workdir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        cleanup = False
    else:
        workdir = Path(tempfile.mkdtemp(prefix="fsq-readme-"))
        cleanup = not (args.keep_html or args.html_only)
    html_dir = workdir / "html"
    html_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out).resolve() if args.out else OUT_DIR

    failed = False
    rows = []
    try:
        for figure in FIGURES:
            if wanted and figure.name not in wanted:
                continue
            for lang in figure.languages:
                if lang not in langs and not figure.neutral:
                    continue
                data = figure.collect(lang) if figure.collect else None
                for theme in themes:
                    name = figure.file_name(lang, theme)
                    page = html_dir / (name[:-4] + ".html")
                    page.write_text(figure.builder(lang, theme, data), encoding="utf-8")
                    if chrome is None:
                        continue
                    png = out_dir / name
                    width, height = screenshot(chrome, workdir, page, png, figures.WIDTH)
                    size = png.stat().st_size
                    rows.append((name, width, height, size))
                    if size > MAX_BYTES:
                        failed = True
                        print(f"too large: {name} is {size} bytes, the limit is {MAX_BYTES}")
    finally:
        if cleanup:
            shutil.rmtree(workdir, ignore_errors=True)
    for name, width, height, size in rows:
        print(f"{name:34s} {width:5d} x {height:<5d} {size / 1024:7.1f} KB")
    if args.html_only or args.keep_html:
        print(f"pages are in {html_dir}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the README figures in docs/assets/.")
    parser.add_argument("--only", help="comma-separated figure names (default: all)")
    parser.add_argument("--lang", help="comma-separated languages: en, zh (default: both)")
    parser.add_argument("--theme", help="comma-separated themes: light, dark (default: both)")
    parser.add_argument("--workdir", help="folder for the HTML pages and the browser profile")
    parser.add_argument("--out", help="folder for the PNG files (default: docs/assets)")
    parser.add_argument("--html-only", action="store_true", help="write the pages, no PNG")
    parser.add_argument("--keep-html", action="store_true", help="keep the temporary folder")
    parser.add_argument("--list", action="store_true", help="list the figures and exit")
    args = parser.parse_args(argv)
    if args.list:
        for figure in FIGURES:
            print(figure.name, ",".join(figure.languages))
        return 0
    try:
        return build(args)
    except (BuildError, subprocess.SubprocessError, OSError, KeyError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
