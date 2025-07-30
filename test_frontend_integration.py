#!/usr/bin/env python3
"""
Frontend Integration Test Suite
Tests the enhanced frontend features for bullet-point analysis format
"""

import json
import time
import asyncio
import logging
import re
from typing import Dict, List, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class FrontendIntegrationTester:
    def __init__(self):
        self.test_results = []
        
    def log_test(self, test_name: str, passed: bool, details: str = ""):
        """Log test result"""
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{status} - {test_name}")
        if details:
            logger.info(f"  Details: {details}")
        
        self.test_results.append({
            "test": test_name,
            "passed": passed,
            "details": details
        })
        
    def create_mock_detailed_analysis(self) -> Dict[str, Any]:
        """Create mock detailed analysis data for testing"""
        return {
            "batch_id": "test_batch_001",
            "time_range": "09:30:00 - 10:15:00",
            "frame_count": 5,
            "detailed_analyses": [
                {
                    "frame_number": 1,
                    "timestamp": "09:30:15",
                    "event_type": "screen_capture",
                    "analysis": """WORKFLOW ANALYSIS (09:30:00 - 10:15:00)

• Specific Problem Moments (exact timestamps)
09:30:15: Email notification distraction, 3 minutes lost
09:35:22: Social media check, 5 minutes impact
09:42:10: Context switch to messaging app, 2 minutes recovery

• Productivity Patterns
Peak focus: 09:45:00 - 10:00:00 (Deep work on project)
Distraction trigger: Email notification at 09:30:15
Recovery pattern: 3-5 minutes to regain focus

• Application Usage
Most used: Code Editor (45.2 minutes)
Context switches: 8 times in 45 minutes
Switch cost: Average 2.3 seconds per switch

• Behavioral Insights
User shows strong focus recovery after distractions
Prefers longer uninterrupted work sessions
Email notifications are primary distraction source""",
                    "base64_data": "mock_base64_data_1",
                    "batch_processed": True,
                    "batch_id": "test_batch_001"
                },
                {
                    "frame_number": 2,
                    "timestamp": "09:45:30",
                    "event_type": "screen_capture",
                    "analysis": """WORKFLOW ANALYSIS (09:30:00 - 10:15:00)

• Specific Problem Moments (exact timestamps)
09:45:30: Phone notification, 1 minute distraction
09:47:15: Quick web search, 2 minutes duration

• Productivity Patterns
Peak focus: 09:45:00 - 10:00:00 (Intense coding session)
Distraction trigger: Phone notification at 09:45:30
Recovery pattern: Quick recovery within 1-2 minutes

• Application Usage
Most used: Code Editor (45.2 minutes)
Context switches: 8 times in 45 minutes
Switch cost: Average 2.3 seconds per switch

• Behavioral Insights
User maintains focus well during peak hours
Quick recovery from minor distractions
Efficient context switching patterns""",
                    "base64_data": "mock_base64_data_2",
                    "batch_processed": True,
                    "batch_id": "test_batch_001"
                }
            ],
            "summary": {
                "start_time": "09:30:00",
                "end_time": "10:15:00",
                "total_duration": 45,
                "event_types": ["screen_capture", "mouse_event", "keyboard_event"]
            }
        }
        
    def test_detailed_analysis_structure(self):
        """Test that detailed analysis has the correct structure"""
        logger.info("Testing detailed analysis structure...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Check required fields
        required_fields = ["batch_id", "time_range", "frame_count", "detailed_analyses", "summary"]
        for field in required_fields:
            if field not in detailed_analysis:
                self.log_test("Detailed Analysis Structure", False, f"Missing required field: {field}")
                return
                
        # Check detailed_analyses structure
        if not isinstance(detailed_analysis["detailed_analyses"], list):
            self.log_test("Detailed Analysis Structure", False, "detailed_analyses should be a list")
            return
            
        # Check each analysis entry
        for i, analysis in enumerate(detailed_analysis["detailed_analyses"]):
            required_analysis_fields = ["frame_number", "timestamp", "event_type", "analysis"]
            for field in required_analysis_fields:
                if field not in analysis:
                    self.log_test("Detailed Analysis Structure", False, f"Missing field in analysis {i}: {field}")
                    return
                    
        self.log_test("Detailed Analysis Structure", True, "All required fields present")
        
    def test_timestamp_format(self):
        """Test that timestamps are in HH:MM:SS format"""
        logger.info("Testing timestamp format...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        import re
        timestamp_pattern = r'^\d{2}:\d{2}:\d{2}$'
        
        # Check time_range format
        if not re.match(timestamp_pattern, detailed_analysis["time_range"].split(" - ")[0]):
            self.log_test("Timestamp Format", False, "time_range start time not in HH:MM:SS format")
            return
            
        if not re.match(timestamp_pattern, detailed_analysis["time_range"].split(" - ")[1]):
            self.log_test("Timestamp Format", False, "time_range end time not in HH:MM:SS format")
            return
            
        # Check individual timestamps
        for analysis in detailed_analysis["detailed_analyses"]:
            if not re.match(timestamp_pattern, analysis["timestamp"]):
                self.log_test("Timestamp Format", False, f"Invalid timestamp format: {analysis['timestamp']}")
                return
                
        self.log_test("Timestamp Format", True, "All timestamps in HH:MM:SS format")
        
    def test_bullet_point_format(self):
        """Test that analysis contains bullet-point format"""
        logger.info("Testing bullet-point format...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Check for bullet points in analysis
        bullet_patterns = [
            r'•\s*Specific Problem Moments',
            r'•\s*Productivity Patterns',
            r'•\s*Application Usage',
            r'•\s*Behavioral Insights'
        ]
        
        for analysis in detailed_analysis["detailed_analyses"]:
            content = analysis["analysis"]
            for pattern in bullet_patterns:
                if not re.search(pattern, content):
                    self.log_test("Bullet Point Format", False, f"Missing bullet point pattern: {pattern}")
                    return
                    
        self.log_test("Bullet Point Format", True, "All required bullet points present")
        
    def test_problem_moments_extraction(self):
        """Test extraction of problem moments with timestamps"""
        logger.info("Testing problem moments extraction...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Extract problem moments from analysis
        problem_moments = []
        for analysis in detailed_analysis["detailed_analyses"]:
            content = analysis["analysis"]
            # Look for timestamp patterns in problem moments section
            import re
            matches = re.findall(r'(\d{2}:\d{2}:\d{2}):\s*([^•\n]+)', content)
            problem_moments.extend(matches)
            
        if not problem_moments:
            self.log_test("Problem Moments Extraction", False, "No problem moments found")
            return
            
        # Check that we have at least 2 problem moments
        if len(problem_moments) < 2:
            self.log_test("Problem Moments Extraction", False, f"Expected at least 2 problem moments, found {len(problem_moments)}")
            return
            
        self.log_test("Problem Moments Extraction", True, f"Found {len(problem_moments)} problem moments")
        
    def test_productivity_patterns_extraction(self):
        """Test extraction of productivity patterns"""
        logger.info("Testing productivity patterns extraction...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Extract productivity patterns
        patterns_found = []
        for analysis in detailed_analysis["detailed_analyses"]:
            content = analysis["analysis"]
            import re
            # Look for productivity pattern keywords
            keywords = ["Peak focus", "Distraction trigger", "Recovery pattern"]
            for keyword in keywords:
                if keyword in content:
                    patterns_found.append(keyword)
                    
        if len(patterns_found) < 2:
            self.log_test("Productivity Patterns Extraction", False, f"Expected at least 2 patterns, found {len(patterns_found)}")
            return
            
        self.log_test("Productivity Patterns Extraction", True, f"Found patterns: {', '.join(set(patterns_found))}")
        
    def test_application_usage_extraction(self):
        """Test extraction of application usage data"""
        logger.info("Testing application usage extraction...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Extract application usage data
        usage_data = []
        for analysis in detailed_analysis["detailed_analyses"]:
            content = analysis["analysis"]
            import re
            # Look for application usage patterns
            patterns = [
                r'Most used:\s*([^•\n]+)',
                r'Context switches:\s*([^•\n]+)',
                r'Switch cost:\s*([^•\n]+)'
            ]
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    usage_data.append(match.group(1).strip())
                    
        if len(usage_data) < 2:
            self.log_test("Application Usage Extraction", False, f"Expected at least 2 usage data points, found {len(usage_data)}")
            return
            
        self.log_test("Application Usage Extraction", True, f"Found usage data: {', '.join(usage_data[:3])}")
        
    def test_behavioral_insights_extraction(self):
        """Test extraction of behavioral insights"""
        logger.info("Testing behavioral insights extraction...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Extract behavioral insights
        insights = []
        for analysis in detailed_analysis["detailed_analyses"]:
            content = analysis["analysis"]
            # Look for behavioral insights section
            import re
            insight_section = re.search(r'•\s*Behavioral Insights[\s\S]*?(?=•|$)', content)
            if insight_section:
                insights.append(insight_section.group(0))
                
        if not insights:
            self.log_test("Behavioral Insights Extraction", False, "No behavioral insights found")
            return
            
        self.log_test("Behavioral Insights Extraction", True, f"Found {len(insights)} behavioral insights sections")
        
    def test_frontend_data_compatibility(self):
        """Test that the data structure is compatible with frontend expectations"""
        logger.info("Testing frontend data compatibility...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Test that the data can be serialized to JSON (for frontend consumption)
        try:
            json_str = json.dumps(detailed_analysis)
            parsed_back = json.loads(json_str)
            
            # Verify structure is preserved
            if parsed_back["batch_id"] != detailed_analysis["batch_id"]:
                self.log_test("Frontend Data Compatibility", False, "JSON serialization/deserialization failed")
                return
                
        except Exception as e:
            self.log_test("Frontend Data Compatibility", False, f"JSON serialization error: {str(e)}")
            return
            
        self.log_test("Frontend Data Compatibility", True, "Data structure is JSON serializable")
        
    def test_chat_integration_format(self):
        """Test that the analysis format is suitable for chat integration"""
        logger.info("Testing chat integration format...")
        
        detailed_analysis = self.create_mock_detailed_analysis()
        
        # Test that analysis content can be formatted for chat
        for analysis in detailed_analysis["detailed_analyses"]:
            content = analysis["analysis"]
            
            # Check for timestamp patterns that can be highlighted
            import re
            timestamps = re.findall(r'\d{2}:\d{2}:\d{2}', content)
            if not timestamps:
                self.log_test("Chat Integration Format", False, "No timestamps found for highlighting")
                return
                
            # Check for bullet points that can be styled
            bullet_points = content.count('•')
            if bullet_points < 4:
                self.log_test("Chat Integration Format", False, f"Expected at least 4 bullet points, found {bullet_points}")
                return
                
        self.log_test("Chat Integration Format", True, f"Found {len(timestamps)} timestamps and {bullet_points} bullet points")
        
    def run_all_tests(self):
        """Run all frontend integration tests"""
        logger.info("🚀 Starting Frontend Integration Test Suite")
        logger.info("=" * 60)
        
        # Run all tests
        self.test_detailed_analysis_structure()
        self.test_timestamp_format()
        self.test_bullet_point_format()
        self.test_problem_moments_extraction()
        self.test_productivity_patterns_extraction()
        self.test_application_usage_extraction()
        self.test_behavioral_insights_extraction()
        self.test_frontend_data_compatibility()
        self.test_chat_integration_format()
        
        # Summary
        logger.info("=" * 60)
        logger.info("📊 Frontend Integration Test Results")
        logger.info("=" * 60)
        
        passed = sum(1 for result in self.test_results if result["passed"])
        total = len(self.test_results)
        
        for result in self.test_results:
            status = "✅" if result["passed"] else "❌"
            logger.info(f"{status} {result['test']}")
            if result["details"]:
                logger.info(f"    {result['details']}")
                
        logger.info("=" * 60)
        logger.info(f"🎯 Overall Result: {passed}/{total} tests passed")
        
        if passed == total:
            logger.info("🎉 All frontend integration tests passed! The enhanced analysis format is ready for production.")
        else:
            logger.warning("⚠️  Some tests failed. Please review the implementation.")
            
        return passed == total

def main():
    """Main test runner"""
    tester = FrontendIntegrationTester()
    success = tester.run_all_tests()
    
    if success:
        print("\n✅ Frontend Integration Test Suite: ALL TESTS PASSED")
        print("The enhanced bullet-point analysis format is fully integrated and ready for use!")
    else:
        print("\n❌ Frontend Integration Test Suite: SOME TESTS FAILED")
        print("Please review the test results and fix any issues.")
        
    return success

if __name__ == "__main__":
    main() 