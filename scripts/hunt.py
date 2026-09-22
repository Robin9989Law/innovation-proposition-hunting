#!/usr/bin/env python3
"""用最近近邻当跳板，走进紧密圈子，再沿最短的路到核心。

跳板不必在核心里。紧密圈子只留它近三年、并且彼此有引用的直接前作和后续。
只读核心全文，写下开放命题。
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


def slot_hit(state: dict[str, Any], paper: dict[str, Any]) -> bool:
    text = normalize(f"{paper.get('title', '')}\n{paper.get('abstract', '')}")
    if not text:
        return False
    object_hit = any(normalize(name) in text for name in state["object_names"])
    action_hit = any(normalize(name) in text for name in state["action_names"])
    return object_hit and action_hit


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
        raise SystemExit("近三年收不成圈子。你写没有价值，或已经被攻克。两个都写，或都不写，都不算。")
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


def tight_members(state: dict[str, Any], paper_ids: list[str]) -> list[str]:
    """彼此至少有一条引用的那些留下。只连着跳板、彼此不连的丢掉。"""
    if len(paper_ids) <= 1:
        return list(paper_ids)
    links = neighbor_links(state, paper_ids)
    remaining = set(paper_ids)
    while True:
        loose = [
            paper_id
            for paper_id in remaining
            if not (links[paper_id] & (remaining - {paper_id}))
        ]
        if not loose:
            break
        remaining.difference_update(loose)
    ordered = [paper_id for paper_id in paper_ids if paper_id in remaining]
    if not ordered:
        return []
    entry = ordered[0]
    seen: list[str] = []
    stack = [entry]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.append(current)
        stack.extend(links[current] & remaining)
    seen_set = set(seen)
    return [paper_id for paper_id in ordered if paper_id in seen_set]


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


def suggest_core(state: dict[str, Any], members: list[str]) -> str:
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
        "path": [],
        "note": note,
    }


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
    members = tight_members(state, recent_hits)
    if not members:
        if not state.get("fate"):
            return _base(
                kind="fate",
                phase="circle",
                note="跳板旁边的近三年论文彼此不连，或者一篇都没有。收不成紧密圈子。你写没有价值，或已经被攻克。",
                anchor_id=anchor_id,
                dropped=dropped,
                old=old,
            )
        return _base(
            kind="closed",
            phase="closed",
            note=f"你的判断：{state['fate']}。",
            anchor_id=anchor_id,
            dropped=dropped,
            old=old,
        )
    chosen = state.get("core_id")
    if chosen and chosen not in members:
        raise SystemExit("核心必须在紧密圈子里。")
    core_id = chosen or suggest_core(state, members)
    links = neighbor_links(state, members)
    path = shortest_path(links, members[0], core_id, members)
    for paper_id in path:
        if state["topic"].get(paper_id) is None:
            step = path.index(paper_id) + 1
            note = (
                f"从跳板往核心走，第 {step} 步，共 {len(path)} 步。"
                + ("这一篇是核心。" if paper_id == core_id else "先确认它在圈子里。")
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
            )
    if not state.get("open_problem"):
        return _base(
            kind="open",
            phase="open",
            note="读这一篇的全文，写下它悬而未决的命题。这一句是创新突破的思路，也是有攻关价值的地方。",
            anchor_id=anchor_id,
            dropped=dropped,
            old=old,
            circle=members,
            core_id=core_id,
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
    )


def present(state: dict[str, Any]) -> dict[str, Any]:
    dropped = 0
    anchor_id: str | None = None
    for paper in state["papers"]:
        if not slot_hit(state, paper):
            dropped += 1
            continue
        decision = state["decisions"].get(paper["id"])
        if decision is None:
            return _base(
                kind="ask",
                phase="scan",
                note="还没有最近近邻。按最近的顺序看题目和摘要。不要拿自己的观点去对。",
                paper=paper,
                dropped=dropped,
            )
        if is_hotspot(decision):
            anchor_id = paper["id"]
            break
    if anchor_id is None:
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
    result = after_anchor(state, anchor_id)
    result["dropped"] += dropped
    return result


def render(state: dict[str, Any], result: dict[str, Any]) -> str:
    lines: list[str] = []
    if result["dropped"]:
        lines.append(f"对不上的已丢掉 {result['dropped']} 篇。对象和动作要两处都中。")
    if result["old"]:
        lines.append(f"三年前的直接文献不进圈子：{result['old']} 篇。")
    if result["missing"]:
        lines.append("这些编号还没进名单，补年份、题目和摘要，不要搜词：")
        lines.extend(f"- {paper_id}" for paper_id in result["missing"])
    if result["circle"]:
        lines.append("最小圈子：" + "、".join(result["circle"]))
    kind = result["kind"]
    if kind == "ask":
        paper = result["paper"]
        if result["anchor_id"]:
            lines.append(f"跳板：{result['anchor_id']}。近三年是 {window_label(state)}。")
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
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(f"核心：{result['core_id']}")
        lines.append(result["note"])
    elif kind == "done":
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(f"核心：{result['core_id']}")
        lines.append(f"悬而未决：{result['note']}")
        lines.append("这一句是创新突破的思路，也是有攻关价值的地方。")
    elif kind == "closed":
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(result["note"])
    elif kind == "fate":
        lines.append(f"跳板：{result['anchor_id']}")
        lines.append(f"近三年是 {window_label(state)}。")
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
        raise SystemExit("把核心里悬而未决的那一句写下来。没有的话，写没有悬而未决。")
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
    print(f"近三年是 {this_year - RECENT_SPAN}–{this_year}。")
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

    fate = sub.add_parser("fate", help="近三年收不成圈子时，写下没有价值或已经被攻克")
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
