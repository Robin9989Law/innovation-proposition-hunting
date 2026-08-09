# Anonymous candidate manuscript

## Contamination identity

For observation $i$, response contamination by an additive perturbation $\eta$ gives

$$e_i = e_i^0 + (1-h_{ii})\eta.$$

Therefore the exact inverse correction is

$$\frac{e_i}{1-h_{ii}} = e_i^0 + \eta.$$

## Recovery window

Let the positive residual excess before any recovery update be $q_0=|r_1|>0$. Each completed update subtracts exactly $c\tau>0$, so

$$q_{k+1}=q_k-c\tau.$$

An update is performed whenever the pre-update excess satisfies $q_k\ge c\tau$. Recovery stops at the first post-update index $T$ satisfying the strict inequality $q_T<c\tau$. Thus $T^*$ counts the number of completed updates (equivalently, $q_{T^*}$ is the state after update $T^*$), not the initial time index. The exact recovery window is

$$T^*=\left\lceil\frac{|r_1|}{c\tau}-1\right\rceil.$$

## Degrees of freedom

Once feature rank saturates, effective degrees of freedom necessarily satisfy $\mathrm{df}\to n$ even when the regularization level remains fixed and strictly positive.

## Evaluation protocol

Algorithm 1 uses per-sample test-then-train evaluation: each record is predicted and then immediately used to update the model before the next record is predicted.
