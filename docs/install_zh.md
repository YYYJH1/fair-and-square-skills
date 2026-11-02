<p align="center"><a href="install.md">English</a> · <b>简体中文</b></p>

# 安装

## Claude Code

在 Claude Code 会话里：

```
/plugin marketplace add YYYJH1/fair-and-square-skills
/plugin install fair-and-square@fair-and-square
```

在终端里：

```
claude plugin marketplace add YYYJH1/fair-and-square-skills
claude plugin install fair-and-square@fair-and-square
```

较新的 Claude Code 也可以一步添加市场并安装：`claude plugin install fair-and-square --marketplace YYYJH1/fair-and-square-skills`。

`@` 后面是市场名，不是仓库名。装完后运行 `/reload-plugins` 或重启 Claude Code。之后技能以 `/fair-and-square:<技能名>` 的形式出现。以后更新用 `claude plugin update fair-and-square@fair-and-square`。

## 不装插件

每个技能文件夹都是自包含的。把 `plugin/skills/<技能名>/` 拷到 `~/.claude/skills/<技能名>/`（所有项目可用）或 `.claude/skills/<技能名>/`（仅当前项目），然后重新加载技能或重启 Claude Code。

## Codex

把 `plugin/skills/<技能名>/` 拷贝或软链到 `$HOME/.agents/skills/`（所有项目可用），或某个仓库里的 `.agents/skills/`（仅该仓库可用）。

脚本只需要 Python 3.9 或更新版本，不需要别的东西。
