import time
import threading
import logging
from collections import defaultdict, deque
from typing import Dict, Deque, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class RateLimitConfig:
    """Configuration for rate limiting"""
    max_requests: int
    window_seconds: int
    cleanup_interval: int = 300  # Cleanup every 5 minutes
    max_memory_entries: int = 10000  # Maximum entries to keep in memory

class ProductionRateLimiter:
    """Production-ready rate limiter with memory management and thread safety"""
    
    def __init__(self):
        # Thread-safe request tracking
        self._requests: Dict[str, Deque[float]] = defaultdict(lambda: deque())
        self._lock = threading.RLock()
        
        # Configuration storage
        self._configs: Dict[str, RateLimitConfig] = {}
        
        # Statistics for monitoring
        self._stats = {
            'total_requests': 0,
            'rate_limited_requests': 0,
            'cleanup_runs': 0,
            'last_cleanup': time.time()
        }
        
        # Start cleanup thread
        self._cleanup_thread = threading.Thread(target=self._cleanup_worker, daemon=True)
        self._cleanup_thread.start()
        
        logger.info("Production rate limiter initialized with automatic cleanup")
    
    def configure_endpoint(self, endpoint: str, max_requests: int, window_seconds: int, 
                          cleanup_interval: int = 300, max_memory_entries: int = 10000):
        """Configure rate limits for a specific endpoint"""
        self._configs[endpoint] = RateLimitConfig(
            max_requests=max_requests,
            window_seconds=window_seconds,
            cleanup_interval=cleanup_interval,
            max_memory_entries=max_memory_entries
        )
        logger.info(f"Configured rate limit for {endpoint}: {max_requests} requests per {window_seconds}s")
    
    def check_limit(self, endpoint: str, max_requests: Optional[int] = None, 
                   window_seconds: Optional[int] = None) -> bool:
        """Check if request is within limits with thread safety"""
        with self._lock:
            # Get configuration
            config = self._configs.get(endpoint)
            if config:
                max_requests = max_requests or config.max_requests
                window_seconds = window_seconds or config.window_seconds
            else:
                # Use provided values or defaults
                max_requests = max_requests or 100
                window_seconds = window_seconds or 60
            
            now = time.time()
            window_start = now - window_seconds
            
            # Get requests for this endpoint
            endpoint_requests = self._requests[endpoint]
            
            # Clean old requests for this endpoint
            while endpoint_requests and endpoint_requests[0] < window_start:
                endpoint_requests.popleft()
            
            # Check if limit exceeded
            if len(endpoint_requests) >= max_requests:
                self._stats['rate_limited_requests'] += 1
                logger.warning(f"Rate limit exceeded for {endpoint}: {len(endpoint_requests)}/{max_requests} requests in {window_seconds}s")
                return False
            
            # Add current request
            endpoint_requests.append(now)
            self._stats['total_requests'] += 1
            
            # Log high usage
            if len(endpoint_requests) >= max_requests * 0.8:
                logger.info(f"High usage for {endpoint}: {len(endpoint_requests)}/{max_requests} requests")
            
            return True
    
    def get_reset_time(self, endpoint: str, window_seconds: Optional[int] = None) -> float:
        """Get when the rate limit resets for an endpoint"""
        with self._lock:
            config = self._configs.get(endpoint)
            window_seconds = window_seconds or (config.window_seconds if config else 60)
            
            endpoint_requests = self._requests[endpoint]
            if not endpoint_requests:
                return 0
            
            return endpoint_requests[0] + window_seconds
    
    def get_remaining_requests(self, endpoint: str, max_requests: Optional[int] = None) -> int:
        """Get remaining requests allowed for an endpoint"""
        with self._lock:
            config = self._configs.get(endpoint)
            max_requests = max_requests or (config.max_requests if config else 100)
            
            endpoint_requests = self._requests[endpoint]
            return max(0, max_requests - len(endpoint_requests))
    
    def get_endpoint_stats(self, endpoint: str) -> Dict:
        """Get statistics for a specific endpoint"""
        with self._lock:
            config = self._configs.get(endpoint)
            endpoint_requests = self._requests[endpoint]
            
            return {
                'endpoint': endpoint,
                'current_requests': len(endpoint_requests),
                'max_requests': config.max_requests if config else 100,
                'window_seconds': config.window_seconds if config else 60,
                'remaining_requests': self.get_remaining_requests(endpoint),
                'reset_time': self.get_reset_time(endpoint),
                'is_limited': len(endpoint_requests) >= (config.max_requests if config else 100)
            }
    
    def get_global_stats(self) -> Dict:
        """Get global rate limiter statistics"""
        with self._lock:
            total_endpoints = len(self._requests)
            total_entries = sum(len(requests) for requests in self._requests.values())
            
            return {
                'total_requests': self._stats['total_requests'],
                'rate_limited_requests': self._stats['rate_limited_requests'],
                'cleanup_runs': self._stats['cleanup_runs'],
                'last_cleanup': self._stats['last_cleanup'],
                'total_endpoints': total_endpoints,
                'total_entries': total_entries,
                'rate_limit_percentage': (self._stats['rate_limited_requests'] / max(1, self._stats['total_requests'])) * 100
            }
    
    def _cleanup_worker(self):
        """Background worker for cleaning up old requests"""
        while True:
            try:
                time.sleep(60)  # Check every minute
                self._cleanup_old_requests()
            except Exception as e:
                logger.error(f"Error in cleanup worker: {e}")
    
    def _cleanup_old_requests(self):
        """Clean up old requests and enforce memory limits"""
        with self._lock:
            now = time.time()
            cleaned_endpoints = 0
            cleaned_requests = 0
            
            for endpoint, requests in list(self._requests.items()):
                config = self._configs.get(endpoint)
                if not config:
                    continue
                
                # Remove old requests
                window_start = now - config.window_seconds
                original_count = len(requests)
                
                while requests and requests[0] < window_start:
                    requests.popleft()
                
                cleaned_requests += original_count - len(requests)
                
                # Enforce memory limits
                if len(requests) > config.max_memory_entries:
                    # Keep only the most recent requests
                    excess = len(requests) - config.max_memory_entries
                    for _ in range(excess):
                        requests.popleft()
                    cleaned_requests += excess
                
                # Remove empty endpoints
                if not requests:
                    del self._requests[endpoint]
                    cleaned_endpoints += 1
            
            if cleaned_requests > 0 or cleaned_endpoints > 0:
                self._stats['cleanup_runs'] += 1
                self._stats['last_cleanup'] = now
                logger.info(f"Cleanup completed: {cleaned_requests} requests, {cleaned_endpoints} endpoints removed")
    
    def reset_endpoint(self, endpoint: str):
        """Reset rate limit for a specific endpoint"""
        with self._lock:
            if endpoint in self._requests:
                del self._requests[endpoint]
                logger.info(f"Reset rate limit for endpoint: {endpoint}")
    
    def reset_all(self):
        """Reset all rate limits"""
        with self._lock:
            self._requests.clear()
            logger.info("Reset all rate limits")

# Global instance with default configuration
rate_limiter = ProductionRateLimiter()

# Configure default endpoints
rate_limiter.configure_endpoint("/observations/video", 5, 300)  # 5 videos per 5 minutes
rate_limiter.configure_endpoint("/observations/text", 20, 60)   # 20 text submissions per minute
rate_limiter.configure_endpoint("/query", 30, 60)              # 30 queries per minute
rate_limiter.configure_endpoint("default", 100, 60)            # 100 requests per minute for other endpoints