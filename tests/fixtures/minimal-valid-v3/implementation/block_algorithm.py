"""Known-incompatible block implementation used by negative fixtures."""


def evaluate_in_blocks(model, xs, ys, block_size=1000):
    predictions = []
    for start in range(0, len(xs), block_size):
        stop = min(start + block_size, len(xs))
        predictions.extend(model.predict_many(xs[start:stop]))
        for index in range(start, stop):
            model.update_one(xs[index], ys[index])
    return predictions
