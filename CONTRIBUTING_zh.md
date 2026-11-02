<p align="center"><a href="CONTRIBUTING.md">English</a> · <b>简体中文</b></p>

# 贡献指南

本文件说明怎样搭建仓库、运行检查和添加技能。

## 准备环境

在 GitHub 上 fork 这个仓库，然后克隆你的 fork：

```
git clone https://github.com/<your-user>/fair-and-square-skills.git
cd fair-and-square-skills
uv sync
```

`uv sync` 会创建 `.venv`，里面有开发工具（pytest、hypothesis、ruff 和 scipy）。技能脚本本身只需要 Python 3.9 或更新版本。

## 报告问题与提出改动

- 数字有误、脚本崩溃，或者 `SKILL.md` 里有一句话会误导人时，请开一个 issue。写明命令、输入和输出。请使用虚构的名字和金额，因为真实的报价、排序或选票不得出现在公开的 issue 里。
- 从你的 fork 的一个分支，向 `main` 提一个 pull request。说明改了什么、为什么改，并且只涉及一个主题。CI 必须通过。
- 改动脚本打印的内容时，需要更新存档的输出，见“运行检查”。请在 pull request 里说明哪些输出变了、为什么变。
- 新技能从一个 issue 开始，写明它解决的情境和它用的方法。一个技能需要什么，见下面的“技能的规则”。

## 运行检查

```
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python tools/validate_plugin.py
```

CI 在 Python 3.9 到 3.13 上运行同样的四条命令。`uv run ruff format .` 会重写格式检查会拒绝的那些文件。另有一个任务，在没有安装任何包的纯 Python 3.9 上，用 `--help`、`--demo` 和 `--selftest` 运行每个技能脚本，再在 `python -I` 下运行一次。

`tests/skills/*/golden/` 里的文件保存脚本对记录示例所打印的原文。有意改动输出之后，运行 `FSQ_UPDATE_GOLDEN=1 uv run pytest -q`，读一遍它重写的每个文件的 `git diff`，并把这些文件与改动一起提交。

每项检查覆盖什么：

- `tests/test_validator.py` 在一次性的夹具目录树上测试 `tools/validate_plugin.py`。
- `tests/test_contract.py` 扫描 `plugin/skills/*/scripts/` 里的每个 `.py` 文件，并运行每个技能脚本。规则见下文。
- `tests/test_shared_behaviour.py` 用同样的方式运行全部八个脚本，并核对它们共有的行为：标准输入不是 UTF-8 时的信息、技能不认识的字段的信息、含有不成对代理项的名字的信息，拉丁文名字与中文词语之间的空格，`--lang en`，以及 `--delete-input`。
- `tests/test_skill_input_routes.py` 核对每个 SKILL.md 都写明了传入输入的两种办法，即给 Claude Code 用的带 `--delete-input` 的文件，和给其他工具用的 heredoc，并核对两条命令照写的样子都能运行，打印出同样的文字。
- `tests/test_skill_template.py` 核对八个 SKILL.md 文件遵循同一个模板：描述的形式和长度、标题、每个围栏代码块的语言标记、关于选项和退出码的句子、示例清单，以及本仓库避免使用的措辞。
- `tests/test_metadata.py` 核对关键词、链接、许可证和 Python 版本在 `pyproject.toml`、各个清单和 CI 里是否一致。
- `tests/core/` 测试共用核心。每个技能再加上自己的测试。
- `tests/test_theory.py` 核对 `docs/THEORY.md`：每个技能一节且各节部分相同、每条保证后面跟着核对它的测试、每个被点名的测试都存在、每条参考文献都带 DOI，以及正文里没有分号或破折号。
- `tools/validate_plugin.py` 核对整体结构：SKILL.md 的 frontmatter、被引用的文件、插件清单、市场条目、四处的版本号，以及共用核心和许可证的副本。

改英文文档时，请在同一次提交里同步改它的中文版，因为 `tests/test_doc_mirrors.py` 会核对两份文档是否在第一行都带有语言切换，是否有相同顺序的相同标题级别，以及是否有相同数目的代码块。

## 技能的规则

一个技能就是一个文件夹 `plugin/skills/<name>/`，里面有 `SKILL.md`、`scripts/`、`examples/` 和 `LICENSE` 的一份副本。验证器和契约测试会强制执行下面这些规则：

