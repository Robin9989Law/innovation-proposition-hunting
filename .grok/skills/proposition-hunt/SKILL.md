---
name: proposition-hunt
description: >-
  Walk from the nearest neighbor into the tightest recent citation group,
  stop at the most-cited hub, and have the reader write the gap seen in the
  abstract. Use for innovation-proposition hunting. Abstracts only. Do not
  collide an unfinished claim, and do not write the reader's verdict.
when-to-use: >-
  命题狩猎, 最近近邻, 跳板, 紧密圈子, 汇合点, 开放命题, 没有悬而未决
argument-hint: "[课题目录] [对象] [动作]"
user-invocable: true
metadata:
  short-description: 用最近近邻走进最密的一团，按汇合点摘要写下缝
---

# 命题狩猎

这个技能只交给名叫「命题狩猎」的那一个 bot。别的 bot 不要启用。

不要拿还没想清楚的观点去和近邻对撞。最近的那一篇只是跳板。这一轮只看近三年的直接邻居。全程只看题目和摘要。全文不进这一轮。

## 程序说了算

仓库用 `cursor/fast-neighbor-8b2e`。不要用 `main`，那上面是旧流程。

```bash
git clone -b cursor/fast-neighbor-8b2e https://github.com/Robin9989Law/innovation-proposition-hunting.git
cd innovation-proposition-hunting
python3 -B -m unittest discover -s tests -q
```

测试没通过、没有 shell、或克隆失败，就停下来告诉读者。不要自己把圈子算出来。

每个课题一个目录。状态只放在该目录的 `neighbor_hunt.json`。只运行：

```bash
python3 scripts/hunt.py
```

每做完一步都运行 `next`，把输出原样给读者，并附上这一步实际运行的命令。不要另写一份结论盖过它。

## 每一步

1. 还没有名单时，先问清对象叫法和动作叫法，再 `init --root <课题目录> --object "..." --action "..."`。
2. 论文由读者给出。候选近邻按读者觉得的远近顺序 `add`。用来收圈的前作和后续加 `--role ring`。三年前的圈内邻居只写年份。
3. 程序要哪句原话，就等读者自己写，再原句传给 `decide`、`topic`、`core`、`fate` 或 `open`。
4. 程序说内核不紧密、不收敛、看不见缝、或换近邻，就按它给的编号继续。不要自己另找一篇，不要搜前作的前作，也不要为了把圈子补圆去搜词。
5. 到了汇合点，请读者看程序印出的题目和摘要，自己写缝。读者写「没有悬而未决」，就按程序换近邻。
6. 读者说要拿去攻，才只读那一篇全文。全文不写进名单。

规则的细目在仓库根目录的 `SKILL.md`。程序和它不一致时，以程序为准。

## 读者自己写

这些整句只能由读者写。不要代写，也不要把含糊话收成肯定句：

- 「是最近的」「不是最近的」
- 「算这个圈子」「不算这个圈子」
- 「是核心」
- 「没有价值」「已经被攻克」
- 摘要里看见的缝

程序拒绝「不一定」「未必」「不太算」「不是没有价值」和问句时，请读者重写。

不要发邮件，不要发帖，不要改这个仓库。
