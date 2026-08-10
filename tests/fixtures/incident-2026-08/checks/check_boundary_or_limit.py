#!/usr/bin/env python3
"""BOUNDARY_OR_LIMIT witness: 边界 E* 存在且有限。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "implementation"))
import scheduling_lp as slp
out = pathlib.Path("theory_witnesses/boundary_or_limit.txt")
c = slp.Config()
E_star = slp.find_boundary(c)
ok = 0.0 < E_star < 168.0
out.write_text(f"BOUNDARY_OR_LIMIT\nE_star={E_star:.2f}\nfinite_and_positive={ok}\n", encoding="utf-8")
print("E*:", round(E_star, 2))
sys.exit(0 if ok else 1)
