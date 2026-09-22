---
name: innovation-proposition-hunting
description: >-
  Use when you need the most dangerous near neighbor of a research claim,
  then the smallest recent circle that still contains the topic, then the
  unresolved proposition at its core. Match object and action. The reader
  confirms whether it is the same thing.
---

# 创新命题狩猎

做四步，然后停。

1. 找到最危险近邻。最危险，是指这篇如果成立，你要写的那句话就被占住，或者能从它推出来。
2. 从这篇出发，收包括这个主题的最小圈子。只收近三年的直接前作和直接后续。近三年收不成，就由读者写「没有价值」或「已经被攻克」。
3. 在这个圈子里往核心走。核心是圈子里被其他论文引用最多的那篇。读者可以改成圈子里的另一篇。
4. 读核心的全文，由读者写下悬而未决的命题。

人看 [docs/给人看.md](docs/给人看.md)。程序是 `scripts/hunt.py`。

## 规则

- 找近邻时只看题目和摘要。对象和动作两处都出现才拿出来问。同义词只用 `add-name` 里已经写明的叫法。
- 「是同一个东西」才能当最危险近邻。「不是同一个东西」就换一篇。问句不算。程序不定这件事。
- 第一篇危险近邻出现，就停止往下扫名单。
- 最小圈子不走出这篇的参考文献和被引。不搜前作的前作，也不再搜词。三年前的文献不进圈子。
- 圈子里的近三年论文，读者写「算这个主题」或「不算这个主题」。
- 全文只读核心那一篇。悬而未决的那一句由读者写。程序不代写。

## 命令

```bash
python3 <技能目录>/scripts/hunt.py init --root . --object "对象" --action "动作"
python3 <技能目录>/scripts/hunt.py add --root . --id W1 --year 2026 --title "题目" --abstract "摘要" --references W0 --cited-by W2
python3 <技能目录>/scripts/hunt.py next --root .
python3 <技能目录>/scripts/hunt.py decide --root . --id W1 --same "是同一个东西" --danger 占住
python3 <技能目录>/scripts/hunt.py topic --root . --id W2 --words "算这个主题"
python3 <技能目录>/scripts/hunt.py fate --root . --words "已经被攻克"
python3 <技能目录>/scripts/hunt.py core --root . --words "是核心"
python3 <技能目录>/scripts/hunt.py open --root . --text "悬而未决的那一句"
```

`--danger` 只在「是同一个东西」时写，取值是 `占住`、`能推出来`、`只是像`。近三年按 `--this-year` 往前数三年，默认是今年。
