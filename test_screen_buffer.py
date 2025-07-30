#!/usr/bin/env python3
"""
Test script for Screen Observer Buffering System

This script tests the 10-minute buffer system implementation.
"""

import asyncio
import logging
import tempfile
import time
from pathlib import Path

# Add the gum directory to the path
import sys
sys.path.append('.')

from gum.observers.screen import Screen

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)

async def test_buffer_system():
    """Test the buffer system with a short timeout."""
    
    # Create a temporary directory for screenshots
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Using temporary directory: {temp_dir}")
        
        # Create screen observer with 10-second buffer for testing
        screen = Screen(
            screenshots_dir=temp_dir,
            debug=True,
            buffer_minutes=0.1,  # 6 seconds for testing
            history_k=5
        )
        
        print("Starting screen observer...")
        # Observer starts automatically when created
        # await screen.start()  # Remove this line
        
        # Wait a moment for initialization
        await asyncio.sleep(1)
        
        # Simulate some events by calling _add_to_buffer directly
        print("Simulating events...")
        
        # Create dummy image files
        dummy_before = Path(temp_dir) / "dummy_before.jpg"
        dummy_after = Path(temp_dir) / "dummy_after.jpg"
        
        # Create simple dummy files
        dummy_before.write_text("dummy before image")
        dummy_after.write_text("dummy after image")
        
        # Add multiple events to buffer
        for i in range(3):
            await screen._add_to_buffer(
                str(dummy_before),
                str(dummy_after),
                f"test_event_{i}",
                1
            )
            print(f"Added event {i+1} to buffer")
            await asyncio.sleep(0.5)
        
        # Check buffer status
        status = screen.get_buffer_status()
        print(f"Buffer status: {status}")
        
        # Wait for buffer processing (should happen after 6 seconds)
        print("Waiting for buffer processing...")
        await asyncio.sleep(8)
        
        # Check final status
        final_status = screen.get_buffer_status()
        print(f"Final buffer status: {final_status}")
        
        # Stop the observer
        print("Stopping screen observer...")
        await screen.stop()
        
        print("Test completed!")

async def test_immediate_processing_fallback():
    """Test that immediate processing still works as fallback."""
    
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"\nTesting immediate processing fallback...")
        
        screen = Screen(
            screenshots_dir=temp_dir,
            debug=True,
            buffer_minutes=10,  # Long buffer
            history_k=5
        )
        
        # Observer starts automatically when created
        # await screen.start()  # Remove this line
        await asyncio.sleep(1)
        
        # Test direct _process_and_emit call
        dummy_before = Path(temp_dir) / "fallback_before.jpg"
        dummy_after = Path(temp_dir) / "fallback_after.jpg"
        
        dummy_before.write_text("fallback before image")
        dummy_after.write_text("fallback after image")
        
        # This should add to buffer
        await screen._process_and_emit(
            str(dummy_before),
            str(dummy_after),
            "fallback_test",
            1
        )
        
        status = screen.get_buffer_status()
        print(f"Buffer status after fallback test: {status}")
        
        await screen.stop()
        print("Fallback test completed!")

async def main():
    """Run all tests."""
    print("=== Screen Observer Buffer System Test ===\n")
    
    try:
        await test_buffer_system()
        await test_immediate_processing_fallback()
        print("\n✅ All tests passed!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 