<p align="center"><a href="how-it-works.md">English</a> · <b>简体中文</b></p>

# 工作方式

## 分工

- Agent 负责理解场景、提问、起草发给群里的消息、把群聊接龙或问卷导出整理成 JSON 输入、读回给组织者确认，并逐字转述脚本的输出。
- 脚本负责校验输入、用精确分数做运算、取整到分，并写出每个人可以核对的说明。
- 每个人用自己的数字核对属于自己的那一句。

每个技能都在任何人报数之前先把规则定下来，所以没有人能在看到数字之后再挑规则。

## 私密输入

大家报的数是私密的，所以输入也要小心处理。脚本可以从标准输入读入，这样不会产生输入文件，也可以读 `--input` 指定的文件。能用管道把输入送进去的 Agent 就这么做。Claude Code 会要求用户批准正文里同时有花括号和引号的 heredoc 命令，而这些技能的输入都是这样。所以在 Claude Code 里，技能会把输入写进会话 scratchpad 里的一个文件，再用 `--delete-input` 运行脚本。脚本读完文件就立刻删掉它，输入被拒绝时也一样。这种删除的局限写在 [对每个技能都成立的局限](THEORY_zh.md#对每个技能都成立的局限) 一节里。

## 每个脚本的规则

每个脚本都必须遵守下面几条，由 `tests/test_contract.py` 检查：

- 只用标准库，支持 Python 3.9 及以上。
- 不联网，不启动子进程，不用 `eval`、`exec`、`compile` 或 `__import__`，不写文件。唯一改动文件系统的地方是可选的 `--delete-input`：读完 `--input` 指定的文件后把它删掉。只有 `core/fsq_core.py` 在一处做这件事。
- `--help`、`--demo` 和 `--selftest` 都以状态码 0 退出，并且演示每次运行输出的字节完全相同。

## 不用 Agent，直接运行脚本

每个脚本都带一个虚构的内置示例。在本仓库的克隆里运行：

```
python3 plugin/skills/rent-split/scripts/rent_split.py --demo
python3 plugin/skills/bill-split/scripts/bill_split.py --demo
python3 plugin/skills/ride-split/scripts/ride_split.py --demo
python3 plugin/skills/group-vote/scripts/group_vote.py --demo
python3 plugin/skills/chore-split/scripts/chore_split.py --demo
python3 plugin/skills/chore-split/scripts/chore_split.py --demo-bundle
python3 plugin/skills/slot-lottery/scripts/slot_lottery.py --demo
python3 plugin/skills/gift-exchange/scripts/gift_exchange.py --demo
python3 plugin/skills/stuff-split/scripts/stuff_split.py --demo
```

文字输出默认是中文，加 `--lang en` 得到英文输出。
