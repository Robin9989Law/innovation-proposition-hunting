#!/usr/bin/env python3
"""MINIMAL_POSITIVE witness: 替代区存在（overlap_frac >= 0.10）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "implementation"))
import scheduling_lp as slp
out = pathlib.Path("theory_witnesses/minimal_positive.txt")
c = slp.Config()
si = slp.substitution_index(24.0, c)
mv0 = slp.storage_marginal(0.0, 0.0, 1.0, c)
mv24 = slp.storage_marginal(24.0, 0.0, 1.0, c)
ok = si["overlap_frac"] >= 0.10 and mv24 < mv0
out.write_text(
    f"MINIMAL_POSITIVE\noverlap_frac={si['overlap_frac']:.4f}\nMV_E(S=0)={mv0:.1f}\nMV_E(S=1)={mv24:.1f}\nsubstitution={ok}\n",
    encoding="utf-8")
print("overlap_frac:", round(si["overlap_frac"], 4), "| MV_E decreases:", mv24 < mv0)
sys.exit(0 if ok else 1)
