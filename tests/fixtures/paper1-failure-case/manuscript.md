# Anonymous candidate manuscript

## Contamination identity

For observation $i$, response contamination by an additive perturbation $\eta$ gives

$$e_i = e_i^0 + (1-h_{ii})\eta.$$

Therefore the exact inverse correction is

$$\frac{e_i}{1-h_{ii}} = e_i^0 + \eta.$$

## Recovery window

When the initial residual is $r_1$, per-step correction is $c\tau$, and the endpoint is inclusive, the exact recovery window is

$$T^*=\left\lceil\frac{|r_1|}{c\tau}-1\right\rceil.$$

## Degrees of freedom

Once feature rank saturates, effective degrees of freedom necessarily satisfy $\mathrm{df}\to n$ even when the regularization level remains fixed and strictly positive.

## Evaluation protocol

Algorithm 1 uses per-sample test-then-train evaluation: each record is predicted and then immediately used to update the model before the next record is predicted.
