import numpy as np
from scipy.stats import poisson

def calibrate_and_predict(momio_1, momio_2, momio_3):
    """
    Modelo Poisson calibrado para Liga MX
    Calcula probabilidades 1X2, EV y Kelly fraccionario
    """
    # 1. Probabilidades implícitas sin VIG
    probs = np.array([1/momio_1, 1/momio_2, 1/momio_3])
    vig = probs.sum() - 1
    true_probs = probs / (1 + vig)

    # 2. Estimar λ (goles esperados) con calibración empírica
    lambda_home = -np.log(true_probs[1] + true_probs[2]) * 1.42
    lambda_away = -np.log(true_probs[1] + true_probs[0]) * 1.18

    # 3. Distribución Poisson 1X2
    max_g = 7
    p1, p2, p3 = 0.0, 0.0, 0.0
    for h in range(max_g):
        for a in range(max_g):
            p_score = poisson.pmf(h, lambda_home) * poisson.pmf(a, lambda_away)
            if h > a: p1 += p_score
            elif h == a: p2 += p_score
            else: p3 += p_score

    # Normalizar a 100%
    total = p1 + p2 + p3
    p1, p2, p3 = p1/total, p2/total, p3/total

    # 4. EV y Kelly (25% fraccional, tope 8%)
    ev = p1 * momio_1 - 1
    b = momio_1 - 1
    kelly = (b * p1 - (1 - p1)) / b
    kelly = max(0, min(kelly * 0.25, 0.08))

    return {
        "vig": round(vig, 4),
        "true_prob": round(p1, 4),
        "expected_value": round(ev, 4),
        "kelly_stake": round(kelly * 100, 2),
        "lambda_home": round(lambda_home, 2),
        "lambda_away": round(lambda_away, 2)
    }

if __name__ == "__main__":
    # Test rápido con momios típicos de Liga MX
    res = calibrate_and_predict(1.85, 3.40, 4.10)
    print("✅ Modelo Poisson calibrado:")
    for k, v in res.items():
        print(f"   {k}: {v}")
