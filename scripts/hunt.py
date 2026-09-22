#!/usr/bin/env python3
"""最快找到最危险近邻。

程序只做三件事：对象和动作两处是否都出现、按你写下的判断往前走、一圈只用参考文献和被引编号。
是不是同一个东西，只认你的原话。
"""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Any

STATE_NAME = "neighbor_hunt.json"
DANGERS = ("占住", "能推出来", "只是像")
DANGER_RANK = {"占住": 2, "能推出来": 1}


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
    return data


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def blank_state(object_name: str, action_name: str) -> dict[str, Any]:
    return {
        "object_names": [require_name(object_name)],
        "action_names": [require_name(action_name)],
        "papers": [],
        "decisions": {},
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


def paper_by_id(state: dict[str, Any], paper_id: str) -> dict[str, Any] | None:
    for paper in state["papers"]:
        if paper["id"] == paper_id:
            return paper
    return None


def slot_hit(state: dict[str, Any], paper: dict[str, Any]) -> bool:
    text = normalize(f"{paper.get('title', '')}\n{paper.get('abstract', '')}")
    if not text:
        return False
    object_hit = any(normalize(name) in text for name in state["object_names"])
    action_hit = any(normalize(name) in text for name in state["action_names"])
    return object_hit and action_hit


def parse_same(text: str) -> str:
    if any(mark in text for mark in ("吗", "？", "?")):
        raise SystemExit("不要写成问句。是同一个东西，或不是同一个东西。")
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


def _ask(
    paper: dict[str, Any],
    *,
    phase: str,
    anchor_id: str | None,
    missing: list[str],
    dropped: int,
    redraws: int,
) -> dict[str, Any]:
    return {
        "kind": "ask",
        "phase": phase,
        "paper": paper,
        "anchor_id": anchor_id,
        "missing": missing,
        "dropped": dropped,
        "redraws": redraws,
        "note": "",
    }


def walk_ring(state: dict[str, Any], anchor_id: str, redraws: int) -> dict[str, Any]:
    anchor = paper_by_id(state, anchor_id)
    if anchor is None:
        raise SystemExit(f"锚点 {anchor_id} 不在名单里。")
    missing: list[str] = []
    dropped = 0
    anchor_rank = DANGER_RANK[state["decisions"][anchor_id]["danger"]]
    for paper_id in ring_ids(anchor):
        paper = paper_by_id(state, paper_id)
        if paper is None:
            missing.append(paper_id)
            continue
        if not slot_hit(state, paper):
            dropped += 1
            continue
        decision = state["decisions"].get(paper_id)
        if decision is None:
            return _ask(
                paper,
                phase="ring",
                anchor_id=anchor_id,
                missing=list(missing),
                dropped=dropped,
                redraws=redraws,
            )
        if is_dangerous(decision) and DANGER_RANK[decision["danger"]] > anchor_rank:
            if missing:
                return {
                    "kind": "missing",
                    "phase": "ring",
                    "paper": None,
                    "anchor_id": anchor_id,
                    "missing": list(missing),
                    "dropped": dropped,
                    "redraws": redraws,
                    "note": "先补上这些编号，再决定要不要换锚点。",
                }
            if redraws < 1:
                return walk_ring(state, paper_id, redraws + 1)
            return {
                "kind": "done",
                "phase": "done",
                "paper": None,
                "anchor_id": paper_id,
                "missing": [],
                "dropped": dropped,
                "redraws": redraws,
                "note": "这篇更危险。圈只许重画一次，不再往外扩。",
            }
    if missing:
        return {
            "kind": "missing",
            "phase": "ring",
            "paper": None,
            "anchor_id": anchor_id,
            "missing": missing,
            "dropped": dropped,
            "redraws": redraws,
            "note": "补上题目和摘要后再继续。不要改用搜词。",
        }
    return {
        "kind": "done",
        "phase": "done",
        "paper": None,
        "anchor_id": anchor_id,
        "missing": [],
        "dropped": dropped,
        "redraws": redraws,
        "note": "这一圈看完，判断没变。",
    }


def present(state: dict[str, Any]) -> dict[str, Any]:
    dropped = 0
    anchor_id: str | None = None
    for paper in state["papers"]:
        if not slot_hit(state, paper):
            dropped += 1
            continue
        decision = state["decisions"].get(paper["id"])
        if decision is None:
            result = _ask(
                paper,
                phase="scan",
                anchor_id=None,
                missing=[],
                dropped=dropped,
                redraws=0,
            )
            return result
        if is_dangerous(decision):
            anchor_id = paper["id"]
            break
    if anchor_id is None:
        if not state["papers"]:
            return {
                "kind": "empty",
                "phase": "scan",
                "paper": None,
                "anchor_id": None,
                "missing": [],
                "dropped": 0,
                "redraws": 0,
                "note": "名单是空的。按最可疑的顺序加论文，只加题目和摘要。",
            }
        return {
            "kind": "unclear",
            "phase": "unclear",
            "paper": None,
            "anchor_id": None,
            "missing": [],
            "dropped": dropped,
            "redraws": 0,
            "note": "看不清。没有一篇是你确认过的危险近邻。不要把领域扫一遍当成蓝海。",
        }
    return walk_ring(state, anchor_id, 0)


def render(result: dict[str, Any]) -> str:
    lines: list[str] = []
    if result["dropped"]:
        lines.append(f"对不上的已丢掉 {result['dropped']} 篇。对象和动作要两处都中。")
    if result["missing"]:
        lines.append("这些编号还没进名单，补题目和摘要，不要搜词：")
        lines.extend(f"- {paper_id}" for paper_id in result["missing"])
    kind = result["kind"]
    if kind == "ask":
        paper = result["paper"]
        if result["phase"] == "scan":
            lines.append("还没有锚点。现在只看这一篇的题目和摘要。")
        else:
            lines.append(
                f"锚点是 {result['anchor_id']}。这一圈只看它的参考文献和被引，现在是这一篇。"
            )
        lines.append(f"编号：{paper['id']}")
        lines.append(f"题目：{paper['title']}")
        lines.append(f"摘要：{paper['abstract']}")
        lines.append("你写：是同一个东西，或不是同一个东西。")
        lines.append("如果是，再写这一句是占住、能推出来，还是只是像。")
    elif kind == "done":
        lines.append(f"锚点：{result['anchor_id']}")
        lines.append(result["note"])
    elif kind in {"unclear", "empty", "missing"}:
        if result.get("anchor_id"):
            lines.append(f"锚点：{result['anchor_id']}")
        lines.append(result["note"])
    return "\n".join(lines)


def decide(state: dict[str, Any], paper_id: str, same_text: str, danger: str | None) -> None:
    result = present(state)
    expected = result["paper"]["id"] if result["kind"] == "ask" else None
    if expected != paper_id:
        if expected:
            raise SystemExit(f"现在只要看这一篇：{expected}")
        raise SystemExit("现在没有要你确认的论文。")
    same = parse_same(same_text)
    if same == "no":
        if danger:
            raise SystemExit("不是同一个东西，就不用再写占住、能推出来或只是像。")
        state["decisions"][paper_id] = {"same": "no", "danger": None}
        return
    if danger not in DANGERS:
        raise SystemExit("是同一个东西之后，要写占住、能推出来，或只是像。")
    state["decisions"][paper_id] = {"same": "yes", "danger": danger}


def cmd_init(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    path = state_path(root)
    if path.exists():
        raise SystemExit(f"名单已经有了：{path}")
    save_state(root, blank_state(args.object, args.action))
    print(f"对象：{args.object.strip()}")
    print(f"动作：{args.action.strip()}")
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
    print(f"已记下{ '对象' if args.slot == 'object' else '动作' }叫法：{name}")


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
    print(render(present(state)))


def cmd_decide(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    state = load_state(root)
    decide(state, require_id(args.id), args.same, args.danger)
    save_state(root, state)
    print(render(present(state)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hunt", description="最快找到最危险近邻")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="写下对象和动作")
    init.add_argument("--root", type=Path, default=Path("."))
    init.add_argument("--object", required=True)
    init.add_argument("--action", required=True)
    init.set_defaults(func=cmd_init)

    naming = sub.add_parser("add-name", help="补一个已经写明的同义叫法")
    naming.add_argument("--root", type=Path, default=Path("."))
    naming.add_argument("--slot", required=True, choices=("object", "action"))
    naming.add_argument("--name", required=True)
    naming.set_defaults(func=cmd_add_name)

    add = sub.add_parser("add", help="按可疑程度加入一篇的题目和摘要")
    add.add_argument("--root", type=Path, default=Path("."))
    add.add_argument("--id", required=True)
    add.add_argument("--title", required=True)
    add.add_argument("--abstract", required=True)
    add.add_argument("--references", default="")
    add.add_argument("--cited-by", default="")
    add.set_defaults(func=cmd_add)

    nxt = sub.add_parser("next", help="看现在该确认的那一篇，或已经可以停")
    nxt.add_argument("--root", type=Path, default=Path("."))
    nxt.set_defaults(func=cmd_next)

    decision = sub.add_parser("decide", help="写下你对这一篇的确认")
    decision.add_argument("--root", type=Path, default=Path("."))
    decision.add_argument("--id", required=True)
    decision.add_argument("--same", required=True)
    decision.add_argument("--danger", choices=DANGERS)
    decision.set_defaults(func=cmd_decide)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
