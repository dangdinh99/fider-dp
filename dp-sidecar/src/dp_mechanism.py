"""
Differential Privacy mechanisms for the fider-dp sidecar service.
This file implements Laplace noise and DP versions of:
- count
- sum
- mean

Used by the API to generate private statistics for items.
"""

import numpy as np

RATING_MIN = 1.0
RATING_MAX = 5.0


# ------------------------------------------------------------
# Basic Laplace
# ------------------------------------------------------------
def laplace_noise(scale: float) -> float:
    """
    Draw Laplace noise with mean 0 and scale 'scale'.
    """
    return np.random.laplace(loc=0.0, scale=scale)


# ------------------------------------------------------------
# DP Count
# ------------------------------------------------------------
def dp_count(true_count: int, epsilon_count: float) -> int:
    """
    Differentially Private Count using Laplace mechanism.

    Sensitivity(count) = 1 because one user can only add/remove one rating.
    scale = 1 / epsilon_count
    """
    if epsilon_count <= 0:
        raise ValueError("epsilon_count must be positive (DP parameter).")

    scale = 1.0 / epsilon_count
    noisy_count = true_count + laplace_noise(scale)

    noisy_count = int(round(max(0, noisy_count)))
    return noisy_count


# ------------------------------------------------------------
# DP Sum
# ------------------------------------------------------------
def dp_sum(true_sum: float,
           epsilon_sum: float,
           rating_min: float = RATING_MIN,
           rating_max: float = RATING_MAX) -> float:
    """
    Differentially Private Sum of ratings.

    Sensitivity(sum) = max_rating - min_rating = 4
    because one user's rating can change the sum by at most 4.
    """
    if epsilon_sum <= 0:
        raise ValueError("epsilon_sum must be positive (DP parameter).")

    sensitivity = rating_max - rating_min
    scale = sensitivity / epsilon_sum

    noisy_sum = true_sum + laplace_noise(scale)
    return noisy_sum


# ------------------------------------------------------------
# DP Mean
# ------------------------------------------------------------
def dp_mean(true_sum: float,
            true_count: int,
            epsilon_sum: float,
            rating_min: float = RATING_MIN,
            rating_max: float = RATING_MAX):
    """
    Differentially Private Mean.

    Approach:
        - Add Laplace noise to the sum (sensitivity = 4)
        - Divide by the TRUE count (not noisy count)

    Returning None if no ratings exist.
    """
    if true_count <= 0:
        return None

    noisy_sum = dp_sum(true_sum, epsilon_sum, rating_min, rating_max)
    noisy_mean = noisy_sum / true_count

    noisy_mean = max(rating_min, min(rating_max, noisy_mean))
    return noisy_mean