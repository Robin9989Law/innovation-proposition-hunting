#!/usr/bin/env python3
"""用最近近邻当跳板，找到紧密的主题生态，再直指主题核心。

四件事要能核对：近邻是不是真的近，能不能通过它找到圈子，紧密程度有没有数对，进核心是不是有限步。
近三年只限制最多看多少篇。最密的那一团里，每篇至少连着两篇。
内核不紧密，或者有限步进不到核心，就换近邻，最多换 10 次。
全程只看题目和摘要，不必读全文。
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

STATE_NAME = "neighbor_hunt.json"
FATES = ("没有价值", "已经被攻克")
RECENT_SPAN = 2
SWITCH_LIMIT = 10


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(folded.split())


def state_path(root: Path) -> Path:
    return root / STATE_NAME


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        raise SystemExit(f"还没有名单。先在这个目录运行 init：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("neighbor_hunt.json 坏了。")
    data.setdefault("topic", {})
    data.setdefault("fate", None)
    data.setdefault("core_id", None)
    data.setdefault("open_problem", None)
    data.setdefault("this_year", date.today().year)
    return data


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def blank_state(object_name: str, action_name: str, this_year: int) -> dict[str, Any]:
    return {
        "object_names": [require_name(object_name)],
        "action_names": [require_name(action_name)],
        "this_year": this_year,
        "papers": [],
        "decisions": {},
        "topic": {},
        "fate": None,
        "core_id": None,
        "open_problem": None,
    }


def require_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned or not normalize(cleaned):
        raise SystemExit("对象或动作要写成具体的叫法，不能是空的。")
    return cleaned


def split_ids(raw: str | None) -> list[str]:
    if raw is None or not raw.strip():
        return []
    parts = [part.strip() for part in raw.split(",")]
    if any(not part for part in parts):
        raise SystemExit("编号用逗号分开，不要留空段。")
    if any(any(char.isspace() for char in part) for part in parts):
        raise SystemExit("一个编号里不要有空格。")
    if len(parts) != len(set(parts)):
        raise SystemExit("同一篇里的编号不要重复。")
    return parts


def require_id(paper_id: str) -> str:
    cleaned = paper_id.strip()
    if not cleaned or any(char.isspace() for char in cleaned) or "," in cleaned:
        raise SystemExit("论文编号不能为空，也不能带空格或逗号。")
    return cleaned


def require_year(year: int) -> int:
    if year < 1800 or year > 2100:
        raise SystemExit("年份要写成四位数字。")
    return year


def paper_by_id(state: dict[str, Any], paper_id: str) -> dict[str, Any] | None:
    for paper in state["papers"]:
        if paper["id"] == paper_id:
            return paper
    return None


def recent_cutoff(state: dict[str, Any]) -> int:
    return int(state["this_year"]) - RECENT_SPAN


def is_recent(state: dict[str, Any], paper: dict[str, Any]) -> bool:
    return int(paper["year"]) >= recent_cutoff(state)


def window_label(state: dict[str, Any]) -> str:
    start = recent_cutoff(state)
    return f"{start}–{state['this_year']}"


def slot_hits(state: dict[str, Any], paper: dict[str, Any]) -> tuple[list[str], list[str]]:
    text = normalize(f"{paper.get('title', '')}\n{paper.get('abstract', '')}")
    if not text:
        return [], []
    objects = [name for name in state["object_names"] if normalize(name) in text]
    actions = [name for name in state["action_names"] if normalize(name) in text]
    return objects, actions


def slot_hit(state: dict[str, Any], paper: dict[str, Any]) -> bool:
    objects, actions = slot_hits(state, paper)
    return bool(objects) and bool(actions)


def _near_prompt(state: dict[str, Any], paper: dict[str, Any]) -> str:
    objects, actions = slot_hits(state, paper)
    return (
        f"对象「{'、'.join(objects)}」和动作「{'、'.join(actions)}」都在题目或摘要里。"
        "这只说明方向碰上了。近不近要你写死。"
    )


def reject_question(text: str) -> None:
    if any(mark in text for mark in ("吗", "？", "?")):
        raise SystemExit("不要写成问句。把判断写死。")


def parse_hotspot(text: str) -> str:
    reject_question(text)
    if "是不是最近的" in text:
        raise SystemExit("是不是最近的，要写死。是最近的，或不是最近的。")
    rejected = "不是最近的" in text
    confirmed = "是最近的" in text.replace("不是最近的", "")
    if rejected and confirmed:
        raise SystemExit("是不是最近的，要写死。是最近的，或不是最近的。")
    if rejected:
        return "no"
    if confirmed:
        return "yes"
    raise SystemExit("这篇是不是最近的，要你自己写。是最近的，或不是最近的。")


def parse_topic(text: str) -> str:
    reject_question(text)
    rejected = "不算这个圈子" in text
    confirmed = "算这个圈子" in text.replace("不算这个圈子", "")
    if rejected and confirmed:
        raise SystemExit("算不算这个圈子，要写死。算这个圈子，或不算这个圈子。")
    if rejected:
        return "no"
    if confirmed:
        return "yes"
    raise SystemExit("这一篇算不算这个圈子，要你自己写。算这个圈子，或不算这个圈子。")


def parse_fate(text: str) -> str:
    reject_question(text)
    hits = [name for name in FATES if name in text]
    if len(hits) != 1:
        raise SystemExit("走不到紧密核心。你写没有价值，或已经被攻克。两个都写，或都不写，都不算。")
    return hits[0]


def is_hotspot(decision: dict[str, Any]) -> bool:
    return decision.get("hotspot") == "yes"


def ring_ids(paper: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for key in ("references", "cited_by"):
        for paper_id in paper.get(key) or []:
            if paper_id == paper["id"] or paper_id in seen:
                continue
            seen.append(paper_id)
    return seen


def neighbor_links(state: dict[str, Any], paper_ids: list[str]) -> dict[str, set[str]]:
    nodes = set(paper_ids)
    links = {paper_id: set() for paper_id in paper_ids}
    for paper_id in paper_ids:
        paper = paper_by_id(state, paper_id)
        if paper is None:
            continue
        for other in list(paper["references"]) + list(paper["cited_by"]):
            if other in nodes and other != paper_id:
                links[paper_id].add(other)
                links[other].add(paper_id)
    return links


def _min_degree(links: dict[str, set[str]], nodes: set[str]) -> int:
    if not nodes:
        return 0
    return min(len(links[paper_id] & (nodes - {paper_id})) for paper_id in nodes)


def _peel(links: dict[str, set[str]], nodes: set[str], minimum: int) -> set[str]:
    remaining = set(nodes)
    while True:
        loose = [
            paper_id
            for paper_id in remaining
            if len(links[paper_id] & (remaining - {paper_id})) < minimum
        ]
        if not loose:
            return remaining
        remaining.difference_update(loose)


def _components(
    links: dict[str, set[str]], nodes: set[str], order: list[str]
) -> list[list[str]]:
    seen: set[str] = set()
    groups: list[list[str]] = []
    for start in order:
        if start not in nodes or start in seen:
            continue
        stack = [start]
        found: list[str] = []
        while stack:
            current = stack.pop()
            if current in seen or current not in nodes:
                continue
            seen.add(current)
            found.append(current)
            stack.extend(links[current] & nodes)
        found_set = set(found)
        groups.append([paper_id for paper_id in order if paper_id in found_set])
    return groups


def tight_kernel(state: dict[str, Any], paper_ids: list[str]) -> tuple[list[str], int]:
    """留下最密的那一团。每篇至少连着两篇才算圈子，密的一团优先于先碰到的松团。"""
    links = neighbor_links(state, paper_ids)
    order = list(paper_ids)
    tightness = 0
    remaining: set[str] = set()
    while True:
        peeled = _peel(links, set(order), tightness + 1)
        if not peeled:
            break
        tightness += 1
        remaining = peeled
    if tightness < 2 or not remaining:
        return [], 0
    groups = _components(links, remaining, order)

    def rank(group: list[str]) -> tuple[int, int, int]:
        return (_min_degree(links, set(group)), len(group), -order.index(group[0]))

    best = max(groups, key=rank)
    return best, _min_degree(links, set(best))


def tight_members(state: dict[str, Any], paper_ids: list[str]) -> list[str]:
    members, _tightness = tight_kernel(state, paper_ids)
    return members


def shortest_path(
    links: dict[str, set[str]], start: str, goal: str, nodes: list[str]
) -> list[str]:
    if start == goal:
        return [start]
    inside = set(nodes)
    previous: dict[str, str | None] = {start: None}
    queue = [start]
    for current in queue:
        for nxt in links[current]:
            if nxt not in inside or nxt in previous:
                continue
            previous[nxt] = current
            if nxt == goal:
                path = [goal]
                while previous[path[-1]] is not None:
                    path.append(previous[path[-1]])
                path.reverse()
                return path
            queue.append(nxt)
    return [start]


def in_degrees(state: dict[str, Any], members: list[str]) -> dict[str, int]:
    member_set = set(members)
    counts = {paper_id: 0 for paper_id in members}
    seen_edges: set[tuple[str, str]] = set()
    for paper_id in members:
        paper = paper_by_id(state, paper_id)
        if paper is None:
            continue
        for ref in paper["references"]:
            if ref in member_set and ref != paper_id and (paper_id, ref) not in seen_edges:
                seen_edges.add((paper_id, ref))
                counts[ref] += 1
        for citer in paper["cited_by"]:
            if citer in member_set and citer != paper_id and (citer, paper_id) not in seen_edges:
                seen_edges.add((citer, paper_id))
                counts[paper_id] += 1
    return counts


def suggest_core(state: dict[str, Any], members: list[str]) -> str:
    counts = in_degrees(state, members)
    return sorted(
        members,
        key=lambda paper_id: (
            -counts[paper_id],
            int(paper_by_id(state, paper_id)["year"]),
            members.index(paper_id),
        ),
    )[0]


def _base(
    *,
    kind: str,
    phase: str,
    note: str,
    paper: dict[str, Any] | None = None,
    anchor_id: str | None = None,
    missing: list[str] | None = None,
    dropped: int = 0,
    old: int = 0,
    circle: list[str] | None = None,
    core_id: str | None = None,
    switch_reason: str = "",
    path: list[str] | None = None,
    tightness: int = 0,
    core_links: int = 0,
    hops: int = 0,
    step_bound: int = 0,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "phase": phase,
        "paper": paper,
        "anchor_id": anchor_id,
        "missing": missing or [],
        "dropped": dropped,
        "old": old,
        "circle": circle or [],
        "core_id": core_id,
        "path": path or [],
        "note": note,
        "switch_reason": switch_reason,
        "tightness": tightness,
        "core_links": core_links,
        "hops": hops,
        "step_bound": step_bound,
    }


def _four_lines(
    state: dict[str, Any],
    anchor_id: str,
    circle: list[str],
    core_id: str,
    tightness: int,
    core_links: int,
    hops: int,
    step_bound: int,
) -> str:
    anchor = paper_by_id(state, anchor_id)
    objects, actions = slot_hits(state, anchor) if anchor else ([], [])
    return "\n".join(
        [
            (
                f"方向碰上了：对象「{'、'.join(objects)}」和动作「{'、'.join(actions)}」都在题目或摘要里。"
                "近不近是你写的是最近的。"
            ),
            f"圈里每一篇都直接连着这篇近邻：{'、'.join(circle)}。",
            "这是近三年篇数里、按已填引用边算出来的最密一团。三年前的直接文献这轮不看，所以这不是历史上的源头。",
            "这团只按名单里写下的引用边计算。没写上的边不算。",
            (
                f"紧密程度：每篇至少连着 {tightness} 篇。"
                f"被引最多的汇合点是「{core_id}」，在圈内被引 {core_links} 次。"
                "要攻的那篇可以改成团里另一篇。"
            ),
            f"进入核心：最短 {hops} 步，最多 {step_bound} 步，不往外扩。",
        ]
    )


def _off_path_block(state: dict[str, Any], circle: list[str], path: list[str]) -> str:
    skipped = [paper_id for paper_id in circle if paper_id not in path]
    if not skipped:
        return ""
    lines = ["最短路没经过这几篇，紧密程度仍按它们一起算："]
    for paper_id in skipped:
        paper = paper_by_id(state, paper_id)
        title = paper["title"] if paper else ""
        lines.append(f"- {paper_id} {title}")
    return "\n".join(lines)


def _walk_started(state: dict[str, Any], anchor: dict[str, Any]) -> bool:
    return any(state["topic"].get(paper_id) is not None for paper_id in ring_ids(anchor))


def _fail(anchor_id: str, reason: str, dropped: int, old: int) -> dict[str, Any]:
    note = "内核不紧密。" if reason == "loose" else "不收敛。"
    return _base(
        kind="fate",
        phase="circle",
        note=note,
        anchor_id=anchor_id,
        dropped=dropped,
        old=old,
        switch_reason=reason,
    )


def _switch_sentence(failed: list[tuple[str, str]]) -> str:
    labels = {
        "loose": "内核不紧密，通过它找不到圈子",
        "diverge": "不收敛，有限步进不到核心",
    }
    return "".join(f"近邻 {paper_id} {labels.get(reason, reason)}。" for paper_id, reason in failed)


def _switch_ask_note(failed: list[tuple[str, str]]) -> str:
    return (
        _switch_sentence(failed)
        + f"第 {len(failed)} 次换近邻，最多 {SWITCH_LIMIT} 次。"
        + "只看题目和摘要。"
    )


def _stop_for_failed(
    state: dict[str, Any], failed: list[tuple[str, str]], dropped: int, capped: bool
) -> dict[str, Any]:
    anchor_id = failed[-1][0]
    if state.get("fate"):
        return _base(
            kind="closed",
            phase="closed",
            note=f"你的判断：{state['fate']}。",
            anchor_id=anchor_id,
            dropped=dropped,
        )
    matched = len(state["papers"]) - dropped
    bits = [_switch_sentence(failed)]
    if dropped > 0 and dropped >= matched:
        bits.append(
            f"对不上的有 {dropped} 篇，不少于对得上的。"
            "叫法可能太窄，先用 add-name 补同义词。这一轮不要先写成主题没有价值。"
        )
    reasons = {reason for _, reason in failed}
    if "loose" in reasons:
        bits.append("这张名单里没有紧密圈子。")
    if "diverge" in reasons:
        bits.append("有限步进不到核心。")
    if capped:
        bits.append(f"已经换了 {SWITCH_LIMIT} 次近邻，到上限了。")
    else:
        switched = max(len(failed) - 1, 0)
        if switched:
            bits.append(f"已换 {switched} 次，最多 {SWITCH_LIMIT} 次。")
        bits.append("没有下一个近邻了。")
    bits.append("按现在的叫法和名单走不通。你若接受这一点，再写没有价值，或已经被攻克。这两句是对主题下的判断。")
    note = "".join(bits)
    return _base(
        kind="fate",
        phase="circle",
        note=note,
        anchor_id=anchor_id,
        dropped=dropped,
    )


def after_anchor(state: dict[str, Any], anchor_id: str) -> dict[str, Any]:
    anchor = paper_by_id(state, anchor_id)
    if anchor is None:
        raise SystemExit(f"跳板 {anchor_id} 不在名单里。")
    missing: list[str] = []
    dropped = 0
    old = 0
    recent_hits: list[str] = []
    for paper_id in ring_ids(anchor):
        paper = paper_by_id(state, paper_id)
        if paper is None:
            missing.append(paper_id)
            continue
        if not is_recent(state, paper):
            old += 1
            continue
        if not slot_hit(state, paper):
            dropped += 1
            continue
        if state["topic"].get(paper_id) == "no":
            continue
        recent_hits.append(paper_id)
    if missing:
        return _base(
            kind="missing",
            phase="circle",
            note="补上年份、题目和摘要后再收圈子。不要改用搜词。",
            anchor_id=anchor_id,
            missing=missing,
            dropped=dropped,
            old=old,
        )
    members, tightness = tight_kernel(state, recent_hits)
    if not members:
        reason = "diverge" if _walk_started(state, anchor) else "loose"
        if not state.get("fate"):
            return _fail(anchor_id, reason, dropped, old)
        return _base(
            kind="closed",
            phase="closed",
            note=f"你的判断：{state['fate']}。",
            anchor_id=anchor_id,
            dropped=dropped,
            old=old,
            switch_reason=reason,
        )
    chosen = state.get("core_id")
    if chosen not in members:
        chosen = None
    counts = in_degrees(state, members)
    core_id = chosen or suggest_core(state, members)
    links = neighbor_links(state, members)
    path = shortest_path(links, members[0], core_id, members)
    hops = max(len(path) - 1, 0)
    step_bound = max(len(members) - 1, 0)
    core_links = counts.get(core_id, 0)
    if path[-1] != core_id or hops > step_bound:
        return _fail(anchor_id, "diverge", dropped, old)
    measured = dict(
        path=path,
        tightness=tightness,
        core_links=core_links,
        hops=hops,
        step_bound=step_bound,
    )
    verdict = _four_lines(
        state, anchor_id, members, core_id, tightness, core_links, hops, step_bound
    )
    aside = _off_path_block(state, members, path)
    for paper_id in path:
        if state["topic"].get(paper_id) is None:
            step = path.index(paper_id) + 1
            where = "这一篇是被引最多的汇合点。" if paper_id == core_id else "先确认它算这个圈子。"
            note = "\n".join(
                part
                for part in (
                    verdict,
                    aside,
                    f"圈内最短路第 {step} 篇，共 {len(path)} 篇。只看题目和摘要。{where}",
                )
                if part
            )
            return _base(
                kind="ask",
                phase="circle",
                note=note,
                paper=paper_by_id(state, paper_id),
                anchor_id=anchor_id,
                dropped=dropped,
                old=old,
                circle=members,
                core_id=core_id,
                **measured,
            )
    if not state.get("open_problem"):
        return _base(
            kind="open",
            phase="open",
            note="\n".join(
                part
                for part in (
                    verdict,
                    aside,
                    "看汇合点的题目和摘要，把看见的缝写下来。这是核心摘要里看见的缝。要拿去攻，再只核对这一篇全文。全文不进这一轮。",
                )
                if part
            ),
            anchor_id=anchor_id,
            dropped=dropped,
            old=old,
            circle=members,
            core_id=core_id,
            **measured,
        )
    return _base(
        kind="done",
        phase="done",
        note=state["open_problem"],
        anchor_id=anchor_id,
        dropped=dropped,
        old=old,
        circle=members,
        core_id=core_id,
        **measured,
    )


def present(state: dict[str, Any]) -> dict[str, Any]:
    dropped = 0
    failed: list[tuple[str, str]] = []
    for paper in state["papers"]:
        if not slot_hit(state, paper):
            dropped += 1
            continue
        if state["topic"].get(paper["id"]) == "no":
            continue
        decision = state["decisions"].get(paper["id"])
        if decision is None:
            if len(failed) > SWITCH_LIMIT:
                return _stop_for_failed(state, failed, dropped, capped=True)
            near = _near_prompt(state, paper)
            if failed:
                note = _switch_ask_note(failed) + near
            else:
                note = "还没有最近近邻。按最近的顺序看题目和摘要。不要拿自己的观点去对。不必读全文。" + near
            return _base(
                kind="ask",
                phase="scan",
                note=note,
                paper=paper,
                dropped=dropped,
            )
        if not is_hotspot(decision):
            continue
        result = after_anchor(state, paper["id"])
        if result.get("switch_reason"):
            failed.append((paper["id"], result["switch_reason"]))
            continue
        result["dropped"] += dropped
        return result
    if failed:
        return _stop_for_failed(state, failed, dropped, capped=len(failed) > SWITCH_LIMIT)
    if not state["papers"]:
        return _base(
            kind="empty",
            phase="scan",
            note="名单是空的。按最近的顺序加论文，只加题目、摘要和年份。",
        )
    return _base(
        kind="unclear",
        phase="unclear",
        note="看不清。还没有你确认的最近近邻。不要把领域扫一遍。",
        dropped=dropped,
    )


def render(state: dict[str, Any], result: dict[str, Any]) -> str:
    lines: list[str] = []
    if result["dropped"]:
        lines.append(f"对不上的已丢掉 {result['dropped']} 篇。对象和动作要两处都中。")
    if result["old"]:
        lines.append(f"近三年只限制最多看多少篇。更早的这轮先不看：{result['old']} 篇。")
    if result["missing"]:
        lines.append("这些编号还没进名单，补年份、题目和摘要，不要搜词：")
        lines.extend(f"- {paper_id}" for paper_id in result["missing"])
    if result["circle"]:
        lines.append("最密的一团：" + "、".join(result["circle"]))
    kind = result["kind"]
    if kind == "ask":
        paper = result["paper"]
        if result["anchor_id"]:
            lines.append(
                f"跳板：{result['anchor_id']}。近三年是 {window_label(state)}，只限制最多看多少篇。"
            )
        lines.append(result["note"])
        lines.append(f"编号：{paper['id']}")
        lines.append(f"年份：{paper['year']}")
        lines.append(f"题目：{paper['title']}")
        lines.append(f"摘要：{paper['abstract']}")
        if result["phase"] == "scan":
            lines.append("你写：是最近的，或不是最近的。")
        else:
            lines.append("你写：算这个圈子，或不算这个圈子。")
    elif kind == "core":
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(f"建议的核心：{result['core_id']}")
        lines.append(result["note"])
    elif kind == "open":
        core = paper_by_id(state, result["core_id"]) if result.get("core_id") else None
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(f"汇合点：{result['core_id']}")
        if core is not None:
            lines.append(f"题目：{core['title']}")
            lines.append(f"摘要：{core['abstract']}")
        lines.append(result["note"])
    elif kind == "done":
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(f"汇合点：{result['core_id']}")
        lines.append(f"摘要里的缝：{result['note']}")
        lines.append("这是核心摘要里看见的缝。要拿去攻，再只核对这一篇全文。全文不进这一轮。")
    elif kind == "closed":
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(result["note"])
    elif kind == "fate":
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(f"近三年是 {window_label(state)}，只限制最多看多少篇。")
        lines.append(result["note"])
    else:
        if result.get("anchor_id"):
            lines.append(f"跳板：{result['anchor_id']}")
        lines.append(result["note"])
    return "\n".join(lines)


def _expect(state: dict[str, Any], kind: str, phase: str | None = None) -> dict[str, Any]:
    result = present(state)
    if result["kind"] != kind or (phase is not None and result["phase"] != phase):
        raise SystemExit("现在还没到这一步。先运行 next，看它要你写什么。")
    return result


def decide(state: dict[str, Any], paper_id: str, text: str) -> None:
    result = _expect(state, "ask", "scan")
    if result["paper"]["id"] != paper_id:
        raise SystemExit(f"现在只要看这一篇：{result['paper']['id']}")
    state["decisions"][paper_id] = {"hotspot": parse_hotspot(text)}


def mark_topic(state: dict[str, Any], paper_id: str, text: str) -> None:
    result = _expect(state, "ask", "circle")
    if result["paper"]["id"] != paper_id:
        raise SystemExit(f"现在只要看这一篇：{result['paper']['id']}")
    state["topic"][paper_id] = parse_topic(text)


def mark_fate(state: dict[str, Any], text: str) -> None:
    _expect(state, "fate")
    state["fate"] = parse_fate(text)


def mark_core(state: dict[str, Any], text: str, paper_id: str | None) -> None:
    result = present(state)
    if result["kind"] != "open":
        raise SystemExit("现在还没到这一步。先运行 next，看它要你写什么。")
    members = result["circle"]
    if paper_id:
        chosen = require_id(paper_id)
        if chosen not in members:
            raise SystemExit("核心必须是最小圈子里的一篇。")
        state["core_id"] = chosen
        return
    reject_question(text)
    if "不是核心" in text:
        raise SystemExit("写下核心是圈子里的哪一篇编号。")
    if "是核心" not in text:
        raise SystemExit("你写是核心，或用 --id 指定圈子里的另一篇。")
    state["core_id"] = result["core_id"]


def mark_open(state: dict[str, Any], text: str) -> None:
    _expect(state, "open")
    cleaned = " ".join(text.split())
    if cleaned in {"继续", "好", "好的", "知道了"} or len(cleaned) < 4:
        raise SystemExit("把核心摘要里看见的缝写下来。没有的话，写没有悬而未决。")
    state["open_problem"] = cleaned


def cmd_init(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = state_path(root)
    if path.exists():
        raise SystemExit(f"名单已经有了：{path}")
    this_year = require_year(args.this_year)
    save_state(root, blank_state(args.object, args.action, this_year))
    print(f"对象：{args.object.strip()}")
    print(f"动作：{args.action.strip()}")
    print(f"近三年是 {this_year - RECENT_SPAN}–{this_year}，只限制最多看多少篇。")
    print(f"换近邻最多 {SWITCH_LIMIT} 次。全程只看题目和摘要，不必读全文。")
    print("对象和动作是热点的叫法，不是你要证明的句子。")
    print("同义词之后用 add-name 加上。没有写明的叫法不能拿来匹配。")


def cmd_add_name(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    name = require_name(args.name)
    key = "object_names" if args.slot == "object" else "action_names"
    if name in state[key]:
        raise SystemExit("这个叫法已经写过了。")
    state[key].append(name)
    save_state(root, state)
    label = "对象" if args.slot == "object" else "动作"
    print(f"已记下{label}叫法：{name}")


def cmd_add(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    paper_id = require_id(args.id)
    if paper_by_id(state, paper_id):
        raise SystemExit(f"这篇已经在名单里：{paper_id}")
    title = args.title.strip()
    abstract = args.abstract.strip()
    if not title or not abstract:
        raise SystemExit("题目和摘要都要有。没有摘要就不能快判。")
    paper = {
        "id": paper_id,
        "year": require_year(args.year),
        "title": title,
        "abstract": abstract,
        "references": split_ids(args.references),
        "cited_by": split_ids(args.cited_by),
    }
    state["papers"].append(paper)
    save_state(root, state)
    print(f"已加入 {paper_id}")


def cmd_next(args: argparse.Namespace) -> None:
    state = load_state(args.root.resolve())
    print(render(state, present(state)))


def cmd_decide(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    decide(state, require_id(args.id), args.words)
    save_state(root, state)
    print(render(state, present(state)))


def cmd_topic(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    mark_topic(state, require_id(args.id), args.words)
    save_state(root, state)
    print(render(state, present(state)))


def cmd_fate(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    mark_fate(state, args.words)
    save_state(root, state)
    print(render(state, present(state)))


def cmd_core(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    mark_core(state, args.words or "", args.id)
    save_state(root, state)
    print(render(state, present(state)))


def cmd_open(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    mark_open(state, args.text)
    save_state(root, state)
    print(render(state, present(state)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hunt", description="凝练当前热点圈，写下悬而未决的命题")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="写下对象和动作")
    init.add_argument("--root", type=Path, default=Path("."))
    init.add_argument("--object", required=True)
    init.add_argument("--action", required=True)
    init.add_argument("--this-year", type=int, default=date.today().year)
    init.set_defaults(func=cmd_init)

    naming = sub.add_parser("add-name", help="补一个已经写明的同义叫法")
    naming.add_argument("--root", type=Path, default=Path("."))
    naming.add_argument("--slot", required=True, choices=("object", "action"))
    naming.add_argument("--name", required=True)
    naming.set_defaults(func=cmd_add_name)

    add = sub.add_parser("add", help="按可疑程度加入一篇的题目、摘要和年份")
    add.add_argument("--root", type=Path, default=Path("."))
    add.add_argument("--id", required=True)
    add.add_argument("--year", type=int, required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--abstract", required=True)
    add.add_argument("--references", default="")
    add.add_argument("--cited-by", default="")
    add.set_defaults(func=cmd_add)

    nxt = sub.add_parser("next", help="看现在该写什么")
    nxt.add_argument("--root", type=Path, default=Path("."))
    nxt.set_defaults(func=cmd_next)

    decision = sub.add_parser("decide", help="确认这篇是不是当前热点的入口")
    decision.add_argument("--root", type=Path, default=Path("."))
    decision.add_argument("--id", required=True)
    decision.add_argument("--words", required=True)
    decision.set_defaults(func=cmd_decide)

    topic = sub.add_parser("topic", help="确认这篇算不算这个主题")
    topic.add_argument("--root", type=Path, default=Path("."))
    topic.add_argument("--id", required=True)
    topic.add_argument("--words", required=True)
    topic.set_defaults(func=cmd_topic)

    fate = sub.add_parser("fate", help="近邻都换完仍走不到紧密核心时，写下没有价值或已经被攻克")
    fate.add_argument("--root", type=Path, default=Path("."))
    fate.add_argument("--words", required=True)
    fate.set_defaults(func=cmd_fate)

    core = sub.add_parser("core", help="确认核心，或改成圈子里的另一篇")
    core.add_argument("--root", type=Path, default=Path("."))
    core.add_argument("--words", default="")
    core.add_argument("--id")
    core.set_defaults(func=cmd_core)

    opened = sub.add_parser("open", help="写下核心里悬而未决的命题")
    opened.add_argument("--root", type=Path, default=Path("."))
    opened.add_argument("--text", required=True)
    opened.set_defaults(func=cmd_open)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
