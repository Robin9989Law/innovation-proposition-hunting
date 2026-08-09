"""Executable chronology check for C-ALGORITHM-1.

TARGET_CLAIM_IDS: C-ALGORITHM-1
"""

from implementation.online_algorithm import evaluate_online


TARGET_CLAIM_IDS = ("C-ALGORITHM-1",)


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


if __name__ == "__main__":
    assert_claim_chronology()
