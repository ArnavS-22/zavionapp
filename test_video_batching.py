#!/usr/bin/env python3
"""
Test script for Video Processing Batching System

This script tests the batch processing implementation for video frames.
"""

import asyncio
import logging
import tempfile
import time
from pathlib import Path

# Add the gum directory to the path
import sys
sys.path.append('.')

from controller import process_frames_in_batches, analyze_frames_batch_with_ai, BATCH_SIZE
import asyncio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)

async def test_batch_processing():
    """Test the batch processing system with dummy frame data."""
    
    print("=== Video Processing Batch System Test ===\n")
    
    # Create dummy frame data
    dummy_frames = []
    for i in range(10):
        # Create a simple dummy base64 image (just a small test image)
        dummy_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="  # 1x1 pixel
        
        dummy_frames.append({
            'frame_number': i + 1,
            'base64_data': dummy_base64,
            'frame_name': f"frame_{i+1:03d}.jpg",
            'timestamp': i * 0.5
        })
    
    print(f"Created {len(dummy_frames)} dummy frames")
    print(f"Batch size: {BATCH_SIZE}")
    
    # Test batch processing
    try:
        print("\nTesting batch processing...")
        
        # Create a semaphore for testing
        semaphore = asyncio.Semaphore(3)
        
        # Process frames in batches
        results = await process_frames_in_batches(dummy_frames, semaphore, BATCH_SIZE)
        
        print(f"✅ Batch processing completed!")
        print(f"   Input frames: {len(dummy_frames)}")
        print(f"   Output results: {len(results)}")
        
        # Check results
        for result in results:
            print(f"   Frame {result['frame_number']}: {'✅' if 'error' not in result else '❌'} {result.get('batch_id', 'N/A')}")
        
        # Count successful vs failed
        successful = sum(1 for r in results if 'error' not in r)
        failed = sum(1 for r in results if 'error' in r)
        
        print(f"\nResults Summary:")
        print(f"   Successful: {successful}")
        print(f"   Failed: {failed}")
        print(f"   Success rate: {successful/len(results)*100:.1f}%")
        
    except Exception as e:
        print(f"❌ Batch processing test failed: {e}")
        import traceback
        traceback.print_exc()

async def test_batch_analysis():
    """Test the batch analysis function directly."""
    
    print("\n=== Testing Batch Analysis Function ===\n")
    
    # Create a small batch of dummy frames
    dummy_batch = []
    for i in range(3):
        dummy_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        
        dummy_batch.append({
            'frame_number': i + 1,
            'base64_data': dummy_base64
        })
    
    try:
        print(f"Testing batch analysis with {len(dummy_batch)} frames...")
        
        results = await analyze_frames_batch_with_ai(dummy_batch, "test_batch")
        
        print(f"✅ Batch analysis completed!")
        print(f"   Results: {len(results)}")
        
        for result in results:
            print(f"   Frame {result['frame_number']}: {'✅' if 'error' not in result else '❌'}")
            if 'analysis' in result and len(result['analysis']) > 100:
                print(f"      Analysis preview: {result['analysis'][:100]}...")
        
    except Exception as e:
        print(f"❌ Batch analysis test failed: {e}")
        import traceback
        traceback.print_exc()

async def test_edge_cases():
    """Test edge cases for batch processing."""
    
    print("\n=== Testing Edge Cases ===\n")
    
    # Test empty frames list
    try:
        print("Testing empty frames list...")
        semaphore = asyncio.Semaphore(3)
        results = await process_frames_in_batches([], semaphore, BATCH_SIZE)
        print(f"✅ Empty list test: {len(results)} results (expected: 0)")
    except Exception as e:
        print(f"❌ Empty list test failed: {e}")
    
    # Test single frame
    try:
        print("Testing single frame...")
        single_frame = [{
            'frame_number': 1,
            'base64_data': "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
        }]
        semaphore = asyncio.Semaphore(3)
        results = await process_frames_in_batches(single_frame, semaphore, BATCH_SIZE)
        print(f"✅ Single frame test: {len(results)} results (expected: 1)")
    except Exception as e:
        print(f"❌ Single frame test failed: {e}")
    
    # Test large batch size
    try:
        print("Testing large batch size...")
        large_frames = []
        for i in range(5):
            large_frames.append({
                'frame_number': i + 1,
                'base64_data': "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
            })
        semaphore = asyncio.Semaphore(3)
        results = await process_frames_in_batches(large_frames, semaphore, 10)  # Large batch size
        print(f"✅ Large batch size test: {len(results)} results (expected: 5)")
    except Exception as e:
        print(f"❌ Large batch size test failed: {e}")

async def main():
    """Run all tests."""
    try:
        await test_batch_processing()
        await test_batch_analysis()
        await test_edge_cases()
        print("\n✅ All tests completed!")
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 