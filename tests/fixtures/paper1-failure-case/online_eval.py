def evaluate(model, xs, ys, block=1000):
    predictions=[]
    for start in range(0,len(xs),block):
        stop=min(start+block,len(xs))
        predictions.extend(model.predict(xs[start:stop]))
        for index in range(start,stop): model.update(xs[index],ys[index])
    return predictions