- SKILL.md 的 frontmatter 只使用开放的 Agent Skills 规范里的字段：`name`、`description`、`license`、`compatibility`、`metadata` 和 `allowed-tools`。只有 Claude Code 认得的字段会被拒绝，这样同一个文件在每个工具里都能加载。
- `name` 由小写字母、数字和单个连字符组成。它等于文件夹名，并且既不含 `claude` 也不含 `anthropic`。
- `description` 至多 1024 个字符，不含尖括号。
- SKILL.md 里提到的每一个 `scripts/`、`examples/` 或 `references/` 路径都存在。
- 脚本以 `python3 ${CLAUDE_SKILL_DIR}/scripts/<script>.py` 的形式调用，后面跟一句话，说明在这个变量没有被替换时，脚本就在 SKILL.md 的旁边。同一节给出传入输入的两种办法。在 Claude Code 里，Agent 用 Write 工具把输入写进一个文件，再用 `--input FILE --delete-input` 运行脚本，因为正文里有花括号和引号的 heredoc 在那里需要用户批准。对 Codex 和其他工具，这一节保留标准输入上的 heredoc。
- 脚本使用 Python 3.9 或更新版本，只用标准库。它们从不使用网络、子进程、`eval`、`exec` 或 `compile`，也从不写文件。它们对文件系统做的唯一改动在共用核心里：带 `--delete-input` 时，`read_input` 在读完 `--input` 文件之后把它删掉。`tests/test_contract.py` 只允许 `fsq_core.py` 的 `_delete_input_file` 里的这一次 `unlink` 调用，别的都不允许。输入来自标准输入或 `--input` 文件，结果写到标准输出。
- 每个脚本在 `--help`、`--demo` 和 `--selftest` 下都以 0 退出，并且演示每次运行打印的字节都相同。每个脚本在 `python -I` 下也能启动，这个模式不把脚本自己的文件夹放进 `sys.path`，所以脚本从它所在的文件夹导入 `fsq_core.py`。
- 回复里的每一个数字都来自脚本的输出。示例使用虚构的名字和金额。
- 这个技能在 `docs/THEORY.md` 里有一节，写出保证、不保证的内容和方法。一条保证只有在测试核对过之后才会写下来，测试以 `file::function` 的形式写在它旁边。

## 共用核心

几个技能都需要的代码只在 `core/` 里放一份，`core/MANIFEST.txt` 列出共用的文件。每个技能文件夹必须保持自包含，所以 `tools/sync_core.py` 把这些文件复制进每个 `plugin/skills/<name>/scripts/`。它也把仓库根目录的 `LICENSE` 复制进每个 `plugin/skills/<name>/`。在某个技能自己加一份检查、一条取整规则或一个文本辅助函数之前，先看看 `core/fsq_core.py`。两个技能都需要的函数应当放在那里，并在 `tests/core/` 里配上测试。

1. 改 `core/` 下的文件，绝不改副本。
2. 运行 `python3 tools/sync_core.py`。
3. 把核心文件和各个副本一起提交。

`python3 tools/sync_core.py --check`、验证器和 CI 在副本缺失或与源文件不同时都会失败。

## 维护者

### 发布清单

1. 要发布的那个提交上，CI 是绿的。
2. 在 `plugin/.claude-plugin/plugin.json`、`pyproject.toml`（然后运行 `uv lock`）、`core/fsq_core.py` 里的 `CORE_VERSION`（然后运行 `python3 tools/sync_core.py`）和 `docs/THEORY.md` 的 `Version:` 行里设置新的版本号。四处不一致时，验证器会失败。版本号不得出现在 `.claude-plugin/marketplace.json` 里，验证器会拒绝这样的文件，因为只有 `plugin.json` 里的版本号改变时，用户才会收到更新。
3. 在 `CHANGELOG.md` 里为这个版本加一节。
4. 在本地运行 `claude plugin validate . --strict` 和 `claude plugin validate plugin --strict`，并修掉每一条警告。CI 的运行环境里没有 Claude Code，所以 CI 不能替你运行它们。
5. 再运行一遍 `python3 tools/validate_plugin.py`、`python3 tools/sync_core.py --check` 和测试。
6. 在目录树和历史里搜索凭据和与机器相关的绝对路径。运行 `git log --format='%an <%ae> | %cn <%ce>' | sort -u`，确认没有个人邮箱地址出现。
7. 把升级版本号的那个提交打上 `vX.Y.Z` 的标签并推送标签。把 `CHANGELOG.md` 里对应的一节复制进发布说明。
