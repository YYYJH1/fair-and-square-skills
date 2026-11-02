<p align="center"><b>English</b> · <a href="CHANGELOG_zh.md">简体中文</a></p>

# Changelog

All notable changes to this project are recorded in this file. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-11-02

### Fixed

- **rent-split.** SKILL.md called `spliddit` the default rule, but `rules.negative_rent` is required. It is now described as the recommended rule.
- **bill-split and ride-split.** The descriptions said that a group order or a shared ride is checked so that nobody pays more than alone. The scripts compare with ordering or riding alone and name anyone who would pay more, and the descriptions now say so.
- **Reproduce.** The command in the Reproduce section of every script repeats the options of the run (`--demo` or `--input -`, the output format, `--audit`, `--all-rules`, `--remove`, `--source` and `--lang`) and starts with `scripts/`.
- **Output wording.** chore-split says "in the single week" when there is one week. ride-split writes "stretch by stretch (Shapley)" in lower case inside a sentence, and in Chinese it says when only one rider is left on a stretch.
- **SKILL.md.** Each guarantee and limit is stated once, under Guarantees and limits. stuff-split names its rules by method, group-vote counts the seven rules of `--all-rules`, and a wrong section pointer in bill-split is fixed.
- **THEORY.** The caption of the gift circle says why the English figure draws number 2, the notes on the references keep only why each work is cited, and the Chinese version translates the citation notes.

### Changed

- CI runs on Python 3.14 as well.

## [0.2.0] - 2026-11-02

First public release. It ships eight skills as a Claude Code plugin named `fair-and-square`, and as plain skill folders for Codex and other tools.

### Added

- **rent-split.** Envy-free rent division from private bids, exact to the cent. The rooms go to the people so that the winning bids add up to the most, and among envy-free splits the rents make the worst-off person as well off as possible. Three rules for negative rents (`spliddit`, `allow`, `forbid`). Bids that do not add up to the total rent are shifted and never scaled. A commitment code (`--commit` and `--verify-commit`) lets the organizer go first. An audit (`--audit`) compares a split the group already uses with the rule.
- **bill-split.** Shared bills item by item, with fees, discounts and several payers, and takeaway group orders with packaging fees, delivery fees, tiered coupons shared by Shapley value or in proportion to dish prices, and flat coupons. A group order is compared with ordering alone, and the output names anyone who would pay more. Cents are rounded by the largest remainder rule, with the leftover cent rotating from bill to bill. Balances are settled with the fewest transfers, which is exact for up to 16 people with a balance. An audit compares the split a group uses now.
- **ride-split.** Taxi and carpool fares by the Shapley value of the airport game, from meter readings or from each rider's app estimate. General mode takes the price of every group of riders or a distance matrix with a tariff. Every split gets a core check that lists the groups paying more than riding alone. The equal split and the split in proportion to solo fares are shown for comparison, and an audit checks a split already made.
- **group-vote.** Ranked ballots, approval ballots, the totals of a chat poll and questionnaire exports, counted by plurality, two-round runoff, instant runoff, Borda, Condorcet with Schulze, approval or Kemeny. Every tie is broken by an order of the options fixed with a public random source. The output shows the pairwise matrix and any cycle. `--remove` recounts without an option that dropped out, and `--all-rules` explains a result after the fact.
- **chore-split.** Round-robin picking from private rankings, envy-free up to one chore, with the start moving one place each week. Chores that repeat during the week count as units, and chores a person cannot do are handled with a per-pair report of where the guarantee fails. A second plan, `bundle_pay`, gives each person a fixed bundle at the smallest total cost within their caps and settles the difference with payments between housemates.
- **slot-lottery.** A lottery that anyone can recompute, from a public random source fixed in advance, with a waiting list for identical slots. For ranked slots: random serial dictatorship, probabilistic serial with a decomposition into fixed assignments, or deferred acceptance with priority tiers and several seats per slot. `--verify` recomputes a published result, and an optional commit-reveal mode lets every person contribute randomness.
- **gift-exchange.** A Secret Santa draw that first checks that a legal draw exists and names the people with too few possible receivers when none does. Any derangement or one single circle, with exclusions for couples and last year's pairs. One legal plan is drawn with equal chances from a public random source. Each person's private message names only whom they give to.
- **stuff-split.** Shared belongings divided by a rule the group picks first: `envy_free` with cash that equalizes final worth, `knaster` sealed bids with optional unequal shares, or `max_nash` with no cash, which is envy-free up to one item and Pareto efficient. With more than 2,000,000 ways to divide, `max_nash` takes turns instead and says so. Turns promise envy-freeness up to one item only.
- **All skills.** Python 3.9 or later and the standard library only. Text output in Chinese or English (`--lang`) as tables for the organizer, one private message per person, or a group-chat summary without private numbers, and `--json` for the full result. `--demo` and `--selftest` run on built-in data. `--input FILE --delete-input` reads the input from a file and deletes it. A shared core, `fsq_core.py`, holds exact money, rounding, the Shapley value, seeded orders and commitments.
- **Documentation.** `docs/THEORY.md` states for each skill what is guaranteed, which tests check it, what is not guaranteed and where the method comes from.

[0.2.1]: https://github.com/YYYJH1/fair-and-square-skills/releases/tag/v0.2.1
[0.2.0]: https://github.com/YYYJH1/fair-and-square-skills/releases/tag/v0.2.0
