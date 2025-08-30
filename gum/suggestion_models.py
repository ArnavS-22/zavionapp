"""
Gumbo Suggestion Models

Production-grade Pydantic models for the intelligent suggestion system.
Defines data structures for suggestions, SSE events, and utility scoring.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, validator


class SSEEventType(str, Enum):
    """Server-Sent Event types for real-time suggestion delivery."""
    SUGGESTIONS_AVAILABLE = "suggestions_available"
    SUGGESTION_BATCH = "suggestion_batch"
    HEARTBEAT = "heartbeat"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"


class UtilityScores(BaseModel):
    """Expected utility scoring components for suggestion filtering."""
    benefit: float = Field(..., ge=0, le=10, description="Expected benefit score (0-10)")
    false_positive_cost: float = Field(..., ge=0, le=10, description="Cost of false positive (0-10)")
    false_negative_cost: float = Field(..., ge=0, le=10, description="Cost of false negative (0-10)")
    decay: float = Field(..., ge=0, le=10, description="Time decay factor (0-10)")
    probability_useful: float = Field(..., ge=0, le=1, description="Probability suggestion is useful (0-1)")
    probability_false_positive: float = Field(..., ge=0, le=1, description="Probability of false positive (0-1)")
    probability_false_negative: float = Field(..., ge=0, le=1, description="Probability of false negative (0-1)")


class SuggestionData(BaseModel):
    """Individual suggestion with utility scoring and metadata."""
    title: str = Field(..., max_length=200, description="Short, actionable suggestion title")
    description: str = Field(..., max_length=1000, description="Detailed suggestion description")
    probability_useful: float = Field(..., ge=0, le=1, description="AI-estimated probability this suggestion is useful")
    rationale: str = Field(..., max_length=500, description="AI reasoning for this suggestion")
    category: str = Field(..., max_length=100, description="Suggestion category (e.g., 'productivity', 'workflow')")
    utility_scores: Optional[UtilityScores] = Field(None, description="Detailed utility scoring breakdown")
    expected_utility: Optional[float] = Field(None, description="Final expected utility score")
    
    @validator('title', 'description', 'rationale')
    def sanitize_text(cls, v):
        """Basic XSS protection - strip potential HTML/JS."""
        if not v:
            return v
        # Remove potential script tags and HTML
        import re
        v = re.sub(r'<[^>]*>', '', v)  # Remove HTML tags
        v = re.sub(r'javascript:', '', v, flags=re.IGNORECASE)  # Remove javascript:
        return v.strip()


class SuggestionBatch(BaseModel):
    """Batch of suggestions with metadata."""
    suggestions: List[SuggestionData] = Field(..., description="List of generated suggestions")
    trigger_proposition_id: int = Field(..., description="ID of proposition that triggered this batch")
    generated_at: datetime = Field(..., description="Timestamp when suggestions were generated")
    processing_time_seconds: float = Field(..., ge=0, description="Time taken to generate suggestions")
    context_propositions_used: int = Field(..., ge=0, description="Number of context propositions used")
    batch_id: str = Field(..., description="Unique identifier for this suggestion batch")


class SuggestionMetrics(BaseModel):
    """System health and performance metrics."""
    total_suggestions_generated: int = Field(..., ge=0)
    total_batches_processed: int = Field(..., ge=0)
    average_processing_time_seconds: float = Field(..., ge=0)
    last_batch_generated_at: Optional[datetime] = None
    rate_limit_hits_today: int = Field(..., ge=0)


class RateLimitStatus(BaseModel):
    """Rate limiter status information."""
    tokens_available: int = Field(..., ge=0)
    tokens_capacity: int = Field(..., ge=0)
    next_refill_at: datetime
    is_rate_limited: bool
    wait_time_seconds: float = Field(..., ge=0)


class SuggestionHealthResponse(BaseModel):
    """Health check response for suggestion system."""
    status: str = Field(..., description="Overall system status: 'healthy', 'degraded', 'unhealthy'")
    metrics: SuggestionMetrics
    rate_limit_status: RateLimitStatus
    last_error: Optional[str] = None
    uptime_seconds: float = Field(..., ge=0)


# SSE Event Data Models
class HeartbeatSSEData(BaseModel):
    """Heartbeat event data."""
    timestamp: datetime
    connections_active: int = Field(..., ge=0)


class RateLimitSSEData(BaseModel):
    """Rate limit event data."""
    wait_time_seconds: float = Field(..., ge=0)
    next_available_at: datetime
    message: str


class ErrorSSEData(BaseModel):
    """Error event data."""
    error_type: str
    message: str
    timestamp: datetime
    retry_after_seconds: Optional[float] = None


class SSEEvent(BaseModel):
    """Server-Sent Event wrapper."""
    event: SSEEventType
    data: Dict[str, Any]
    id: Optional[str] = None
    retry: Optional[int] = None  # Milliseconds
    
    def to_sse_format(self) -> str:
        """Convert to Server-Sent Events format."""
        lines = []
        
        if self.id:
            lines.append(f"id: {self.id}")
        if self.retry:
            lines.append(f"retry: {self.retry}")
            
        lines.append(f"event: {self.event}")
        
        # Convert data to JSON string
        import json
        data_json = json.dumps(self.data, default=str)
        lines.append(f"data: {data_json}")
        
        # Add empty line to end the event
        lines.append("")
        
        return "\n".join(lines)


# Context Retrieval Models
class ContextualProposition(BaseModel):
    """Proposition with similarity score for context retrieval."""
    id: int
    text: str
    reasoning: str
    confidence: float
    created_at: datetime
    similarity_score: float = Field(..., ge=0, le=1)


class ContextRetrievalResult(BaseModel):
    """Result of contextual proposition retrieval."""
    related_propositions: List[ContextualProposition]
    total_found: int
    retrieval_time_seconds: float
    semantic_query: str
    screen_content: Optional[str] = Field(None, description="Current screen content for enhanced context")