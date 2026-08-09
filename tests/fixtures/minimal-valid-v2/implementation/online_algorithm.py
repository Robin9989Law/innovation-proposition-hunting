"""Reference implementation bound to C-ALGORITHM-1."""


def evaluate_online(model, xs, ys):
    predictions = []
    for features, label in zip(xs, ys):
        predictions.append(model.predict_one(features))
        model.update_one(features, label)
    return predictions
