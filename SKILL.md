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

最近的那一篇只是跳板。它在不在核心里不重要。近三年只限制最多看多少篇。全程只看题目和摘要。用它找到近期直接邻居里最密的一团，再沿最短的路走到被引最多的汇合点，按摘要写下看见的缝。要拿去攻，再只核对这一篇全文。全文不进这一轮。

人看 [docs/给人看.md](docs/给人看.md)。程序是 `scripts/hunt.py`。

## 四件要核对的事

1. 近邻是不是真的近。题目和摘要里对象、动作都出现，才拿出来，并写明这只是方向碰上了。读者写「是最近的」或「不是最近的」。程序不替读者判近。对不上的篇数不少于对得上的，先补叫法，不要先写成主题没有价值。
2. 能不能通过这篇近邻找到圈子。只看它直接前作和直接后续，篇数受近三年限制。圈里每一篇都直接连着它。这是按已填引用边算出的最密一团，不是历史上的源头。没写上的边不算。找不到，就换近邻。
3. 紧密程度准不准。反复去掉连得少的论文，留下最密的那一团。每篇至少连着两篇才算。被引最多的那篇称作汇合点，被引次数写出来。读者可以改成团里另一篇。最短路没经过的团员，用编号和题目列出来，不逐篇追问。
4. 怎么用有限步进入核心。从这一团里先碰到的那篇，沿最短的路走到汇合点。步数不超过团里篇数减一，不往外扩。走不到，就换近邻。换近邻最多 10 次。已经写过「不算这个圈子」的论文，不再当下一篇近邻。

路上每一步只看题目和摘要，读者写「算这个圈子」或「不算这个圈子」。开放句是核心摘要里看见的缝。换满 10 次，或名单走不通，先写明是哪一关没过，读者再写「没有价值」或「已经被攻克」。这两句是接受走不通之后，才对主题下的判断。不搜前作的前作，也不再搜词。

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
