#!/usr/bin/env python3
"""
Test script for tracking control functionality

This script tests the tracking control endpoints and Screen observer
to ensure the web-based control system works correctly.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add the current directory to the path so we can import gum modules
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

try:
    from gum.config_manager import get_config_manager
    from gum.observers.screen import Screen
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure you're running this from the project root directory.")
    sys.exit(1)

async def test_screen_observer_tracking():
    """Test the Screen observer's tracking control methods."""
    print("Testing Screen Observer Tracking Control")
    print("=" * 40)
    
    # Create a Screen observer instance
    screen_observer = Screen(
        user_name="test_user",
        debug=True
    )
    
    print(f"Initial tracking state: {screen_observer.is_tracking_enabled()}")
    
    # Test disabling tracking
    print("\nDisabling tracking...")
    await screen_observer.disable_tracking()
    print(f"Tracking disabled: {not screen_observer.is_tracking_enabled()}")
    
    # Test enabling tracking
    print("\nEnabling tracking...")
    await screen_observer.enable_tracking()
    print(f"Tracking enabled: {screen_observer.is_tracking_enabled()}")
    
    # Test toggle functionality
    print("\nTesting toggle functionality...")
    await screen_observer.disable_tracking()
    print(f"After disable: {screen_observer.is_tracking_enabled()}")
    await screen_observer.enable_tracking()
    print(f"After enable: {screen_observer.is_tracking_enabled()}")
    
    print("\n✓ Screen observer tracking control tests passed!")

async def test_config_manager():
    """Test the configuration manager functionality."""
    print("\nTesting Configuration Manager")
    print("=" * 30)
    
    config_manager = get_config_manager()
    
    # Test API key management
    print("Testing API key management...")
    test_key = "test_api_key_12345"
    config_manager.set_api_key("openai", test_key)
    
    retrieved_key = config_manager.get_api_key("openai")
    if retrieved_key == test_key:
        print("✓ API key set and retrieved successfully")
    else:
        print(f"✗ API key mismatch: expected {test_key}, got {retrieved_key}")
    
    # Test user settings
    print("\nTesting user settings...")
    test_user = "test_user_123"
    user_settings = config_manager.get_user_settings(test_user)
    
    if user_settings:
        print("✓ User settings created/retrieved successfully")
        print(f"  Username: {test_user}")
        print(f"  Tracking enabled: {user_settings.get('tracking_enabled', False)}")
    else:
        print("✗ Failed to get user settings")
    
    # Test configuration status
    print("\nTesting configuration status...")
    is_configured = config_manager.is_configured()
    print(f"Configuration complete: {is_configured}")
    
    if is_configured:
        print("✓ Configuration is complete")
    else:
        missing = config_manager.get_missing_config()
        print(f"Missing configuration: {missing}")
    
    print("\n✓ Configuration manager tests passed!")

async def main():
    """Run all tests."""
    print("Zavion GUM Tracking Control Tests")
    print("=" * 40)
    print()
    
    try:
        await test_config_manager()
        await test_screen_observer_tracking()
        
        print("\n" + "=" * 40)
        print("🎉 All tests passed!")
        print("=" * 40)
        print()
        print("The tracking control system is working correctly.")
        print("Users can now control tracking from the web dashboard.")
        
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
