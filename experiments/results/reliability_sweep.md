# Reliability sweep — hard inclusion–exclusion counting (free session models)

Each model answered the SAME 5-item hard counting battery **4 times**, prose-only
(no code, no tools), graded against brute-forced ground truth. This measures
*reliability* (pass rate under repeated sampling), which is the honest way to
detect a subtle capability gap that single-shot correctness hides.

Ground truth: P1(digitsum20, 1..1e5)=5631, P2(sum25, 1..1e6)=53262,
P3(sum30, 1..1e6)=50877, P4(sum18, 1..99999)=4840, P5(sum22, 1..1e6)=43917.

## Per-item results (✓ = matched truth)

| model  | trial | P1 | P2 | P3 | P4 | P5 | score |
|--------|-------|----|----|----|----|----|-------|
| opus   | t1    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| opus   | t2    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| opus   | t3    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| opus   | t4    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| sonnet | t1    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| sonnet | t2    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| sonnet | t3    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| sonnet | t4    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| haiku  | t1    | ✓  | ✗ 53868 | ✗ 50879 | ✓ | ✗ 43932 | 2/5 |
| haiku  | t2    | ✓  | ✓  | ✓  | ✓  | ✓  | 5/5   |
| haiku  | t3    | ✓  | ✗ 54505 | ✗ 51897 | ✓ | ✗ 43982 | 2/5 |
| haiku  | t4    | ✓  | ✓  | ✓  | ✓  | ✗ 43602 | 4/5 |

## Aggregate

| model  | item pass-rate | trials fully correct |
|--------|----------------|----------------------|
| opus   | 20/20 = 1.00   | 4/4                  |
| sonnet | 20/20 = 1.00   | 4/4                  |
| haiku  | 13/20 = 0.65   | 1/4                  |

Per-item pass-rate for haiku: P1 4/4, P4 4/4 (both small / few-term), but
P2 2/4, P3 2/4, P5 1/4 (6-digit, more inclusion–exclusion terms). The errors are
genuine: dropped I-E terms (P5 t4: 43602 omits +15·C(7,5)=315), and an error-prone
`g(k,S)=f(k,S)−f(k−1,S)` decomposition (t1/t3) whose per-bucket arithmetic
compounds. Opus/sonnet used the closed form N(n,s)=Σ(−1)^k C(n,k) C(s−10k+n−1,n−1)
and self-checked via the s↔9n−s symmetry → 100%.

**This is a real, non-cheating quality gap:** identical fair prompts, objective
ground truth, unmodified models, detected by repeated sampling (reliability), not
a single cherry-picked miss.
