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

## 快速算法

1. 对象和动作只是这个方向的叫法。题目和摘要里两处都出现，才拿出来。读者写「是最近的」或「不是最近的」。
2. 近三年只限制这一轮最多看多少篇。只在这个数量里看跳板的直接前作和直接后续。反复去掉连着不到两篇的论文。剩下的每一篇至少还连着两篇，主题生态才算在，内核才算紧密。两篇只互相引用、连成一条线、一篇在中间而旁边彼此不相连、单独一篇，都是松的。跳板自己不必在里面。
3. 内核不紧密，就换下一个近邻。走到一半散了，指不到主题核心，也换。换近邻最多 10 次。再让读者写「是最近的」或「不是最近的」。直到某个近邻旁边有紧密的主题生态，并且最短的路能指到主题核心。
4. 主题核心是这个生态里被其他论文引用最多的那篇。路上每一步只看题目和摘要，读者写「算这个圈子」或「不算这个圈子」。开放命题由读者按核心的摘要来写。不必读全文。
5. 换满 10 次，或近邻用完了还是指不到，读者才写「没有价值」或「已经被攻克」。不搜前作的前作，也不再搜词。

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
