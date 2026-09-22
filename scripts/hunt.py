#!/usr/bin/env python3
"""按四步找悬而未决的命题。

1. 用题目和摘要找到最危险近邻。是不是同一个东西，只认读者的原话。
2. 从这篇出发，只收近三年的直接前作和后续，收成包括主题的最小圈子。
3. 圈子里被其他篇引用最多的，当作核心。读者可以改。
4. 核心读全文，由读者写下悬而未决的命题。
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any

STATE_NAME = "neighbor_hunt.json"
DANGERS = ("占住", "能推出来", "只是像")
DANGER_RANK = {"占住": 2, "能推出来": 1}
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


def parse_same(text: str) -> str:
    reject_question(text)
    if "是不是同一个东西" in text:
        raise SystemExit(
            "是不是同一个东西，要写死。"
            "是同一个东西，才能当锚点。不是同一个东西，就换一篇。"
        )
    rejected = "不是同一个东西" in text
    confirmed = "是同一个东西" in text.replace("不是同一个东西", "")
    if rejected and confirmed:
        raise SystemExit(
            "是不是同一个东西，要写死。"
            "是同一个东西，才能当锚点。不是同一个东西，就换一篇。"
        )
    if rejected:
        return "no"
    if confirmed:
        return "yes"
    raise SystemExit(
        "对象是不是同一个东西，要你自己写。"
        "是同一个东西，才能当锚点。不是同一个东西，就换一篇。"
    )


def parse_topic(text: str) -> str:
    reject_question(text)
    rejected = "不算这个主题" in text
    confirmed = "算这个主题" in text.replace("不算这个主题", "")
    if rejected and confirmed:
        raise SystemExit("算不算这个主题，要写死。算这个主题，或不算这个主题。")
    if rejected:
        return "no"
    if confirmed:
        return "yes"
    raise SystemExit("这一篇算不算这个主题，要你自己写。算这个主题，或不算这个主题。")


def parse_fate(text: str) -> str:
    reject_question(text)
    hits = [name for name in FATES if name in text]
    if len(hits) != 1:
        raise SystemExit("近三年收不成圈子。你写没有价值，或已经被攻克。两个都写，或都不写，都不算。")
    return hits[0]


def is_dangerous(decision: dict[str, Any]) -> bool:
    return decision.get("same") == "yes" and decision.get("danger") in DANGER_RANK


def ring_ids(paper: dict[str, Any]) -> list[str]:
    seen: list[str] = []
    for key in ("references", "cited_by"):
        for paper_id in paper.get(key) or []:
            if paper_id == paper["id"] or paper_id in seen:
                continue
            seen.append(paper_id)
    return seen


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
        "note": note,
    }


def after_anchor(state: dict[str, Any], anchor_id: str) -> dict[str, Any]:
    anchor = paper_by_id(state, anchor_id)
    if anchor is None:
        raise SystemExit(f"锚点 {anchor_id} 不在名单里。")
    missing: list[str] = []
    dropped = 0
    old = 0
    members: list[str] = []
    if is_recent(state, anchor):
        members.append(anchor_id)
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
        topic = state["topic"].get(paper_id)
        if topic is None:
            return _base(
                kind="ask",
                phase="circle",
                note="近三年里，这一篇算不算这个主题。",
                paper=paper,
                anchor_id=anchor_id,
                missing=list(missing),
                dropped=dropped,
                old=old,
            )
        if topic == "yes":
            members.append(paper_id)
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
    if not members:
        if not state.get("fate"):
            return _base(
                kind="fate",
                phase="circle",
                note="近三年的直接前作和后续里，没有包括这个主题的圈子。你写没有价值，或已经被攻克。",
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
    core_id = state.get("core_id") or (members[0] if len(members) == 1 else None)
    if len(members) > 1 and not state.get("core_id"):
        return _base(
            kind="core",
            phase="core",
            note="被圈子里其他论文引用最多的是这一篇。你写是核心，或指定圈子里的另一篇。",
            anchor_id=anchor_id,
            dropped=dropped,
            old=old,
            circle=members,
            core_id=suggest_core(state, members),
        )
    if core_id not in members:
        raise SystemExit("核心必须是最小圈子里的一篇。")
    if not state.get("open_problem"):
        return _base(
            kind="open",
            phase="open",
            note="读这一篇的全文，写下它悬而未决的命题。",
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
                note="还没有最危险近邻。现在只看这一篇的题目和摘要。",
                paper=paper,
                dropped=dropped,
            )
        if is_dangerous(decision):
            anchor_id = paper["id"]
            break
    if anchor_id is None:
        if not state["papers"]:
            return _base(
                kind="empty",
                phase="scan",
                note="名单是空的。按最可疑的顺序加论文，只加题目、摘要和年份。",
            )
        return _base(
            kind="unclear",
            phase="unclear",
            note="看不清。没有一篇是你确认过的危险近邻。不要把领域扫一遍当成蓝海。",
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
            lines.append(f"最危险近邻：{result['anchor_id']}。近三年是 {window_label(state)}。")
        lines.append(result["note"])
        lines.append(f"编号：{paper['id']}")
        lines.append(f"年份：{paper['year']}")
        lines.append(f"题目：{paper['title']}")
        lines.append(f"摘要：{paper['abstract']}")
        if result["phase"] == "scan":
            lines.append("你写：是同一个东西，或不是同一个东西。")
            lines.append("如果是，再写这一句是占住、能推出来，还是只是像。")
        else:
            lines.append("你写：算这个主题，或不算这个主题。")
    elif kind == "core":
        lines.append(f"最危险近邻：{result['anchor_id']}")
        lines.append(f"建议的核心：{result['core_id']}")
        lines.append(result["note"])
    elif kind == "open":
        lines.append(f"最危险近邻：{result['anchor_id']}")
        lines.append(f"核心：{result['core_id']}")
        lines.append(result["note"])
    elif kind == "done":
        lines.append(f"最危险近邻：{result['anchor_id']}")
        lines.append(f"核心：{result['core_id']}")
        lines.append(f"悬而未决：{result['note']}")
    elif kind == "closed":
        lines.append(f"最危险近邻：{result['anchor_id']}")
        lines.append(result["note"])
    elif kind == "fate":
        lines.append(f"最危险近邻：{result['anchor_id']}")
        lines.append(f"近三年是 {window_label(state)}。")
        lines.append(result["note"])
    else:
        if result.get("anchor_id"):
            lines.append(f"最危险近邻：{result['anchor_id']}")
        lines.append(result["note"])
    return "\n".join(lines)


def _expect(state: dict[str, Any], kind: str, phase: str | None = None) -> dict[str, Any]:
    result = present(state)
    if result["kind"] != kind or (phase is not None and result["phase"] != phase):
        raise SystemExit("现在还没到这一步。先运行 next，看它要你写什么。")
    return result


def decide(state: dict[str, Any], paper_id: str, same_text: str, danger: str | None) -> None:
    result = _expect(state, "ask", "scan")
    if result["paper"]["id"] != paper_id:
        raise SystemExit(f"现在只要看这一篇：{result['paper']['id']}")
    same = parse_same(same_text)
    if same == "no":
        if danger:
            raise SystemExit("不是同一个东西，就不用再写占住、能推出来或只是像。")
        state["decisions"][paper_id] = {"same": "no", "danger": None}
        return
    if danger not in DANGERS:
        raise SystemExit("是同一个东西之后，要写占住、能推出来，或只是像。")
    state["decisions"][paper_id] = {"same": "yes", "danger": danger}


def mark_topic(state: dict[str, Any], paper_id: str, text: str) -> None:
    result = _expect(state, "ask", "circle")
    if result["paper"]["id"] != paper_id:
        raise SystemExit(f"现在只要看这一篇：{result['paper']['id']}")
    state["topic"][paper_id] = parse_topic(text)


def mark_fate(state: dict[str, Any], text: str) -> None:
    _expect(state, "fate")
    state["fate"] = parse_fate(text)


def mark_core(state: dict[str, Any], text: str, paper_id: str | None) -> None:
    result = _expect(state, "core")
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
    decide(state, require_id(args.id), args.same, args.danger)
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
    parser = argparse.ArgumentParser(prog="hunt", description="找到最危险近邻，再收近三年的最小圈子")
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

    decision = sub.add_parser("decide", help="确认这篇是不是最危险近邻")
    decision.add_argument("--root", type=Path, default=Path("."))
    decision.add_argument("--id", required=True)
    decision.add_argument("--same", required=True)
    decision.add_argument("--danger", choices=DANGERS)
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
