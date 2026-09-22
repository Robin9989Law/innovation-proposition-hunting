---
name: innovation-proposition-hunting
description: >-
  Use when condensing the current hotspot circle in a research area and
  extracting the unresolved proposition at its core. Do not collide an
  unfinished personal claim against neighboring papers.
---

# 创新命题狩猎

不要拿还没想清楚的观点去和近邻对撞。那样往往没有好结果。

先凝练当前的热点圈，再找到里边悬而未决的开放命题。这一句才是创新突破的思路，也是有攻关价值的地方。

人看 [docs/给人看.md](docs/给人看.md)。程序是 `scripts/hunt.py`。

## 四步

1. 用热点的叫法筛论文。对象和动作只是这个热点怎么被称呼，不是你要证明的句子。题目和摘要里两处都出现，才拿出来。
2. 读者写「是当前热点」或「不是当前热点」。第一篇确认的，就是热点入口，名单不再往下扫。
3. 从这篇出发，只收近三年的直接前作和直接后续。读者写「算这个主题」的，才进入最小圈子。近三年收不成，读者写「没有价值」或「已经被攻克」。
4. 圈子里被其他论文引用最多的那篇是核心。只读它的全文，由读者写下悬而未决的命题。

## 命令

```bash
python3 <技能目录>/scripts/hunt.py init --root . --object "热点里的对象" --action "热点里的动作"
python3 <技能目录>/scripts/hunt.py add --root . --id W1 --year 2026 --title "题目" --abstract "摘要" --references W0 --cited-by W2
python3 <技能目录>/scripts/hunt.py next --root .
python3 <技能目录>/scripts/hunt.py decide --root . --id W1 --words "是当前热点"
python3 <技能目录>/scripts/hunt.py topic --root . --id W2 --words "算这个主题"
python3 <技能目录>/scripts/hunt.py core --root . --words "是核心"
python3 <技能目录>/scripts/hunt.py open --root . --text "悬而未决的那一句"
```

近三年按 `--this-year` 往前数三年，默认是今年。问句不算确认。程序不代写开放命题。
