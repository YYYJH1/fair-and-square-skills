<p align="center"><b>English</b> · <a href="install_zh.md">简体中文</a></p>

# Install

## Claude Code

In a Claude Code session:

```
/plugin marketplace add YYYJH1/fair-and-square-skills
/plugin install fair-and-square@fair-and-square
```

From a terminal:

```
claude plugin marketplace add YYYJH1/fair-and-square-skills
claude plugin install fair-and-square@fair-and-square
```

Recent versions of Claude Code can also add the marketplace and install in one step: `claude plugin install fair-and-square --marketplace YYYJH1/fair-and-square-skills`.

The name after `@` is the marketplace name, which is not the repository name. Run `/reload-plugins` or restart Claude Code afterwards. The skills then appear as `/fair-and-square:<skill>`. To update later, run `claude plugin update fair-and-square@fair-and-square`.

## Without the plugin

Each skill folder is self-contained. Copy `plugin/skills/<name>/` to `~/.claude/skills/<name>/` for all projects, or to `.claude/skills/<name>/` for one project, then reload skills or restart Claude Code.

## Codex

Copy or symlink `plugin/skills/<name>/` into `$HOME/.agents/skills/` for all projects, or into `.agents/skills/` inside a repository for that repository only.

The scripts need Python 3.9 or later and nothing else.
