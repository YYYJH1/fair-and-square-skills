<p align="center"><a href="README.md">English</a> · <b>简体中文</b></p>

# README 配图

`docs/assets/` 里的配图展示的是技能脚本的真实输出。`build.py` 运行脚本取得数字，为每张图、每种语言和每个主题写出一个 HTML 页面，并让无头 Chromium 以两倍分辨率给每个页面截图。

## 重新生成

```
CHROME_BIN=/path/to/chrome-headless-shell python3 tools/readme_assets/build.py
```

- Python 3.9 或更新版本，只用标准库。在 Linux 上测试过。
- `CHROME_BIN` 指向一个无头 Chromium，例如 Playwright 下载的 `chrome-headless-shell` 二进制文件。不设置时，脚本会在 `PATH` 里找 `chrome-headless-shell`、`chromium` 和 `google-chrome`。完整的 Chrome 在无头模式下，在某些机器上可能卡住，所以请使用 headless shell。
- 页面只使用系统字体：拉丁文字用 Arial（或 Liberation Sans），代码用 DejaVu Sans Mono，中文用 Noto Sans CJK SC。不从网络加载任何东西。换用其他字体会让外观略有不同。在同一台机器上，两次构建给出相同的文件。
- 浏览器把它的配置目录和临时文件放在工作文件夹里。用 `--workdir DIR` 指定一个，否则脚本会建一个临时文件夹，用完删除。

常用选项：`--only result-card,gift-ring` 只生成部分图。`--lang zh` 和 `--theme dark` 选择变体。`--out DIR` 把 PNG 文件写到别处。`--html-only` 不用浏览器，只写出页面并打印它们所在的文件夹。`--list` 列出所有图。在浏览器里打开一个页面时，可以在地址里加 `?theme=dark` 或 `?theme=light`。

## 生成了什么

| 图 | 数字的来源 | `docs/assets/` 里的文件 |
|---|---|---|
| `banner` | 无 | `banner-{light,dark}.png` |
| `result-card` | `rent_split.py --input tools/readme_assets/rent_card.<lang>.json --json --lang <lang>` | `result-card-{en,zh}-{light,dark}.png` |
| `skills` | 无，文字在 `figures.py` 里 | `skills-{en,zh}-{light,dark}.png` |
| `how-it-works` | 无 | `how-it-works-{en,zh}-{light,dark}.png` |
| `ps-timeline` | `slot_lottery.py --input <input> --json`：中文用示例 `plugin/skills/slot-lottery/examples/ps_holiday_weeks.json`，英文用 `tools/readme_assets/ps_holiday_weeks.en.json` | `ps-timeline-{en,zh}-{light,dark}.png` |
| `gift-ring` | `gift_exchange.py --input <input> --json`：中文用示例 `plugin/skills/gift-exchange/examples/six_circle.json`，英文用 `tools/readme_assets/six_circle.en.json` | `gift-ring-{en,zh}-{light,dark}.png` |

两份 README 展示 `banner`、`result-card`、`skills` 和 `how-it-works`。[docs/THEORY_zh.md](../../docs/THEORY_zh.md) 展示 `ps-timeline`（在 `slot-lottery` 一节）和 `gift-ring`（在 `gift-exchange` 一节）。

下面任何一项检查不通过时，构建都会报错退出：

- 卡片上的房租加起来等于总额，每个报价都等于房租加好处，英文输入和中文输入给出同样的数字。
- 在吃的日程里，一个人花在某个时段上的时间，等于脚本的概率表里这个时段的概率。
- 圈沿着脚本给出的分配走，不使用任何不被允许的方向。
- 没有一个 PNG 大于 400 KB。

## 文件

| 文件 | 内容 |
|---|---|
| `build.py` | 运行脚本，写出页面，调用浏览器，检查大小。 |
| `figures.py` | 每张图的 HTML，含英文和中文文字。 |
| `style.css` | 颜色定义成 CSS 变量，由 `<html>` 上的 `data-theme`（light、dark）切换，另有字体。一个主色（青绿），一个强调色（琥珀）和若干灰色。 |
| `rent_card.en.json`、`rent_card.zh.json` | 结果卡片的固定输入：同样的三份私下报价，配上英文或中文的名字和房间。 |
| `ps_holiday_weeks.en.json`、`six_circle.en.json` | `slot-lottery` 和 `gift-exchange` 的示例，名字和时段换成英文，供英文配图使用。 |

## 英文配图的输入

`slot-lottery` 和 `gift-exchange` 的中文配图运行这两个技能自带的示例。英文配图运行本文件夹里的 `ps_holiday_weeks.en.json` 和 `six_circle.en.json`，它们是同样的输入，只是名字换成了英文。
