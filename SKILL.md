---
name: innovation-proposition-hunting
description: >-
  Use when entering the tightest recent citation group around the nearest
  neighbor, walking to its most-cited paper, and writing the gap seen in that
  paper's abstract. Switch neighbors, at most ten times, when the group is
  loose, falls apart, or shows no gap. Abstracts only. Do not collide an
  unfinished personal claim against the papers.
---

# 创新命题狩猎

不要拿还没想清楚的观点去和近邻对撞。

最近的那一篇只是跳板。它在不在核心里不重要。这一轮只看近三年的直接邻居。全程只看题目和摘要。用它找到最密的一团，再沿最短的路走到被引最多的汇合点，按摘要写下看见的缝。要拿去攻，再只核对这一篇全文。全文不进这一轮。

人看 [docs/给人看.md](docs/给人看.md)。程序是 `scripts/hunt.py`。

## 两张名单

- 候选近邻：`add` 默认就是。按读者觉得的远近顺序加。只有它们会被问「是最近的」。
- 圈内邻居：`add --role ring`。为了收圈补进来的前作和后续，不会被当成下一篇近邻。三年前的圈内邻居只写年份。

跳板的 `--references` 和 `--cited-by` 只写读者要算进来的直接邻居。

## 四件要核对的事

1. 近邻是不是真的近。题目和摘要里对象、动作都出现，才拿出来，并写明这只是方向碰上了。读者写「是最近的」或「不是最近的」。程序不替读者判近。对不上的篇数不少于对得上的，先补叫法，不要先写成主题没有价值。
2. 能不能通过这篇近邻找到圈子。只看它近三年的直接前作和直接后续。圈里每一篇都直接连着它。三年前的不进这一团，所以这不是历史上的源头。只按已填的引用边计算，没写上的边不算。找不到，就换近邻。
3. 紧密程度准不准。反复去掉连得少的论文，留下最密的那一团。每篇至少连着两篇才算。被引最多的那篇称作汇合点，被引次数写出来，被引一样多时更早的优先。读者可以改成团里另一篇。最短路没经过的团员，用编号和题目列出来，不逐篇追问。
4. 怎么用有限步进入核心。团是连通的，最短路步数一定不超过团里篇数减一，不往外扩。不收敛只会是读者否掉路上的论文以后，这一团散了。这时换近邻，不悄悄换到另一团。换近邻最多 10 次。

## 读者原话

整句只认这几句，句末标点可以有：

- 「是最近的」「不是最近的」
- 「算这个圈子」「不算这个圈子」
- 「是核心」
- 「没有价值」「已经被攻克」

「不一定是最近的」「未必算这个圈子」「不是没有价值」这类都要重写。问句不算。

圈子里的判断记在跳板下面。换了跳板，前一篇跳板下写的「算」或「不算」不带过来。写过「不算这个圈子」的论文，不再当下一篇近邻。那一句也记在跳板和汇合点下面。

## 结束

到了汇合点，读者按摘要写看见的缝。看不见，就写「没有悬而未决」，程序换下一篇近邻。换满 10 次，或名单走不通，先写明是哪一关没过，读者再写「没有价值」或「已经被攻克」。这两句是接受走不通之后，才对主题下的判断。不搜前作的前作，也不再搜词。

## 命令

```bash
python3 <技能目录>/scripts/hunt.py init --root . --object "方向里的对象" --action "方向里的动作"
python3 <技能目录>/scripts/hunt.py add --root . --id W1 --year 2026 --title "题目" --abstract "摘要" --references W0 --cited-by W2
python3 <技能目录>/scripts/hunt.py add --root . --id W2 --year 2025 --title "题目" --abstract "摘要" --references W1 --role ring
python3 <技能目录>/scripts/hunt.py add --root . --id W0 --year 2018 --role ring
python3 <技能目录>/scripts/hunt.py next --root .
python3 <技能目录>/scripts/hunt.py decide --root . --id W1 --words "是最近的"
python3 <技能目录>/scripts/hunt.py topic --root . --id W2 --words "算这个圈子"
python3 <技能目录>/scripts/hunt.py core --root . --words "是核心"
python3 <技能目录>/scripts/hunt.py open --root . --text "摘要里看见的缝"
```

近三年按 `--this-year` 往前数三年，默认是今年。
