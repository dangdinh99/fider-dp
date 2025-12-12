"""
Averaging Attack Resistance Test
Tests whether querying multiple times allows recovery of true count
"""
import requests
import time
import numpy as np
from collections import Counter

API_BASE = "http://localhost:8000"

def test_averaging_attack(post_id=1, num_queries=100):
    """
    Attempt to recover true count by averaging multiple noisy queries.
    
    With proper noise reuse, all queries should return the SAME noisy count,
    making averaging useless for the attacker.
    """
    print("="*70)
    print("AVERAGING ATTACK RESISTANCE TEST")
    print("="*70)
    print()
    
    print(f"Attack Scenario:")
    print(f"  Target: Post ID {post_id}")
    print(f"  Strategy: Query {num_queries} times and average results")
    print(f"  Goal: Recover true count by canceling out noise")
    print()
    
    print(f"Executing {num_queries} queries...")
    print("(This should take ~10 seconds with 100ms per query)")
    print()
    
    noisy_counts = []
    errors = []
    
    start_time = time.time()
    
    for i in range(num_queries):
        try:
            response = requests.get(f"{API_BASE}/api/counts/{post_id}")
            
            if response.status_code == 200:
                data = response.json()
                noisy_count = data.get('noisy_count')
                
                if noisy_count is not None:
                    noisy_counts.append(noisy_count)
                    
                    # Progress indicator every 20 queries
                    if (i + 1) % 20 == 0:
                        print(f"  Progress: {i+1}/{num_queries} queries completed")
                        
        except Exception as e:
            errors.append(str(e))
            
    elapsed = time.time() - start_time
    
    print(f"✓ Completed in {elapsed:.1f} seconds")
    print()
    
    if not noisy_counts:
        print("❌ Error: No successful queries!")
        print("   Make sure:")
        print("   1. API is running (uvicorn src.api:app --reload)")
        print("   2. Post ID 1 exists in Fider")
        print("   3. Post has at least 1 vote (meets threshold)")
        return
    
    # Analyze results
    print("─" * 70)
    print("ATTACK RESULTS:")
    print("─" * 70)
    
    # Check uniqueness
    unique_counts = set(noisy_counts)
    value_counts = Counter(noisy_counts)
    
    print(f"  Total queries: {len(noisy_counts)}")
    print(f"  Unique values returned: {len(unique_counts)}")
    print()
    
    if len(unique_counts) == 1:
        print("✅ NOISE REUSE DETECTED!")
        print(f"   All {len(noisy_counts)} queries returned: {noisy_counts[0]}")
        print()
    else:
        print("⚠️  Multiple values detected:")
        for value, count in sorted(value_counts.items()):
            print(f"   Value {value:.2f}: {count} times ({count/len(noisy_counts)*100:.1f}%)")
        print()
    
    # Statistical analysis
    mean_noisy = np.mean(noisy_counts)
    std_noisy = np.std(noisy_counts)
    
    print("Statistical Analysis:")
    print(f"  Mean: {mean_noisy:.2f}")
    print(f"  Std Dev: {std_noisy:.4f}")
    print(f"  Min: {min(noisy_counts):.2f}")
    print(f"  Max: {max(noisy_counts):.2f}")
    print()
    
    # Verdict
    print("─" * 70)
    print("ATTACK VERDICT:")
    print("─" * 70)
    
    if std_noisy < 0.001:  # Essentially zero
        print("✅ ATTACK FAILED!")
        print()
        print("Reason:")
        print("  • All queries returned identical value")
        print("  • Noise reuse mechanism working correctly")
        print("  • Averaging provides NO advantage to attacker")
        print("  • Standard deviation = 0 (no variance to average out)")
        print()
        print("Privacy Protection: STRONG ✅")
    else:
        print("⚠️  ATTACK MAY SUCCEED!")
        print()
        print("Reason:")
        print("  • Multiple different values observed")
        print("  • Averaging may reduce noise uncertainty")
        print("  • Noise reuse may not be working")
        print()
        print("Privacy Protection: WEAK ⚠️")
    
    print()
    print("="*70)
    
    return {
        'num_queries': len(noisy_counts),
        'unique_values': len(unique_counts),
        'mean': mean_noisy,
        'std': std_noisy,
        'attack_failed': std_noisy < 0.001
    }


def test_multiple_posts():
    """
    Test averaging attack on multiple posts
    """
    print("\n\n")
    print("="*70)
    print("TESTING MULTIPLE POSTS")
    print("="*70)
    print()
    
    results = {}
    
    for post_id in [1, 2, 3]:
        print(f"\n--- Testing Post ID {post_id} ---\n")
        
        try:
            result = test_averaging_attack(post_id=post_id, num_queries=50)
            results[post_id] = result
            
        except Exception as e:
            print(f"❌ Error testing post {post_id}: {e}")
            
        print()
        time.sleep(1)  # Brief pause between tests
    
    # Summary
    if results:
        print("="*70)
        print("SUMMARY ACROSS ALL POSTS:")
        print("="*70)
        
        all_passed = all(r['attack_failed'] for r in results.values())
        
        for post_id, result in results.items():
            status = "✅ PROTECTED" if result['attack_failed'] else "⚠️  VULNERABLE"
            print(f"  Post {post_id}: {status} (std={result['std']:.4f})")
        
        print()
        
        if all_passed:
            print("✅ ALL POSTS PROTECTED: Noise reuse working system-wide!")
        else:
            print("⚠️  Some posts vulnerable - investigate noise reuse implementation")


if __name__ == "__main__":
    # Test single post in detail
    test_averaging_attack(post_id=1, num_queries=100)
    # Optional: Test multiple posts
    # Uncomment the line below to test posts 1, 2, 3
    # test_multiple_posts()