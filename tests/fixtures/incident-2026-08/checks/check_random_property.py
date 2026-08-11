#!/usr/bin/env python3
"""RANDOM_PROPERTY witness: 随机价格结构/任务种子下替代方向一致（>=5/6）。"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "implementation"))
import scheduling_lp as slp
out = pathlib.Path("theory_witnesses/random_property.txt")
results = []
for seed, ps in [(42, 1.0), (7, 0.8), (99, 1.2), (13, 0.9), (55, 1.1), (21, 1.3)]:
    c = slp.Config(seed=seed, price_scale=ps)
    mv0 = slp.storage_marginal(0.0, 0.0, 1.0, c)
    mv24 = slp.storage_marginal(24.0, 0.0, 1.0, c)
    results.append(mv24 < mv0)
ok = sum(results) >= 5
out.write_text(f"RANDOM_PROPERTY\ndraws={len(results)}\nsubstitution_consistent={results}\npass={ok}\n", encoding="utf-8")
print("random draws substitution-consistent:", results)
sys.exit(0 if ok else 1)
