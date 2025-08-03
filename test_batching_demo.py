#!/usr/bin/env python3
"""
Demo script for the batching system.
This shows how the batching works without requiring actual API keys.
"""

import asyncio
import time
import logging
from batched_ai_client import BatchedAIClient

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)


class MockUnifiedClient:
    """Mock client for demonstration purposes."""
    
    async def text_completion(self, messages, max_tokens=1000, temperature=0.1):
        """Mock text completion that simulates API call."""
        await asyncio.sleep(0.1)  # Simulate API delay
        return f"Mock response for: {messages[0]['content'][:50]}..."
    
    async def vision_completion(self, text_prompt, base64_image, max_tokens=1000, temperature=0.1):
        """Mock vision completion that simulates API call."""
        await asyncio.sleep(0.1)  # Simulate API delay
        return f"Mock vision response for: {text_prompt[:50]}..."


class DemoBatchedClient(BatchedAIClient):
    """Demo version of batched client that uses mock API calls."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Replace the fallback client with our mock
        self.fallback_client = MockUnifiedClient()


async def demo_batching():
    """Demonstrate the batching system."""
    print("=== Batching System Demo ===\n")
    
    # Create a demo client with short intervals for testing
    client = DemoBatchedClient(
        batch_interval_hours=0.01,  # 36 seconds for demo
        max_batch_size=5,
        enable_fallback=True,
        fallback_threshold_seconds=10  # 10 seconds for demo
    )
    
    print("1. Submitting multiple requests for batching...")
    
    # Submit several text requests
    tasks = []
    for i in range(3):
        task = client.text_completion(
            messages=[{"role": "user", "content": f"Request {i+1}: Say hello"}],
            max_tokens=50,
            temperature=0.1
        )
        tasks.append(task)
    
    print(f"   Submitted {len(tasks)} requests")
    print(f"   Pending requests: {client.get_stats()['pending_requests']}")
    
    # Wait a bit and check stats
    await asyncio.sleep(2)
    stats = client.get_stats()
    print(f"   After 2s - Pending: {stats['pending_requests']}, Cached: {stats['cached_results']}")
    
    # Wait for batch processing
    print("\n2. Waiting for batch processing...")
    start_time = time.time()
    
    # Wait for results
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    processing_time = time.time() - start_time
    print(f"   Processing completed in {processing_time:.1f}s")
    
    # Show results
    print("\n3. Results:")
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"   Request {i+1}: Error - {result}")
        else:
            print(f"   Request {i+1}: {result}")
    
    # Show final stats
    final_stats = client.get_stats()
    print(f"\n4. Final Stats:")
    print(f"   Pending requests: {final_stats['pending_requests']}")
    print(f"   Cached results: {final_stats['cached_results']}")
    print(f"   Batch counter: {final_stats['batch_counter']}")
    
    # Test urgent request
    print("\n5. Testing urgent request (immediate processing)...")
    urgent_result = await client.text_completion(
        messages=[{"role": "user", "content": "Urgent request"}],
        max_tokens=50,
        temperature=0.1,
        urgent=True
    )
    print(f"   Urgent result: {urgent_result}")
    
    # Cleanup
    client.shutdown()
    print("\n=== Demo completed ===")


async def demo_fallback():
    """Demonstrate the fallback system."""
    print("\n=== Fallback System Demo ===\n")
    
    client = DemoBatchedClient(
        batch_interval_hours=1.0,  # Long interval
        max_batch_size=5,
        enable_fallback=True,
        fallback_threshold_seconds=5  # Short threshold for demo
    )
    
    print("1. Submitting request with long batch interval...")
    
    # Submit a request
    task = client.text_completion(
        messages=[{"role": "user", "content": "Test request"}],
        max_tokens=50,
        temperature=0.1
    )
    
    print("2. Waiting for fallback (5 second threshold)...")
    start_time = time.time()
    
    try:
        result = await asyncio.wait_for(task, timeout=10)
        processing_time = time.time() - start_time
        print(f"   Result received in {processing_time:.1f}s: {result}")
    except asyncio.TimeoutError:
        print("   Request timed out")
    
    # Cleanup
    client.shutdown()
    print("\n=== Fallback demo completed ===")


if __name__ == "__main__":
    asyncio.run(demo_batching())
    asyncio.run(demo_fallback()) 