"""节点快筛。

状态先决定该停、等人，还是继续记账。laya 只在 --laya 时看这一页像不像空话，
不能放宽停点，也不判断这句话新不新。
"""

from __future__ import annotations

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
# 只收紧记账，不放宽停点。基线模型零样本容易说满，门槛要高。
HOLLOW_BAR = 0.85
PAGE_LIMIT = 1600
MIN_PAGE_CHARS = 80
PAGE_QUESTIONS = {
    "hollow": {
        "type": "noul",
        "instructions": "这一页是不是空话：删掉以后判断不变，或者只有套话、没有具体论文和结论？",
    },
    "off_node": {
        "type": "noul",
        "instructions": "这一页是不是跑偏了：近邻表还没写就在抽全文结论，或者题目还没定就在谈实验？",
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


def apply_screen(action: str, answers: dict[str, Any] | None) -> str:
    """laya 只能把「继续记账」收紧成「这页是空的」。"""
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


def run_laya(page: str) -> dict[str, Any]:
    """跑一次多语言模型。没装或失败时返回 reason，不抛给调用方。"""
    if len(page.strip()) < MIN_PAGE_CHARS:
        return {"ok": False, "reason": "这一页太短，没送去快筛。"}
    try:
        from laya import Router
    except ImportError:
        return {"ok": False, "reason": "没装 laya。要内容快筛就先 pip install laya。"}
    try:
        router = Router(max_loaded=1)
        result = router.predict({"page": page}, PAGE_QUESTIONS, model="multilingual")
    except Exception as error:  # 模型下载或推理失败时，状态判断仍然有效
        return {"ok": False, "reason": f"laya 没跑成：{error}"}
    answers = result.get("answers") if isinstance(result, dict) else None
    if not isinstance(answers, dict):
        return {"ok": False, "reason": "laya 没有返回答案。"}
    return {"ok": True, "answers": answers}


def format_report(
    state: dict[str, Any],
    page: str,
    screen: dict[str, Any] | None,
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
    if screen is None:
        lines.append("还没看这一页写得空不空。要看的话，命令加上 --laya。")
    elif not screen.get("ok"):
        lines.append(f"内容快筛没跑成。{screen.get('reason', '')}")
    else:
        hollow = _score(screen.get("answers"), "hollow")
        off_node = _score(screen.get("answers"), "off_node")
        lines.append(
            "内容快筛用的是 laya 多语言，一次前向。"
            "它只看像不像空话，不判断新不新。"
            f"空话 {hollow if hollow is not None else '未知'}，"
            f"跑偏 {off_node if off_node is not None else '未知'}。"
        )
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
