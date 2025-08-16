#!/usr/bin/env python3
"""
Test script for GUM API Rate Limiting

This script tests the rate limiting implementation to ensure it works correctly
for all endpoints and provides proper feedback.
"""

import asyncio
import time
import requests
import json
from typing import Dict, List

class RateLimitTester:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = requests.Session()
        
    def test_endpoint(self, endpoint: str, method: str = "GET", data: Dict = None, 
                     expected_limit: int = None, expected_window: int = None) -> Dict:
        """Test rate limiting for a specific endpoint"""
        url = f"{self.base_url}{endpoint}"
        
        print(f"\n🧪 Testing {method} {endpoint}")
        print(f"   URL: {url}")
        
        results = {
            "endpoint": endpoint,
            "method": method,
            "requests_made": 0,
            "rate_limited_at": None,
            "rate_limit_headers": {},
            "response_times": [],
            "errors": []
        }
        
        # Make requests until we hit the rate limit
        while True:
            try:
                start_time = time.time()
                
                if method == "GET":
                    response = self.session.get(url)
                elif method == "POST":
                    response = self.session.post(url, json=data)
                else:
                    raise ValueError(f"Unsupported method: {method}")
                
                response_time = time.time() - start_time
                results["response_times"].append(response_time)
                results["requests_made"] += 1
                
                # Check for rate limit headers
                rate_limit_headers = {
                    "X-RateLimit-Limit": response.headers.get("X-RateLimit-Limit"),
                    "X-RateLimit-Remaining": response.headers.get("X-RateLimit-Remaining"),
                    "X-RateLimit-Reset": response.headers.get("X-RateLimit-Reset")
                }
                
                if not results["rate_limit_headers"]:
                    results["rate_limit_headers"] = rate_limit_headers
                
                print(f"   Request {results['requests_made']}: {response.status_code} "
                      f"(Remaining: {rate_limit_headers.get('X-RateLimit-Remaining', 'N/A')}) "
                      f"({response_time:.3f}s)")
                
                # Check if we hit the rate limit
                if response.status_code == 429:
                    results["rate_limited_at"] = results["requests_made"]
                    
                    # Parse rate limit info
                    try:
                        error_data = response.json()
                        retry_after = response.headers.get("Retry-After")
                        print(f"   🚫 Rate limited after {results['requests_made']} requests")
                        print(f"   📋 Retry-After: {retry_after}s")
                        print(f"   📄 Error: {error_data.get('detail', 'Unknown error')}")
                    except:
                        print(f"   🚫 Rate limited after {results['requests_made']} requests (no JSON response)")
                    
                    break
                
                # Small delay between requests
                time.sleep(0.1)
                
            except Exception as e:
                results["errors"].append(str(e))
                print(f"   ❌ Error: {e}")
                break
        
        # Validate results
        if expected_limit and results["rate_limited_at"]:
            if results["rate_limited_at"] != expected_limit:
                print(f"   ⚠️  Expected rate limit at {expected_limit}, but got {results['rate_limited_at']}")
            else:
                print(f"   ✅ Rate limit hit at expected count: {results['rate_limited_at']}")
        
        return results
    
    def test_all_endpoints(self) -> Dict:
        """Test rate limiting for all configured endpoints"""
        print("🚀 Starting Rate Limiting Tests")
        print("=" * 60)
        
        test_results = {
            "timestamp": time.time(),
            "base_url": self.base_url,
            "endpoints": {}
        }
        
        # Test endpoints with their expected limits
        endpoints_to_test = [
            {
                "endpoint": "/observations/text",
                "method": "POST",
                "data": {"content": "Test observation", "user_name": "test_user"},
                "expected_limit": 20
            },
            {
                "endpoint": "/query",
                "method": "POST", 
                "data": {"query": "test query", "limit": 5},
                "expected_limit": 30
            },
            {
                "endpoint": "/observations",
                "method": "GET",
                "expected_limit": 100
            },
            {
                "endpoint": "/propositions",
                "method": "GET", 
                "expected_limit": 100
            }
        ]
        
        for test_config in endpoints_to_test:
            try:
                results = self.test_endpoint(
                    endpoint=test_config["endpoint"],
                    method=test_config["method"],
                    data=test_config.get("data"),
                    expected_limit=test_config.get("expected_limit")
                )
                test_results["endpoints"][test_config["endpoint"]] = results
                
                # Wait between endpoint tests to avoid interference
                time.sleep(2)
                
            except Exception as e:
                print(f"❌ Failed to test {test_config['endpoint']}: {e}")
                test_results["endpoints"][test_config["endpoint"]] = {
                    "error": str(e),
                    "endpoint": test_config["endpoint"]
                }
        
        return test_results
    
    def test_admin_endpoints(self) -> Dict:
        """Test admin endpoints for rate limiting"""
        print("\n🔧 Testing Admin Endpoints")
        print("-" * 40)
        
        admin_results = {}
        
        # Test rate limit statistics endpoint
        try:
            print("📊 Testing /admin/rate-limits")
            response = self.session.get(f"{self.base_url}/admin/rate-limits")
            
            if response.status_code == 200:
                stats = response.json()
                admin_results["stats"] = stats
                print(f"   ✅ Stats endpoint working")
                print(f"   📈 Total requests: {stats.get('global_stats', {}).get('total_requests', 0)}")
                print(f"   🚫 Rate limited: {stats.get('global_stats', {}).get('rate_limited_requests', 0)}")
            else:
                print(f"   ❌ Stats endpoint failed: {response.status_code}")
                admin_results["stats"] = {"error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            print(f"   ❌ Stats endpoint error: {e}")
            admin_results["stats"] = {"error": str(e)}
        
        # Test rate limit reset endpoint
        try:
            print("🔄 Testing /admin/rate-limits/reset")
            response = self.session.post(f"{self.base_url}/admin/rate-limits/reset")
            
            if response.status_code == 200:
                reset_data = response.json()
                admin_results["reset"] = reset_data
                print(f"   ✅ Reset endpoint working: {reset_data.get('message', 'Unknown')}")
            else:
                print(f"   ❌ Reset endpoint failed: {response.status_code}")
                admin_results["reset"] = {"error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            print(f"   ❌ Reset endpoint error: {e}")
            admin_results["reset"] = {"error": str(e)}
        
        return admin_results
    
    def generate_report(self, test_results: Dict, admin_results: Dict) -> str:
        """Generate a comprehensive test report"""
        report = []
        report.append("# GUM Rate Limiting Test Report")
        report.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Base URL: {self.base_url}")
        report.append("")
        
        # Summary
        total_tests = len(test_results["endpoints"])
        successful_tests = sum(1 for r in test_results["endpoints"].values() 
                             if "rate_limited_at" in r and r["rate_limited_at"] is not None)
        
        report.append("## Summary")
        report.append(f"- Total endpoints tested: {total_tests}")
        report.append(f"- Successful rate limiting: {successful_tests}")
        report.append(f"- Success rate: {(successful_tests/total_tests)*100:.1f}%")
        report.append("")
        
        # Endpoint details
        report.append("## Endpoint Test Results")
        for endpoint, results in test_results["endpoints"].items():
            report.append(f"### {endpoint}")
            report.append(f"- Method: {results.get('method', 'N/A')}")
            report.append(f"- Requests made: {results.get('requests_made', 0)}")
            report.append(f"- Rate limited at: {results.get('rate_limited_at', 'Not hit')}")
            
            if results.get("rate_limit_headers"):
                headers = results["rate_limit_headers"]
                report.append(f"- Rate limit headers:")
                report.append(f"  - Limit: {headers.get('X-RateLimit-Limit', 'N/A')}")
                report.append(f"  - Remaining: {headers.get('X-RateLimit-Remaining', 'N/A')}")
                report.append(f"  - Reset: {headers.get('X-RateLimit-Reset', 'N/A')}")
            
            if results.get("errors"):
                report.append(f"- Errors: {', '.join(results['errors'])}")
            
            report.append("")
        
        # Admin endpoints
        report.append("## Admin Endpoints")
        if admin_results.get("stats"):
            report.append("### Rate Limit Statistics")
            if "error" in admin_results["stats"]:
                report.append(f"- Status: ❌ Error - {admin_results['stats']['error']}")
            else:
                report.append("- Status: ✅ Working")
                stats = admin_results["stats"]
                report.append(f"- Total requests: {stats.get('global_stats', {}).get('total_requests', 0)}")
                report.append(f"- Rate limited requests: {stats.get('global_stats', {}).get('rate_limited_requests', 0)}")
        
        if admin_results.get("reset"):
            report.append("### Rate Limit Reset")
            if "error" in admin_results["reset"]:
                report.append(f"- Status: ❌ Error - {admin_results['reset']['error']}")
            else:
                report.append("- Status: ✅ Working")
        
        return "\n".join(report)

def main():
    """Main test function"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test GUM API Rate Limiting")
    parser.add_argument("--url", default="http://localhost:8001", 
                       help="Base URL of the GUM API")
    parser.add_argument("--report", action="store_true",
                       help="Generate detailed report")
    
    args = parser.parse_args()
    
    print("🔍 GUM Rate Limiting Test Suite")
    print("=" * 50)
    
    tester = RateLimitTester(args.url)
    
    try:
        # Test all endpoints
        test_results = tester.test_all_endpoints()
        
        # Test admin endpoints
        admin_results = tester.test_admin_endpoints()
        
        # Generate report
        if args.report:
            report = tester.generate_report(test_results, admin_results)
            print("\n" + "=" * 60)
            print("📋 TEST REPORT")
            print("=" * 60)
            print(report)
            
            # Save report to file
            with open("rate_limit_test_report.md", "w") as f:
                f.write(report)
            print("\n💾 Report saved to rate_limit_test_report.md")
        
        print("\n✅ Rate limiting tests completed!")
        
    except KeyboardInterrupt:
        print("\n⏹️  Tests interrupted by user")
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")

if __name__ == "__main__":
    main()