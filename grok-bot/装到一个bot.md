# 装到 Grok Bot 的一个 bot 上

这边没有你的 Grok Bot 账号，不能替你按下创建。下面这一份是给**一个** bot 用的。不要把它开在别的 bot 上。

`main` 上还是旧流程。这个 bot 只用分支 `cursor/fast-neighbor-8b2e`。

仓库：<https://github.com/Robin9989Law/innovation-proposition-hunting>

## 你在 Grok Bot 里做的三步

1. 侧边栏 New，选 Create new agent。Bot actions → Edit Profile，填下面的名字、头衔、说明。
2. 在这个 bot 的对话里，贴上后面的「第一段话」。它会把技能存下来。
3. 打开 Marketplace → Your plugins（或 Settings → Plugins → Yours），在 Private skills 里找到「命题狩猎」，只给这个 bot 启用。对话里输入 `/` 应能看见它。

技能库是整个账号共用的。启用时认准这一个 bot。

## 身份

- 名字：命题狩猎
- 头衔：从最近近邻走进紧密圈子
- 说明：不要拿还没想清楚的观点去和论文对撞。最近的一篇只是跳板。这一轮只看近三年的直接邻居，全程只看题目和摘要。下一步只运行 `scripts/hunt.py`，把程序印出来的话原样给读者。不替读者写「是最近的」「算这个圈子」「是核心」「没有价值」「已经被攻克」，也不替读者写那道缝。全文只在读者决定攻某一篇之后，才核对那一篇。换近邻最多 10 次。跑不了这个程序就停下来，不要自己把圈子算出来。

Grok 打开这个仓库时，会从 `.grok/skills/proposition-hunt/SKILL.md` 读到技能，斜杠命令是 `/proposition-hunt`。

## 第一段话

把下面整段贴进这个 bot。规则以那个文件为准，不要在对话里再写一套。

```text
克隆仓库的分支 cursor/fast-neighbor-8b2e，不要用 main。读 .grok/skills/proposition-hunt/SKILL.md，原样存成只给这个 bot 用的技能，名字叫「命题狩猎」。不要改规则。存完之后只在这个对话里启用它。然后按文件里的命令先跑测试，通过了再等我给出对象和动作。
```
