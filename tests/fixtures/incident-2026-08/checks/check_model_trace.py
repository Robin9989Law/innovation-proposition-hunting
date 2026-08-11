#!/usr/bin/env python3
"""C-MODEL-1 trace test: 调用 implementation.scheduling_lp.solve 并产出 PASS 输出。"""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "implementation"))
import scheduling_lp as slp
out = pathlib.Path("test_outputs/model_pass.json")
r = slp.solve(24.0, 1.0, slp.Config())
assert r["cost"] > 0 and r["purchase_MWh"] > 0
out.write_text(json.dumps({"status": "PASS", "claim_id": "C-MODEL-1", "implementation_symbol": "scheduling_lp.solve", "metrics": {k: round(v, 2) for k, v in r.items()}}, ensure_ascii=False, indent=1), encoding="utf-8")
print("model trace PASS")
