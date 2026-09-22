---
name: innovation-proposition-hunting
description: >-
  Use when entering a tight research circle from the nearest neighbor, walking
  inward to its core, and writing down the open proposition there. Do not
  collide an unfinished personal claim against the papers.
---

# 创新命题狩猎

不要拿还没想清楚的观点去和近邻对撞。

最近的那一篇只是跳板。它在不在核心里不重要。用它走进一个紧密圈子，再沿着圈子里最短的一条路移到核心，从核心里写下开放命题。这一句是创新突破的思路，也是有攻关价值的地方。

人看 [docs/给人看.md](docs/给人看.md)。程序是 `scripts/hunt.py`。

## 快速算法

1. 对象和动作只是这个方向的叫法。题目和摘要里两处都出现，才拿出来。读者写「是最近的」或「不是最近的」。第一篇「是最近的」就是跳板，名单不再往下扫。
2. 只取跳板的直接前作和直接后续。三年前的不进圈子。只跟跳板单独连着、彼此不连的，丢掉。剩下彼此有引用的，是紧密圈子。跳板自己不必在里面。
3. 核心是圈子里被其他论文引用最多的那篇。从紧挨跳板的那篇出发，沿最短的引用路，一篇一篇走到核心。每一步读者写「算这个圈子」或「不算这个圈子」。
4. 只读核心的全文。开放命题由读者写。

近三年收不成紧密圈子，读者写「没有价值」或「已经被攻克」。不搜前作的前作，也不再搜词。

## 命令

```bash
python3 <技能目录>/scripts/hunt.py init --root . --object "方向里的对象" --action "方向里的动作"
python3 <技能目录>/scripts/hunt.py add --root . --id W1 --year 2026 --title "题目" --abstract "摘要" --references W0 --cited-by W2
python3 <技能目录>/scripts/hunt.py next --root .
python3 <技能目录>/scripts/hunt.py decide --root . --id W1 --words "是最近的"
python3 <技能目录>/scripts/hunt.py topic --root . --id W2 --words "算这个圈子"
python3 <技能目录>/scripts/hunt.py open --root . --text "悬而未决的那一句"
```

近三年按 `--this-year` 往前数三年，默认是今年。问句不算。
