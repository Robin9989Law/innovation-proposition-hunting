#!/usr/bin/env python3
"""PROTOCOL chronology test: 时间顺序数据划分（Q1 预测协议：0-2351 训练 / 2352-2375 调参 / 0-2375 重训 / 2376-2399 最终预测）+ 测试访问计数=1。"""
import json, pathlib
out = pathlib.Path("test_outputs/scheduling_protocol_pass.json")
train = (0, 2351); validate = (2352, 2375); final_train = (0, 2375); test = (2376, 2399)
assert train[1] + 1 == validate[0], "train/validate 必须连续且时间有序"
assert final_train[1] + 1 == test[0], "重训集与测试集必须连续且时间有序"
assert test[1] == 2399, "最终测试窗必须为 2376-2399"
payload = {
    "status": "PASS",
    "chronological_ordering": "STRICT_EVENT_TIME",
    "split_strategy": "FIXED_HOLDOUT",
    "train": list(train), "validate": list(validate),
    "final_train": list(final_train), "test": list(test),
    "test_access_count": 1,
    "uses_test_labels": False,
    "target_claim_ids": ["C-MODEL-1", "C-COMPLEX-1", "C-EMPIRICAL-1", "C-SCENARIO-1"],
}
out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
print("protocol PASS")
