#!/usr/bin/env python3
"""PREMISE_REMOVAL witness: 移除延迟前提（E=0）后命题规律必须失败 -> exit 1。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "implementation"))
import scheduling_lp as slp
out = pathlib.Path("theory_witnesses/premise_removal.txt")
c = slp.Config()
fails = slp.premise_removal_fails(c)
out.write_text(f"PREMISE_REMOVAL\npremise_removed=E=0\nexpected=FAIL\nobserved={'FAIL' if fails else 'PASS'}\n", encoding="utf-8")
print("premise removed -> regularity fails:", fails)
sys.exit(1 if fails else 0)
