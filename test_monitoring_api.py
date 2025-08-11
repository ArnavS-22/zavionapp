#!/usr/bin/env python3
"""
Test script for the GUM Monitoring API endpoints.
Run this script to test the monitoring start, stop, and status endpoints.
"""

import requests
import time
import json
from typing import Dict, Any

class MonitoringAPITester:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def test_endpoint(self, method: str, endpoint: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Test a specific endpoint and return the response."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method.upper() == "GET":
                response = self.session.get(url)
            elif method.upper() == "POST":
                response = self.session.post(url, json=data)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            print(f"\n{method.upper()} {endpoint}")
            print(f"Status Code: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                print("Response:")
                print(json.dumps(result, indent=2))
                return result
            else:
                print(f"Error Response: {response.text}")
                return {"error": response.text, "status_code": response.status_code}
                
        except requests.exceptions.ConnectionError:
            print(f"❌ Connection Error: Could not connect to {url}")
            print("Make sure the backend is running on port 8001")
            return {"error": "Connection failed"}
        except Exception as e:
            print(f"❌ Error: {str(e)}")
            return {"error": str(e)}
    
    def run_tests(self):
        """Run a complete test suite of the monitoring endpoints."""
        print("🧪 Testing GUM Monitoring API Endpoints")
        print("=" * 50)
        
        # Test 1: Get initial status
        print("\n1️⃣ Testing GET /monitoring/status (initial)")
        initial_status = self.test_endpoint("GET", "/monitoring/status")
        
        # Test 2: Try to start monitoring
        print("\n2️⃣ Testing POST /monitoring/start")
        start_data = {
            "user_name": "Test User",
            "model": "gpt-4o-mini",
            "debug": True
        }
        start_result = self.test_endpoint("POST", "/monitoring/start", start_data)
        
        # Test 3: Check status after starting
        if start_result.get("success"):
            print("\n3️⃣ Testing GET /monitoring/status (after start)")
            time.sleep(2)  # Wait a moment for process to start
            status_after_start = self.test_endpoint("GET", "/monitoring/status")
            
            # Test 4: Try to start monitoring again (should fail)
            print("\n4️⃣ Testing POST /monitoring/start (should fail - already running)")
            duplicate_start = self.test_endpoint("POST", "/monitoring/start", start_data)
            
            # Test 5: Stop monitoring
            print("\n5️⃣ Testing POST /monitoring/stop")
            stop_result = self.test_endpoint("POST", "/monitoring/stop")
            
            # Test 6: Check final status
            if stop_result.get("success"):
                print("\n6️⃣ Testing GET /monitoring/status (after stop)")
                time.sleep(1)  # Wait a moment for process to stop
                final_status = self.test_endpoint("GET", "/monitoring/status")
        else:
            print("\n⚠️  Skipping remaining tests due to start failure")
        
        print("\n" + "=" * 50)
        print("✅ Testing completed!")
    
    def interactive_mode(self):
        """Run an interactive testing mode."""
        print("🎮 Interactive Monitoring API Testing Mode")
        print("Commands: start, stop, status, quit")
        print("=" * 50)
        
        while True:
            try:
                command = input("\nEnter command: ").strip().lower()
                
                if command == "quit":
                    break
                elif command == "start":
                    user_name = input("Enter user name: ").strip()
                    model = input("Enter AI model (default: gpt-4o-mini): ").strip() or "gpt-4o-mini"
                    debug = input("Enable debug mode? (y/n, default: n): ").strip().lower() == "y"
                    
                    data = {
                        "user_name": user_name,
                        "model": model,
                        "debug": debug
                    }
                    self.test_endpoint("POST", "/monitoring/start", data)
                    
                elif command == "stop":
                    self.test_endpoint("POST", "/monitoring/stop")
                    
                elif command == "status":
                    self.test_endpoint("GET", "/monitoring/status")
                    
                else:
                    print("❌ Unknown command. Use: start, stop, status, or quit")
                    
            except KeyboardInterrupt:
                print("\n\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"❌ Error: {str(e)}")

def main():
    """Main function to run the tests."""
    import sys
    
    # Check if backend is accessible
    try:
        response = requests.get("http://localhost:8001/health", timeout=5)
        if response.status_code != 200:
            print("❌ Backend health check failed")
            sys.exit(1)
    except requests.exceptions.RequestException:
        print("❌ Could not connect to backend. Make sure it's running on port 8001")
        print("Run: python start_gum.py")
        sys.exit(1)
    
    tester = MonitoringAPITester()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--interactive":
        tester.interactive_mode()
    else:
        tester.run_tests()

if __name__ == "__main__":
    main()
