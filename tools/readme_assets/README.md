<p align="center"><b>English</b> · <a href="README_zh.md">简体中文</a></p>

# Documentation figures

The figures in `docs/assets/` show real output of the skill scripts. `build.py` runs the scripts for the numbers, writes one HTML page per figure, language and theme, and lets headless Chromium screenshot each page at twice the resolution.

## Rebuild

```
CHROME_BIN=/path/to/chrome-headless-shell python3 tools/readme_assets/build.py
```

- Python 3.9 or later and the standard library. Tested on Linux.
- `CHROME_BIN` names a headless Chromium, for example the `chrome-headless-shell` binary that Playwright downloads. Without it the script looks for `chrome-headless-shell`, `chromium` and `google-chrome` on `PATH`. The full Chrome in headless mode can hang on some machines, so use the headless shell.
- The pages use system fonts only: Arial (or Liberation Sans) for Latin text, DejaVu Sans Mono for code and Noto Sans CJK SC for Chinese. Nothing is loaded from the network. Other fonts change the look slightly. On one machine two builds give identical files.
- The browser keeps its profile and temporary files in the work folder. Give one with `--workdir DIR`, otherwise the script makes a temporary folder and removes it.

Useful options: `--only result-card,gift-ring` builds some figures, `--lang zh` and `--theme dark` pick variants, `--out DIR` writes the PNG files somewhere else, `--html-only` writes the pages without a browser and prints their folder, `--list` lists the figures. A page opened in a browser takes `?theme=dark` or `?theme=light` in the address.

## What is built

| Figure | Numbers come from | Files in `docs/assets/` |
|---|---|---|
| `banner` | none | `banner-{light,dark}.png` |
| `result-card` | `rent_split.py --input tools/readme_assets/rent_card.<lang>.json --json --lang <lang>` | `result-card-{en,zh}-{light,dark}.png` |
| `skills` | none, the text is in `figures.py` | `skills-{en,zh}-{light,dark}.png` |
| `how-it-works` | none | `how-it-works-{en,zh}-{light,dark}.png` |
| `ps-timeline` | `slot_lottery.py --input <input> --json`: in Chinese the example `plugin/skills/slot-lottery/examples/ps_holiday_weeks.json`, in English `tools/readme_assets/ps_holiday_weeks.en.json` | `ps-timeline-{en,zh}-{light,dark}.png` |
| `gift-ring` | `gift_exchange.py --input <input> --json`: in Chinese the example `plugin/skills/gift-exchange/examples/six_circle.json`, in English `tools/readme_assets/six_circle.en.json` | `gift-ring-{en,zh}-{light,dark}.png` |

The two READMEs show `banner`, `result-card`, `skills` and `how-it-works`. [docs/THEORY.md](../../docs/THEORY.md) shows `ps-timeline` in the `slot-lottery` section and `gift-ring` in the `gift-exchange` section.

The build exits with an error when one of these checks fails:

- The rents of the card add up to the total, every bid equals rent plus gain, and the English and the Chinese input give the same numbers.
- In the eating schedule, the time a person spends on a slot equals the chance of that slot in the table of the script.
- The circle follows the assignments of the script and uses no direction that is not allowed.
- No PNG is larger than 400 KB.

## Files

| File | Content |
|---|---|
| `build.py` | Runs the scripts, writes the pages, calls the browser, checks sizes. |
| `figures.py` | The HTML of every figure, with the English and the Chinese text. |
| `style.css` | Colors as CSS variables, switched by `data-theme` (light, dark) on `<html>`, and the fonts. One primary color (teal), one accent (amber) and grays. |
| `rent_card.en.json`, `rent_card.zh.json` | The fixed input of the result card: the same three private bids, with English or Chinese names and rooms. |
| `ps_holiday_weeks.en.json`, `six_circle.en.json` | The examples of `slot-lottery` and `gift-exchange` with English names and slots, for the English figures. |
