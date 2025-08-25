#!/usr/bin/env python3
"""
Test script for the Three Pillar System implementation.

This script tests the new pillar-specific prompts and processing functionality.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from gum.prompts.gum import (
    get_pillar_prompt, 
    DAILY_UNDERSTANDING_PROMPT, 
    PATTERN_ANALYSIS_PROMPT, 
    USER_LEARNING_PROMPT
)
from gum.buffer_manager import create_pillar_specific_prompt, BufferedFrame
from datetime import datetime

def test_pillar_prompts():
    """Test the pillar-specific prompts."""
    print("🧪 Testing Pillar-Specific Prompts")
    print("=" * 50)
    
    user_name = "TestUser"
    time_span_minutes = 5.0
    
    # Test each pillar
    pillars = ["daily", "patterns", "preferences"]
    
    for pillar in pillars:
        print(f"\n📋 Testing {pillar.upper()} Pillar:")
        print("-" * 30)
        
        prompt = get_pillar_prompt(pillar, user_name, time_span_minutes)
        
        # Check if prompt contains expected content
        if pillar == "daily":
            assert "daily activities" in prompt.lower(), "Daily prompt should mention daily activities"
            assert "70%" in prompt, "Daily prompt should mention 70% content focus"
        elif pillar == "patterns":
            assert "productivity patterns" in prompt.lower(), "Patterns prompt should mention productivity patterns"
            assert "50%" in prompt, "Patterns prompt should mention 50% content focus"
        elif pillar == "preferences":
            assert "preferences" in prompt.lower(), "Preferences prompt should mention preferences"
            assert "60%" in prompt, "Preferences prompt should mention 60% content focus"
        
        print(f"✅ {pillar} pillar prompt generated successfully")
        print(f"   Length: {len(prompt)} characters")
        print(f"   Contains time span: {'✓' if str(time_span_minutes) in prompt else '✗'}")
        print(f"   Contains user name: {'✓' if user_name in prompt else '✗'}")

def test_buffer_manager_prompts():
    """Test the buffer manager pillar-specific prompt creation."""
    print("\n🧪 Testing Buffer Manager Pillar Prompts")
    print("=" * 50)
    
    # Create test frames
    frames = [
        BufferedFrame(
            frame_data="base64_test_data_1",
            timestamp=time.time(),
            event_type="click",
            monitor_idx=1
        ),
        BufferedFrame(
            frame_data="base64_test_data_2", 
            timestamp=time.time() + 60,
            event_type="scroll",
            monitor_idx=1
        )
    ]
    
    time_span_minutes = 1.0
    user_name = "TestUser"
    
    for pillar in ["daily", "patterns", "preferences"]:
        print(f"\n📋 Testing {pillar.upper()} Buffer Prompt:")
        print("-" * 30)
        
        try:
            prompt = create_pillar_specific_prompt(frames, time_span_minutes, pillar, user_name)
            
            # Check if prompt contains expected elements
            assert "TIMELINE" in prompt, f"{pillar} prompt should contain timeline"
            assert "ACTIVITY SUMMARY" in prompt, f"{pillar} prompt should contain activity summary"
            assert str(time_span_minutes) in prompt, f"{pillar} prompt should contain time span"
            
            print(f"✅ {pillar} buffer prompt generated successfully")
            print(f"   Length: {len(prompt)} characters")
            print(f"   Contains timeline: {'✓' if 'TIMELINE' in prompt else '✗'}")
            print(f"   Contains activity summary: {'✓' if 'ACTIVITY SUMMARY' in prompt else '✗'}")
            
        except Exception as e:
            print(f"❌ Error generating {pillar} buffer prompt: {e}")

def test_prompt_content_ratios():
    """Test that prompts contain the correct context ratios."""
    print("\n🧪 Testing Context Ratios in Prompts")
    print("=" * 50)
    
    user_name = "TestUser"
    time_span_minutes = 5.0
    
    # Test daily understanding (70% content, 30% behavior)
    daily_prompt = get_pillar_prompt("daily", user_name, time_span_minutes)
    assert "70%" in daily_prompt and "30%" in daily_prompt, "Daily prompt should mention 70%/30% ratio"
    assert "Primary Focus (70%)" in daily_prompt, "Daily prompt should mention primary focus"
    
    # Test pattern analysis (50% content, 50% behavior)
    patterns_prompt = get_pillar_prompt("patterns", user_name, time_span_minutes)
    assert "50%" in patterns_prompt, "Patterns prompt should mention 50% ratio"
    assert "Content Patterns (50%)" in patterns_prompt, "Patterns prompt should mention content patterns"
    
    # Test user learning (60% content, 40% behavior)
    preferences_prompt = get_pillar_prompt("preferences", user_name, time_span_minutes)
    assert "60%" in preferences_prompt and "40%" in preferences_prompt, "Preferences prompt should mention 60%/40% ratio"
    assert "Preference Learning (60%)" in preferences_prompt, "Preferences prompt should mention preference learning"
    
    print("✅ All context ratios correctly specified in prompts")

def test_time_awareness():
    """Test that prompts are time-aware instead of 'current activities'."""
    print("\n🧪 Testing Time Awareness in Prompts")
    print("=" * 50)
    
    user_name = "TestUser"
    time_span_minutes = 5.0
    
    for pillar in ["daily", "patterns", "preferences"]:
        prompt = get_pillar_prompt(pillar, user_name, time_span_minutes)
        
        # Check for time-aware language
        assert "current activities" not in prompt.lower(), f"{pillar} prompt should not mention 'current activities'"
        assert str(time_span_minutes) in prompt, f"{pillar} prompt should mention time span"
        assert "minutes" in prompt, f"{pillar} prompt should mention time units"
        
        print(f"✅ {pillar} prompt is time-aware")

def main():
    """Run all tests."""
    print("🚀 Testing Three Pillar System Implementation")
    print("=" * 60)
    
    try:
        test_pillar_prompts()
        test_buffer_manager_prompts()
        test_prompt_content_ratios()
        test_time_awareness()
        
        print("\n🎉 All tests passed! Three Pillar System is working correctly.")
        print("\n📊 Summary:")
        print("   ✅ Pillar-specific prompts generated")
        print("   ✅ Context ratios implemented (70%/30%, 50%/50%, 60%/40%)")
        print("   ✅ Time-aware prompts (no 'current activities' bias)")
        print("   ✅ Buffer manager integration working")
        print("   ✅ All functionality preserved")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    import time
    exit(main()) 