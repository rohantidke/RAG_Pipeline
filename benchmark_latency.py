import json
import time
import urllib.request

def benchmark_grounded_queries():
    url = "http://127.0.0.1:8000/query"
    questions = [
        "What are foundation models in AI Engineering?",
        "How do you build machine learning powered applications?",
        "Explain generative deep learning techniques.",
        "What are the challenges of deploying AI systems to production?",
        "How do transformers and attention mechanisms work in foundation models?"
    ]
    
    latencies = []
    print("=" * 70)
    print("  Measuring End-to-End Query Latency on Indexed Knowledge Base  ")
    print("=" * 70)

    for idx, question in enumerate(questions, start=1):
        payload = json.dumps({
            "query": question,
            "top_k": 5,
            "use_cache": False
        }).encode("utf-8")
        
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        
        start_time = time.perf_counter()
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_response = resp.read()
        end_time = time.perf_counter()
        
        elapsed_ms = (end_time - start_time) * 1000.0
        latencies.append(elapsed_ms)
        
        data = json.loads(raw_response)
        citations_count = len(data.get("citations", []))
        confidence = data.get("confidence", 0.0)
        abstained = data.get("abstained", False)
        
        print(f"Request {idx}: {elapsed_ms:.2f} ms | Citations: {citations_count} | Confidence: {confidence:.3f} | Abstained: {abstained} | Query: '{question}'")

    avg_latency = sum(latencies) / len(latencies)
    min_latency = min(latencies)
    max_latency = max(latencies)
    
    print("-" * 70)
    print(f"Individual Latencies: {[round(t, 2) for t in latencies]} ms")
    print(f"Average Latency: {avg_latency:.2f} ms (Min: {min_latency:.2f} ms, Max: {max_latency:.2f} ms)")
    print("=" * 70)

if __name__ == "__main__":
    benchmark_grounded_queries()
