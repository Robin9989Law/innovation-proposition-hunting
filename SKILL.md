---
name: innovation-proposition-hunting
description: >-
  Use when you need the fastest way to find the most dangerous near neighbor
  of a research claim. Match the object and the action, then the reader
  confirms whether it is the same thing. Stop after one bibliographic ring.
---

# 创新命题狩猎

现在只做一件事：用最快的速度找到最危险的近邻。

最危险，是指这篇如果成立，你要写的那句话就被占住，或者能从它推出来。不是引用最多，也不是期刊最好。

人要看的说明在 [docs/给人看.md](docs/给人看.md)。程序是 `scripts/hunt.py`。

## 规则

1. 把要写的那句话拆成对象和动作。同义词只用已经写明的叫法，用 `add-name` 记下来。不要临时加词。
2. 论文按你觉得最可疑的顺序 `add`。每篇只要编号、题目、摘要、参考文献编号、被引编号。不读全文。
3. 运行 `next`。对象和动作两处都出现，才拿出来问。只中一处的丢掉。不要拿整句去对整句。
4. 是不是同一个东西，只认读者的原话。`是同一个东西` 才能继续。`不是同一个东西` 就丢掉。问句不算。程序不能自己定。
5. 确认是同一个东西之后，只看摘要里那一句，写成 `占住`、`能推出来` 或 `只是像`。前两个才是锚点。`只是像` 就看下一篇。
6. 第一篇锚点出现，就停止往下扫名单。
7. 然后只看这篇的参考文献和被引，直接前作和直接后续。不搜前作的前作，也不再搜词。圈上每篇仍要两处对上，仍要读者确认。
8. 圈看完判断不变，就停。圈上出现更危险的一篇（`占住` 高于 `能推出来`），它变成新锚点，圈只重画一次。
9. 圈上的编号还没进名单，就补那一篇的题目和摘要。不要改去搜关键词。
10. 名单走完还没有锚点，结果是看不清。不要把领域扫一遍当成蓝海。

## 命令

在课题目录里：

```bash
python3 <技能目录>/scripts/hunt.py init --root . --object "对象叫法" --action "动作叫法"
python3 <技能目录>/scripts/hunt.py add-name --root . --slot object --name "已经写明的同义叫法"
python3 <技能目录>/scripts/hunt.py add --root . --id W1 --title "题目" --abstract "摘要" --references W0 --cited-by W2
python3 <技能目录>/scripts/hunt.py next --root .
python3 <技能目录>/scripts/hunt.py decide --root . --id W1 --same "是同一个东西" --danger 占住
python3 <技能目录>/scripts/hunt.py decide --root . --id W1 --same "不是同一个东西"
```

`--danger` 只在「是同一个东西」时写，取值是 `占住`、`能推出来`、`只是像`。

判断写在课题目录的 `neighbor_hunt.json`。程序不写「是同一个东西」。
