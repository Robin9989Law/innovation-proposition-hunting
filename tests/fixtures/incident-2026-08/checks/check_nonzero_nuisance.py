#!/usr/bin/env python3
"""NONZERO_NUISANCE witness: 碳权重非零时替代仍存在。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "implementation"))
import scheduling_lp as slp
out = pathlib.Path("theory_witnesses/nonzero_nuisance.txt")
c = slp.Config(carbon_weight=2.0)
si = slp.substitution_index(24.0, c)
ok = si["overlap_frac"] >= 0.10
out.write_text(f"NONZERO_NUISANCE\ncarbon_weight=2.0\noverlap_frac={si['overlap_frac']:.4f}\nsubstitution={ok}\n", encoding="utf-8")
print("carbon-nuisance overlap_frac:", round(si["overlap_frac"], 4))
sys.exit(0 if ok else 1)
