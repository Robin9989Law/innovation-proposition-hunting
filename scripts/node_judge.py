"""节点快筛。

状态先决定该停、等人，还是继续记账。加上 --jev 才请求 Jev，只看这一页像不像空话。
不能放宽停点，也不判断这句话新不新。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

HUMAN_WAIT = frozenset(
    {
        "BOOT",
        "SCOPE_LOCK",
        "L1_FREEZE",
        "LAYER_DECISION",
        "N0_AUDIT",
        "DIRECTION_LOCK",
    }
)
LEGACY = frozenset(
    {
        "COMPUTE",
        "POSTCOMPUTE_CLAIM_FREEZE",
        "FINAL_VALIDITY_AUDIT",
        "FINAL_LOCK",
    }
)
PASS = {
    "BOOT": "第 1 段，定范围",
    "SCOPE_LOCK": "第 1 段，定范围",
    "PRIOR_CLAIM_DRAIN": "第 2 段，写研究卡片",
    "RECENT_FRONTIER": "第 2 段，写研究卡片",
    "LITERATURE_REGISTER": "第 2 段，写研究卡片",
    "L1_FREEZE": "第 2 段，写研究卡片",
    "L2_TRIAGE": "第 3 段，写近邻表",
    "LAYER_DECISION": "第 3 段，写近邻表",
    "K_FULLTEXT": "第 4 段，试着推翻那一句",
    "K_CLAIM_REGISTER": "第 4 段，试着推翻那一句",
    "SYNTHESIZE_COLLISION": "第 4 段，试着推翻那一句",
    "OUTPUT_CLAIM_BIND": "第 4 段，试着推翻那一句",
    "EVIDENCE_VALIDATE": "第 4 段，试着推翻那一句",
    "N0_AUDIT": "第 4 段，试着推翻那一句",
    "CLAIM_FREEZE": "第 5 段，定下那一句",
    "VALIDITY_AUDIT": "第 5 段，定下那一句",
    "INDEPENDENT_REVIEW": "第 5 段，定下那一句",
    "DIRECTION_LOCK": "第 5 段，定下那一句",
    "COMPLETE": "五段已经走完",
}
PAGE_KEYS = {
    "SCOPE_LOCK": ("scope_lock",),
    "PRIOR_CLAIM_DRAIN": ("scope_lock",),
    "RECENT_FRONTIER": ("l1_card", "scope_lock"),
    "LITERATURE_REGISTER": ("l1_card",),
    "L1_FREEZE": ("l1_card",),
    "L2_TRIAGE": ("l2_card",),
    "LAYER_DECISION": ("l2_card",),
    "K_FULLTEXT": ("l2_card",),
    "K_CLAIM_REGISTER": ("l2_card",),
    "SYNTHESIZE_COLLISION": ("hierarchy_novelty_audit",),
    "OUTPUT_CLAIM_BIND": ("hierarchy_novelty_audit",),
    "EVIDENCE_VALIDATE": ("hierarchy_novelty_audit",),
    "N0_AUDIT": ("hierarchy_novelty_audit",),
    "CLAIM_FREEZE": ("exact_statement",),
    "VALIDITY_AUDIT": ("exact_statement",),
    "INDEPENDENT_REVIEW": ("exact_statement",),
    "DIRECTION_LOCK": ("exact_statement",),
    "COMPLETE": ("exact_statement",),
}
ACTION_TEXT = {
    "wait_for_human": "下一步：停下来等你。用你自己的话回答，不要只回「继续」。",
    "keep_bookkeeping": "下一步：同一段里可以继续记账。不要写删掉也不影响判断的句子。",
    "close_as_done": "下一步：这个想法该停。停在这里就是做完，不用硬走到最后。",
    "page_is_empty": "下一步：这一页像空话。先补上能改变判断的内容，再往下走。",
    "stop_legacy": "下一步：叫它停。新课题不在这里做实验，也不在这里写论文。",
    "already_done": "下一步：题目已经收下。不要再交给这个工具。",
    "blocked": "下一步：卡住了。先补外部条件，别改结论。",
}
# 只收紧记账，不放宽停点。中文不是 Jev 最熟的语言，门槛要高。
HOLLOW_BAR = 0.85
PAGE_LIMIT = 6000
MIN_PAGE_CHARS = 80
JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-1.13.0"
OCEANS = ("红海", "蓝海", "看不清")
RESOLVES = ("大", "中", "小")
RESOLVE_FILE = "dig_resolve.json"
FAST_STATES = frozenset(
    {
        "PRIOR_CLAIM_DRAIN",
        "RECENT_FRONTIER",
        "LITERATURE_REGISTER",
        "L1_FREEZE",
    }
)
SLOW_STATES = frozenset(
    {
        "L2_TRIAGE",
        "LAYER_DECISION",
        "K_FULLTEXT",
        "K_CLAIM_REGISTER",
        "SYNTHESIZE_COLLISION",
        "OUTPUT_CLAIM_BIND",
        "EVIDENCE_VALIDATE",
        "N0_AUDIT",
        "CLAIM_FREEZE",
        "VALIDITY_AUDIT",
        "INDEPENDENT_REVIEW",
        "DIRECTION_LOCK",
    }
)
DIG_TEXT = {
    ("红海", "小"): "红海，决心小：停在这里。不写深的近邻表，也不钻进论文里找缝。",
    ("蓝海", "小"): "蓝海，决心小：只核对最像的一两篇的题目和摘要。不像就收一个小题目。不钻六问。不许换个场景把它说成新的。",
    ("看不清", "小"): "还看不清，决心小：只补最像的几篇题目和摘要，然后再判一次。不要读全文。",
    ("红海", "中"): "红海，决心中：只钻最强的那一篇。回答三问：它靠了什么自己没检查的承诺，它为什么停在这里，边界情形露出了什么。没有缝就停。不许换场景，也不许收成它没做的那一小块。",
    ("蓝海", "中"): "蓝海，决心中：近邻表三栏写完。最强的一篇答上面三问。其余的不读全文。",
    ("看不清", "中"): "还看不清，决心中：先点明最强的几篇，判成红海或蓝海，再按中档挖。",
    ("红海", "大"): "红海，决心大：近邻表要写。最强的那篇六问都要答完：没检查的承诺、它的结果边上还有什么、倒过来说断在哪、边界情形、关键一步还能走多远、它为什么停。缝必须是它自己没回答的问题。六问都闭合还没有这个问题，才允许停。不许换名、换场景、收成补集。",
    ("蓝海", "大"): "蓝海，决心大：同样把最强近邻的六问答完，确认这片空是真的，不是没看见近邻。",
    ("看不清", "大"): "还看不清，决心大：先读到能判红海或蓝海，再把六问答完。不要用看不清当作继续挖的理由。",
}
PAGE_QUESTIONS = {
    "ocean": {
        "type": "choice",
        "instructions": (
            "From titles and abstracts only, is this shore crowded or open? "
            "The text may be Chinese. This is a rough map, not a novelty verdict."
        ),
        "criteria": {
            "红海": "several close published neighbors already did the natural idea",
            "蓝海": "the natural idea is not visibly occupied by close neighbors",
            "看不清": "too few papers, or the abstracts do not say",
        },
    },
    "hollow": {
        "type": "noul",
        "instructions": (
            "The page is hollow: deleting it would not change the judgment, "
            "or it only uses stock phrases and names no specific paper or result. "
            "The page may be written in Chinese."
        ),
    },
    "off_node": {
        "type": "noul",
        "instructions": (
            "The page is off-node: it extracts full-text claims before a neighbor "
            "table exists, or it discusses running experiments before the topic is locked. "
            "The page may be written in Chinese."
        ),
    },
}


def structural_action(state: dict[str, Any]) -> str:
    active = state.get("active_state")
    if active in LEGACY:
        return "stop_legacy"
    if active == "COMPLETE":
        return "already_done"
    if active == "BLOCKED":
        return "blocked"
    if active == "N0_AUDIT" and state.get("novelty_level") in {"N0-1", "N0-2"}:
        return "close_as_done"
    if active in HUMAN_WAIT:
        return "wait_for_human"
    return "keep_bookkeeping"


def _score(answers: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(answers, dict):
        return None
    item = answers.get(key)
    if not isinstance(item, dict):
        return None
    value = item.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def parse_fast_decision(text: str) -> tuple[str, str]:
    """从用户原话里取出红海/蓝海/看不清，以及决心大/中/小。"""
    oceans = [name for name in OCEANS if name in text]
    resolves = [
        level
        for level in RESOLVES
        if f"决心{level}" in text
        or f"{level}决心" in text
        or f"决心：{level}" in text
        or f"决心:{level}" in text
    ]
    if len(oceans) != 1 or len(resolves) != 1:
        raise SystemExit(
            "离开研究卡片之前，你自己的话里要写清两件："
            "这片是红海、蓝海还是看不清，以及决心是大、中还是小。"
            "例如：这片是红海，我的决心中。"
        )
    return oceans[0], resolves[0]


def dig_instruction(ocean: str, resolve: str) -> str:
    return DIG_TEXT[(ocean, resolve)]


def write_dig_resolve(root: Path, ocean: str, resolve: str, note: str) -> None:
    payload = {"ocean": ocean, "resolve": resolve, "human_decision": note}
    path = root / RESOLVE_FILE
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def read_dig_resolve(root: Path) -> dict[str, str] | None:
    path = root / RESOLVE_FILE
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    ocean = payload.get("ocean")
    resolve = payload.get("resolve")
    if ocean not in OCEANS or resolve not in RESOLVES:
        return None
    return {"ocean": ocean, "resolve": resolve}


def apply_screen(action: str, answers: dict[str, Any] | None) -> str:
    """Jev 只能把「继续记账」收紧成「这页是空的」。"""
    if action != "keep_bookkeeping":
        return action
    hollow = _score(answers, "hollow")
    off_node = _score(answers, "off_node")
    if (hollow is not None and hollow >= HOLLOW_BAR) or (
        off_node is not None and off_node >= HOLLOW_BAR
    ):
        return "page_is_empty"
    return action


def load_page(root: Path, state: dict[str, Any]) -> str:
    artifacts = state.get("artifacts")
    if not isinstance(artifacts, dict):
        return ""
    active = state.get("active_state")
    keys = PAGE_KEYS.get(active, ())
    chunks: list[str] = []
    for key in keys:
        relative = artifacts.get(key)
        if not isinstance(relative, str):
            continue
        relative = relative.strip()
        parts = Path(relative).parts
        if not relative or relative.startswith(("/", "\\")) or ".." in parts:
            continue
        path = root / relative
        if not path.is_file():
            continue
        chunks.append(path.read_text(encoding="utf-8", errors="replace").strip())
        if sum(len(chunk) for chunk in chunks) >= PAGE_LIMIT:
            break
    return "\n\n".join(chunks)[:PAGE_LIMIT]


def jev_payload(page: str) -> dict[str, Any]:
    return {"model": JEV_MODEL, "state": page, "questions": PAGE_QUESTIONS}


def run_jev(page: str) -> dict[str, Any]:
    """请求官方 Jev。没钥匙或失败时返回 reason，不抛给调用方。"""
    if len(page.strip()) < MIN_PAGE_CHARS:
        return {"ok": False, "reason": "这一页太短，没送去快筛。"}
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        return {
            "ok": False,
            "reason": "没有 TYPESAFE_API_KEY。状态判断仍然有效。",
        }
    request = urllib.request.Request(
        JEV_URL,
        data=json.dumps(jev_payload(page), ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:180].replace(key, "[key]")
        return {"ok": False, "reason": f"Jev 返回 {error.code}。{detail}"}
    except Exception as error:
        reason = str(error).replace(key, "[key]")
        return {"ok": False, "reason": f"Jev 没连上：{reason}"}
    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        return {"ok": False, "reason": "Jev 没有返回答案。"}
    return {"ok": True, "answers": answers}


def _choice(answers: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(answers, dict):
        return None
    item = answers.get(key)
    if isinstance(item, dict) and isinstance(item.get("choice"), str):
        return item["choice"]
    return None


def format_report(
    state: dict[str, Any],
    page: str,
    screen: dict[str, Any] | None,
    resolve: dict[str, str] | None = None,
) -> str:
    action = apply_screen(structural_action(state), (screen or {}).get("answers"))
    lines: list[str] = []
    active = state.get("active_state")
    pass_name = PASS.get(active) if isinstance(active, str) else None
    if pass_name:
        lines.append(f"整段流程里，这是{pass_name}。")
    elif isinstance(active, str) and active:
        lines.append(f"现在的步骤是 {active}。")
    lines.append(ACTION_TEXT.get(action, "下一步：先停下来问人。"))
    if active in FAST_STATES:
        lines.append("这一步是快判。只看题目和摘要，写清这片是红海、蓝海，还是看不清。不要读全文，也不要钻缝。")
        lines.append("然后用你自己的话说决心：大、中或小。决心越大，后面挖缝越深。决心小，红海就停。")
    elif active in SLOW_STATES:
        if resolve:
            lines.append(dig_instruction(resolve["ocean"], resolve["resolve"]))
        else:
            lines.append("慢路线还没记下你的决心。新课题要先回到研究卡片，写红海或蓝海，再说大、中、小。")
    if screen is None:
        lines.append("还没看这一页写得空不空。要看的话，命令加上 --jev。")
    elif not screen.get("ok"):
        lines.append(f"内容快筛没跑成。{screen.get('reason', '')}")
    else:
        hollow = _score(screen.get("answers"), "hollow")
        off_node = _score(screen.get("answers"), "off_node")
        lines.append(
            "内容快筛用的是 Jev，一次请求。"
            "它看像不像空话，也给一个红海或蓝海的大致看法，不判断新不新。"
            f"空话 {hollow if hollow is not None else '未知'}，"
            f"跑偏 {off_node if off_node is not None else '未知'}。"
        )
        ocean_guess = _choice(screen.get("answers"), "ocean")
        if ocean_guess:
            lines.append(f"Jev 的大致看法是{ocean_guess}。这不算数，要你自己说了才算。")
        if (
            structural_action(state) == "wait_for_human"
            and action == "wait_for_human"
            and (
                (hollow is not None and hollow >= HOLLOW_BAR)
                or (off_node is not None and off_node >= HOLLOW_BAR)
            )
        ):
            lines.append("你看的时候注意：快筛觉得这一页像空话。")
    if page.strip() and len(page.strip()) < MIN_PAGE_CHARS and screen is None:
        lines.append("这一页很短。先把它写成能读的一页，再往下做。")
    lines.append("这个结果不能代替你点头，也不能放宽该停的地方。")
    return "\n".join(lines)
