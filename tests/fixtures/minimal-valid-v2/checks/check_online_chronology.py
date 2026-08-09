"""Executable chronology check for C-ALGORITHM-1.

TARGET_CLAIM_IDS: C-ALGORITHM-1
"""

import hashlib
import json
from pathlib import Path

from implementation.online_algorithm import evaluate_online


TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)
RECORDED_COMMAND = "python3 -m checks.check_online_chronology"
IMPLEMENTATION_PATH = "implementation/online_algorithm.py"
TEST_PATH = "checks/check_online_chronology.py"


class RecordingModel:
    def __init__(self):
        self.events = []

    def predict_one(self, features):
        self.events.append(("predict", features))
        return features

    def update_one(self, features, label):
        self.events.append(("update", features, label))


def assert_claim_chronology():
    model = RecordingModel()
    evaluate_online(model, [1, 2], [10, 20])
    assert model.events == [
        ("predict", 1),
        ("update", 1, 10),
        ("predict", 2),
        ("update", 2, 20),
    ]


def file_sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_pass_manifest():
    root = Path(__file__).resolve().parents[1]
    return {
        "schema_version": "2.0",
        "status": "PASS",
        "exit_code": 0,
        "command": RECORDED_COMMAND,
        "target_claim_ids": list(TARGET_CLAIM_IDS),
        "implementation_relative_path": IMPLEMENTATION_PATH,
        "implementation_sha256": file_sha256(root / IMPLEMENTATION_PATH),
        "executable_test_relative_path": TEST_PATH,
        "executable_test_sha256": file_sha256(root / TEST_PATH),
    }


if __name__ == "__main__":
    assert_claim_chronology()
    print(json.dumps(build_pass_manifest(), ensure_ascii=False, indent=2))
