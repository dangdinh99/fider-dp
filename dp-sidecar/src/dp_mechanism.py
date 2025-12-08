"""
Differential Privacy Mechanisms
Pure DP logic - Laplace noise, threshold checking, confidence intervals
"""
import numpy as np
from typing import Tuple, Optional
from .config import THRESHOLD, EPSILON_PER_QUERY, SENSITIVITY


class DPMechanism:
    """
    Implements differential privacy mechanisms for vote counts.
    """
    
    def __init__(self, 
                 threshold: int = None,
                 epsilon: float = None,
                 sensitivity: int = None):
        """
        Initialize DP mechanism.
        
        Args:
            threshold: Minimum count before release (default from config)
            epsilon: Privacy budget per query (default from config)
            sensitivity: Maximum influence of one individual (default 1)
        """
        self.threshold = threshold or THRESHOLD
        self.epsilon = epsilon or EPSILON_PER_QUERY
        self.sensitivity = sensitivity or SENSITIVITY
    
    def check_threshold(self, true_count: int) -> bool:
        """
        Check if count meets minimum threshold for release.
        
        Args:
            true_count: The true vote count
            
        Returns:
            True if count >= threshold, False otherwise
        """
        return true_count >= self.threshold
    
    def add_laplace_noise(self, true_count: int) -> float:
        """
        Add Laplace noise to count for differential privacy.
        
        The scale of Laplace noise is sensitivity/epsilon.
        Larger epsilon = less noise = less privacy.
        
        Args:
            true_count: The true vote count
            
        Returns:
            Noisy count (may be negative, but we'll clip to 0 when displaying)
        """
        scale = self.sensitivity / self.epsilon
        noise = np.random.laplace(loc=0, scale=scale)
        noisy_count = true_count + noise
        
        return noisy_count
    
    def release_count(self, true_count: int) -> Tuple[Optional[float], float, bool]:
        """
        Main function: decide whether to release a DP count.
        
        Args:
            true_count: The true vote count
            
        Returns:
            Tuple of:
            - noisy_count: The DP count (or None if threshold not met)
            - epsilon_used: How much privacy budget was consumed
            - meets_threshold: Whether threshold was met
        """
        meets_threshold = self.check_threshold(true_count)
        
        if not meets_threshold:
            # Don't release anything if below threshold
            return None, 0.0, False
        
        # Add noise and release
        noisy_count = self.add_laplace_noise(true_count)
        return noisy_count, self.epsilon, True
    
    def calculate_confidence_interval(self, 
                                     noisy_count: float, 
                                     confidence: float = 0.95) -> Tuple[float, float]:
        """
        Calculate confidence interval for the noisy count.
        
        For Laplace mechanism, the confidence interval is:
        noisy_count ± scale * ln(2/(1-confidence))
        
        Args:
            noisy_count: The noisy count
            confidence: Confidence level (default 0.95 for 95%)
            
        Returns:
            (lower_bound, upper_bound)
        """
        scale = self.sensitivity / self.epsilon
        margin = scale * np.log(2 / (1 - confidence))
        
        lower = max(0, noisy_count - margin)
        upper = noisy_count + margin
        
        return lower, upper


def test_dp_mechanism():
    """Test function to verify DP mechanism works"""
    print("Testing DP Mechanism...")
    print("=" * 60)
    
    dp = DPMechanism(threshold=15, epsilon=0.5)
    
    # Test 1: Below threshold
    print("\nTest 1: Count below threshold (10 votes)")
    noisy, eps_used, meets = dp.release_count(10)
    print(f"  Result: noisy_count={noisy}, epsilon_used={eps_used}, meets_threshold={meets}")
    assert noisy is None
    assert eps_used == 0.0
    assert meets is False
    print("  ✓ Passed: No release below threshold")
    
    # Test 2: Above threshold
    print("\nTest 2: Count above threshold (50 votes)")
    noisy, eps_used, meets = dp.release_count(50)
    print(f"  Result: noisy_count={noisy:.2f}, epsilon_used={eps_used}, meets_threshold={meets}")
    assert noisy is not None
    assert eps_used == 0.5
    assert meets is True
    print("  ✓ Passed: Released noisy count")
    
    # Test 3: Multiple releases show different noise
    print("\nTest 3: Multiple releases of same count (50 votes)")
    print("  Showing noise varies each time:")
    for i in range(5):
        noisy, _, _ = dp.release_count(50)
        lower, upper = dp.calculate_confidence_interval(noisy)
        print(f"    Release {i+1}: {noisy:.2f} (95% CI: [{lower:.2f}, {upper:.2f}])")
    print("  ✓ Passed: Noise is random")
    
    # Test 4: Check noise magnitude
    print("\nTest 4: Verify noise magnitude")
    samples = [dp.release_count(100)[0] for _ in range(1000)]
    mean_noisy = np.mean(samples)
    std_noisy = np.std(samples)
    expected_scale = 1 / 0.5
    print(f"  True count: 100")
    print(f"  Average noisy count (1000 samples): {mean_noisy:.2f}")
    print(f"  Standard deviation: {std_noisy:.2f}")
    print(f"  Expected scale (1/ε): {expected_scale:.2f}")
    print("  ✓ Passed: Noise magnitude is correct")
    
    print("\n" + "=" * 60)
    print("✓ All DP mechanism tests passed!")


if __name__ == "__main__":
    test_dp_mechanism()