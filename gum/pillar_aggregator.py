"""
Production-Grade Three-Pillar Data Aggregation System

This module provides intelligent aggregation functions for the three-pillar system:
1. Timeline Builder - Creates chronological activity timelines
2. User Profile Builder - Accumulates user preferences and characteristics
3. Productivity Insights - Analyzes patterns for actionable optimization
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, and_, desc
from gum.models import Proposition, Observation

logger = logging.getLogger(__name__)


class PillarAggregator:
    """Production-grade aggregator for three-pillar system data."""
    
    def __init__(self, session):
        self.session = session
    
    async def build_daily_timeline(self, target_date: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Build a chronological timeline of activities for a specific day.
        
        Args:
            target_date: Date to build timeline for (defaults to today)
            
        Returns:
            Dict containing timeline entries, summary, and metadata
        """
        if target_date is None:
            target_date = datetime.now().date()
        
        try:
            # Get timeline propositions for the target date
            start_date = datetime.combine(target_date, datetime.min.time())
            end_date = start_date + timedelta(days=1)
            
            stmt = select(Proposition).where(
                and_(
                    Proposition.analysis_type == "timeline",
                    Proposition.created_at >= start_date,
                    Proposition.created_at < end_date
                )
            ).order_by(Proposition.created_at)
            
            result = await self.session.execute(stmt)
            timeline_props = result.scalars().all()
            
            # Parse and aggregate timeline entries
            timeline_entries = []
            total_activities = 0
            applications_used = set()
            
            for prop in timeline_props:
                try:
                    # Parse JSON structured data
                    if prop.structured_data:
                        data = json.loads(prop.structured_data)
                        if "timeline_entries" in data:
                            for entry in data["timeline_entries"]:
                                timeline_entries.append({
                                    "start_time": entry.get("start_time", ""),
                                    "end_time": entry.get("end_time", ""),
                                    "activity": entry.get("activity", ""),
                                    "application": entry.get("application", ""),
                                    "details": entry.get("details", ""),
                                    "confidence": entry.get("confidence", prop.confidence),
                                    "timestamp": prop.created_at.isoformat()
                                })
                                applications_used.add(entry.get("application", ""))
                                total_activities += 1
                    else:
                        # Fallback to text parsing for non-structured data
                        timeline_entries.append({
                            "start_time": prop.created_at.strftime("%H:%M"),
                            "end_time": "",
                            "activity": prop.text[:100] + "..." if len(prop.text) > 100 else prop.text,
                            "application": "Unknown",
                            "details": prop.reasoning or "",
                            "confidence": prop.confidence,
                            "timestamp": prop.created_at.isoformat()
                        })
                        total_activities += 1
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse timeline data: {e}")
                    continue
            
            # Sort timeline entries by start time
            timeline_entries.sort(key=lambda x: x.get("start_time", ""))
            
            # Generate summary
            summary = {
                "date": target_date.isoformat(),
                "total_activities": total_activities,
                "applications_used": list(applications_used),
                "total_tracked_time": len(timeline_entries) * 15,  # Estimate 15 min per entry
                "activity_distribution": self._calculate_activity_distribution(timeline_entries)
            }
            
            return {
                "timeline": timeline_entries,
                "summary": summary,
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "data_source": "pillar_timeline_analysis",
                    "confidence_range": [
                        min([e.get("confidence", 0) for e in timeline_entries], default=0),
                        max([e.get("confidence", 0) for e in timeline_entries], default=0)
                    ]
                }
            }
            
        except Exception as e:
            logger.error(f"Error building daily timeline: {e}")
            return {
                "timeline": [],
                "summary": {"error": f"Failed to build timeline: {str(e)}"},
                "metadata": {"generated_at": datetime.now().isoformat()}
            }
    
    async def build_user_profile(self, days_back: int = 30) -> Dict[str, Any]:
        """
        Build comprehensive user profile by aggregating preference data.
        
        Args:
            days_back: Number of days to look back for preferences
            
        Returns:
            Dict containing user preferences, traits, and characteristics
        """
        try:
            # Get preference propositions from the last N days
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            stmt = select(Proposition).where(
                and_(
                    Proposition.analysis_type == "preference",
                    Proposition.created_at >= cutoff_date,
                    Proposition.confidence >= 6  # Only high-confidence preferences
                )
            ).order_by(desc(Proposition.confidence))
            
            result = await self.session.execute(stmt)
            preference_props = result.scalars().all()
            
            # Aggregate preferences by category
            preferences = {
                "tool_preferences": [],
                "work_style": [],
                "interface_preferences": [],
                "communication_style": [],
                "content_preferences": []
            }
            
            overall_confidence = []
            
            for prop in preference_props:
                try:
                    # Parse JSON structured data
                    if prop.structured_data:
                        data = json.loads(prop.structured_data)
                        if "preferences" in data:
                            for pref in data["preferences"]:
                                category = pref.get("category", "other")
                                if category in preferences:
                                    preferences[category].append({
                                        "preference": pref.get("preference", ""),
                                        "evidence": pref.get("evidence", ""),
                                        "confidence": pref.get("confidence", prop.confidence),
                                        "persistence": pref.get("persistence", ""),
                                        "learned_at": prop.created_at.isoformat()
                                    })
                                    overall_confidence.append(pref.get("confidence", prop.confidence))
                    else:
                        # Fallback for non-structured data
                        category = self._categorize_preference_text(prop.text)
                        preferences[category].append({
                            "preference": prop.text,
                            "evidence": prop.reasoning or "",
                            "confidence": prop.confidence,
                            "persistence": "observed",
                            "learned_at": prop.created_at.isoformat()
                        })
                        overall_confidence.append(prop.confidence)
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse preference data: {e}")
                    continue
            
            # Remove duplicates and sort by confidence
            for category in preferences:
                preferences[category] = self._deduplicate_preferences(preferences[category])
                preferences[category].sort(key=lambda x: x.get("confidence", 0), reverse=True)
            
            # Generate profile summary
            profile_summary = {
                "total_preferences": sum(len(prefs) for prefs in preferences.values()),
                "average_confidence": sum(overall_confidence) / len(overall_confidence) if overall_confidence else 0,
                "learning_period_days": days_back,
                "most_confident_category": max(preferences.keys(), 
                    key=lambda k: sum(p.get("confidence", 0) for p in preferences[k]) / max(len(preferences[k]), 1)
                ) if any(preferences.values()) else "none"
            }
            
            return {
                "preferences": preferences,
                "summary": profile_summary,
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "data_source": "pillar_preference_analysis",
                    "confidence_range": [
                        min(overall_confidence, default=0),
                        max(overall_confidence, default=0)
                    ]
                }
            }
            
        except Exception as e:
            logger.error(f"Error building user profile: {e}")
            return {
                "preferences": {},
                "summary": {"error": f"Failed to build user profile: {str(e)}"},
                "metadata": {"generated_at": datetime.now().isoformat()}
            }
    
    async def build_productivity_insights(self, days_back: int = 7) -> Dict[str, Any]:
        """
        Build actionable productivity insights from pattern analysis data.
        
        Args:
            days_back: Number of days to analyze for patterns
            
        Returns:
            Dict containing productivity insights, suggestions, and metrics
        """
        try:
            # Get productivity propositions from the last N days
            cutoff_date = datetime.now() - timedelta(days=days_back)
            
            stmt = select(Proposition).where(
                and_(
                    Proposition.analysis_type == "productivity",
                    Proposition.created_at >= cutoff_date,
                    Proposition.confidence >= 5  # Include medium-confidence insights
                )
            ).order_by(desc(Proposition.confidence))
            
            result = await self.session.execute(stmt)
            productivity_props = result.scalars().all()
            
            # Aggregate insights by type
            insights = {
                "focus_patterns": [],
                "distractions": [],
                "tool_effectiveness": [],
                "time_management": [],
                "workflow_optimization": []
            }
            
            suggestions = []
            overall_confidence = []
            
            for prop in productivity_props:
                try:
                    # Parse JSON structured data
                    if prop.structured_data:
                        data = json.loads(prop.structured_data)
                        if "insights" in data:
                            for insight in data["insights"]:
                                insight_type = insight.get("type", "other")
                                
                                insight_data = {
                                    "insight": insight.get("insight", ""),
                                    "evidence": insight.get("evidence", ""),
                                    "suggestion": insight.get("suggestion", ""),
                                    "impact": insight.get("impact", "medium"),
                                    "confidence": insight.get("confidence", prop.confidence),
                                    "identified_at": prop.created_at.isoformat()
                                }
                                
                                if insight_type in insights:
                                    insights[insight_type].append(insight_data)
                                
                                # Add to suggestions if actionable
                                if insight.get("suggestion"):
                                    suggestions.append({
                                        "suggestion": insight.get("suggestion", ""),
                                        "category": insight_type,
                                        "impact": insight.get("impact", "medium"),
                                        "confidence": insight.get("confidence", prop.confidence),
                                        "priority": self._calculate_priority(insight.get("impact", "medium"), insight.get("confidence", prop.confidence))
                                    })
                                
                                overall_confidence.append(insight.get("confidence", prop.confidence))
                    else:
                        # Fallback for non-structured data
                        insight_type = self._categorize_productivity_text(prop.text)
                        insights[insight_type].append({
                            "insight": prop.text,
                            "evidence": prop.reasoning or "",
                            "suggestion": "",
                            "impact": "medium",
                            "confidence": prop.confidence,
                            "identified_at": prop.created_at.isoformat()
                        })
                        overall_confidence.append(prop.confidence)
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse productivity data: {e}")
                    continue
            
            # Sort suggestions by priority
            suggestions.sort(key=lambda x: x.get("priority", 0), reverse=True)
            
            # Generate productivity summary
            productivity_summary = {
                "total_insights": sum(len(insights_list) for insights_list in insights.values()),
                "actionable_suggestions": len(suggestions),
                "average_confidence": sum(overall_confidence) / len(overall_confidence) if overall_confidence else 0,
                "analysis_period_days": days_back,
                "top_optimization_area": max(insights.keys(),
                    key=lambda k: len(insights[k])
                ) if any(insights.values()) else "none",
                "high_impact_suggestions": len([s for s in suggestions if s.get("impact") == "high"])
            }
            
            return {
                "insights": insights,
                "suggestions": suggestions[:10],  # Top 10 suggestions
                "summary": productivity_summary,
                "metadata": {
                    "generated_at": datetime.now().isoformat(),
                    "data_source": "pillar_productivity_analysis",
                    "confidence_range": [
                        min(overall_confidence, default=0),
                        max(overall_confidence, default=0)
                    ]
                }
            }
            
        except Exception as e:
            logger.error(f"Error building productivity insights: {e}")
            return {
                "insights": {},
                "suggestions": [],
                "summary": {"error": f"Failed to build productivity insights: {str(e)}"},
                "metadata": {"generated_at": datetime.now().isoformat()}
            }
    
    def _calculate_activity_distribution(self, timeline_entries: List[Dict]) -> Dict[str, int]:
        """Calculate distribution of activities by application."""
        distribution = {}
        for entry in timeline_entries:
            app = entry.get("application", "Unknown")
            distribution[app] = distribution.get(app, 0) + 1
        return distribution
    
    def _categorize_preference_text(self, text: str) -> str:
        """Categorize preference text into appropriate category."""
        text_lower = text.lower()
        if any(word in text_lower for word in ["tool", "app", "software", "platform"]):
            return "tool_preferences"
        elif any(word in text_lower for word in ["style", "approach", "method", "way"]):
            return "work_style"
        elif any(word in text_lower for word in ["interface", "ui", "theme", "layout"]):
            return "interface_preferences"
        elif any(word in text_lower for word in ["communication", "message", "chat", "email"]):
            return "communication_style"
        else:
            return "content_preferences"
    
    def _categorize_productivity_text(self, text: str) -> str:
        """Categorize productivity text into appropriate category."""
        text_lower = text.lower()
        if any(word in text_lower for word in ["focus", "concentration", "attention"]):
            return "focus_patterns"
        elif any(word in text_lower for word in ["distraction", "interrupt", "disruption"]):
            return "distractions"
        elif any(word in text_lower for word in ["tool", "effective", "app", "software"]):
            return "tool_effectiveness"
        elif any(word in text_lower for word in ["time", "schedule", "break", "duration"]):
            return "time_management"
        else:
            return "workflow_optimization"
    
    def _deduplicate_preferences(self, preferences: List[Dict]) -> List[Dict]:
        """Remove duplicate preferences based on similarity."""
        unique_prefs = []
        seen_prefs = set()
        
        for pref in preferences:
            pref_key = pref.get("preference", "").lower()[:50]  # First 50 chars as key
            if pref_key not in seen_prefs:
                unique_prefs.append(pref)
                seen_prefs.add(pref_key)
        
        return unique_prefs
    
    def _calculate_priority(self, impact: str, confidence: int) -> int:
        """Calculate priority score for suggestions."""
        impact_weights = {"high": 3, "medium": 2, "low": 1}
        impact_weight = impact_weights.get(impact, 2)
        return impact_weight * confidence