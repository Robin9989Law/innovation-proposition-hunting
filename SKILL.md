---
name: innovation-proposition-hunting
description: >-
  Use when finding a tight topic ecosystem from abstracts only, within ten
  neighbor switches, then pointing straight at its core and writing the open
  proposition. If the kernel is loose or the walk does not converge, switch
  neighbors. Do not read full texts. Do not collide an unfinished personal
  claim against the papers.
---

# 创新命题狩猎

不要拿还没想清楚的观点去和近邻对撞。

最近的那一篇只是跳板。它在不在核心里不重要。近三年只限制最多看多少篇。全程只看题目和摘要，不必读全文。用它找到一个紧密的主题生态，再沿最短的路直指主题核心，从核心的摘要里写下开放命题。这一句是创新突破的思路，也是有攻关价值的地方。

人看 [docs/给人看.md](docs/给人看.md)。程序是 `scripts/hunt.py`。

## 四件要核对的事

1. 近邻是不是真的近。题目和摘要里对象、动作都出现，才拿出来给读者看，并写明碰上的是哪两个叫法。读者写「是最近的」或「不是最近的」。程序不替读者判近。
2. 能不能通过这篇近邻找到圈子。只看它直接前作和直接后续，篇数受近三年限制。圈里每一篇都要直接连着它。找不到，就换近邻。
3. 紧密程度准不准。反复去掉连得少的论文，留下最密的那一团。每篇至少连着两篇才算圈子。两篇只互相引用、一条线、一篇在中间而旁边彼此不相连、单独一篇，紧密程度都不够，丢掉。先碰到的松团，不能压过更密的一团。核心是这一团里被引最多的那篇，被引次数写出来。
4. 怎么用有限步进入核心。从这一团里先碰到的那篇，沿最短的路走到核心。步数不超过团里篇数减一，不往外扩。走不到，就换近邻。换近邻最多 10 次。

路上每一步只看题目和摘要，读者写「算这个圈子」或「不算这个圈子」。开放命题由读者按核心的摘要来写。不必读全文。换满 10 次，或近邻用完了还是指不到，读者才写「没有价值」或「已经被攻克」。不搜前作的前作，也不再搜词。

## 命令

```bash
python3 <技能目录>/scripts/hunt.py init --root . --object "方向里的对象" --action "方向里的动作"
python3 <技能目录>/scripts/hunt.py add --root . --id W1 --year 2026 --title "题目" --abstract "摘要" --references W0 --cited-by W2
python3 <技能目录>/scripts/hunt.py next --root .
python3 <技能目录>/scripts/hunt.py decide --root . --id W1 --words "是最近的"
python3 <技能目录>/scripts/hunt.py topic --root . --id W2 --words "算这个圈子"
python3 <技能目录>/scripts/hunt.py open --root . --text "悬而未决的那一句"
```

近三年按 `--this-year` 往前数三年，默认是今年，只用来封住篇数。换近邻最多 10 次。问句不算。
