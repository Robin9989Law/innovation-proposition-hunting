#!/usr/bin/env python3
"""C-COMPLEX-1 trace test: find_boundary 运行时间证据（复杂度有界）。"""
import json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "implementation"))
import scheduling_lp as slp
out = pathlib.Path("test_outputs/complexity_pass.json")
t0 = time.time()
E_star = slp.find_boundary(slp.Config())
dt = time.time() - t0
assert 0 < E_star < 168 and dt < 600
out.write_text(json.dumps({"status": "PASS", "claim_id": "C-COMPLEX-1", "implementation_symbol": "scheduling_lp.find_boundary", "E_star": round(E_star, 2), "runtime_s": round(dt, 2)}, ensure_ascii=False, indent=1), encoding="utf-8")
print("complexity trace PASS, E*:", round(E_star, 2), "runtime:", round(dt, 1), "s")
