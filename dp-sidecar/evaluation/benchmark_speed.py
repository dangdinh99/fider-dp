import requests
import time
import numpy as np

# Config: Local API URL (Post ID 1 to force a DB lookup)
API_URL = "http://localhost:8000/api/counts/1" 

def benchmark_api():
    latencies = []
    print(f"🚀 Benchmarking API at {API_URL}...")
    print("   (Make sure your 'python -m src.api' window is still running!)\n")
    
    # 1. Warm up request (often slower)
    try:
        requests.get(API_URL)
    except Exception as e:
        print(f" Error: Could not connect to API. Is it running?\n   Details: {e}")
        return

    # 2. Run 100 requests
    print("⏱️  Running 100 requests...")
    for i in range(100):
        start = time.time()
        requests.get(API_URL)
        end = time.time()
        
        # Convert to milliseconds
        latencies.append((end - start) * 1000)

    # 3. Calculate Stats
    avg_lat = np.mean(latencies)
    p95_lat = np.percentile(latencies, 95)
    
    print("\n" + "="*30)
    print("📊 PERFORMANCE RESULTS")
    print("="*30)
    print(f"✅ Average Latency:  {avg_lat:.2f} ms")
    print(f"✅ 95th Percentile:  {p95_lat:.2f} ms")
    print("="*30)
    
    if avg_lat < 50:
        print("Conclusion: 🚀 FAST (Negligible overhead)")
    elif avg_lat < 200:
        print("Conclusion: 🟢 ACCEPTABLE (Standard web speed)")
    else:
        print("Conclusion: ⚠️ SLOW (Might need optimization)")

if __name__ == "__main__":
    benchmark_api()