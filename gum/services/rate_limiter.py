"""
Token Bucket Rate Limiter for Gumbo

Production-grade rate limiter implementing token bucket algorithm.
Prevents suggestion spam while allowing burst generation when needed.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
import threading


logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """
    Production-grade token bucket rate limiter for Gumbo suggestions.
    
    Allows burst generation while maintaining overall rate limits.
    Thread-safe and memory efficient.
    """
    
    def __init__(
        self,
        capacity: int = 1,
        refill_rate: float = 1.0 / 60.0,  # 1 token per minute by default
        refill_interval: float = 1.0  # Check every second
    ):
        """
        Initialize token bucket rate limiter.
        
        Args:
            capacity: Maximum number of tokens in bucket
            refill_rate: Tokens per second to add
            refill_interval: How often to refill tokens (seconds)
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        
        # Thread-safe token management
        self._lock = threading.RLock()
        self._tokens = float(capacity)
        self._last_refill = datetime.now(timezone.utc)
        
        # Background refill task
        self._refill_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        
        logger.info(f"TokenBucket initialized: capacity={capacity}, refill_rate={refill_rate:.4f}/sec")
    
    async def start(self):
        """Start the background refill task."""
        if self._refill_task is None or self._refill_task.done():
            self._shutdown_event.clear()
            self._refill_task = asyncio.create_task(self._refill_worker())
            logger.info("TokenBucket refill worker started")
    
    async def stop(self):
        """Stop the background refill task."""
        if self._refill_task and not self._refill_task.done():
            self._shutdown_event.set()
            try:
                await asyncio.wait_for(self._refill_task, timeout=2.0)
            except asyncio.TimeoutError:
                self._refill_task.cancel()
                try:
                    await self._refill_task
                except asyncio.CancelledError:
                    pass
            logger.info("TokenBucket refill worker stopped")
    
    async def _refill_worker(self):
        """Background worker to refill tokens periodically."""
        try:
            while not self._shutdown_event.is_set():
                self._refill_tokens()
                await asyncio.sleep(self.refill_interval)
        except asyncio.CancelledError:
            logger.info("TokenBucket refill worker cancelled")
        except Exception as e:
            logger.error(f"TokenBucket refill worker error: {e}")
    
    def _refill_tokens(self):
        """Refill tokens based on elapsed time (thread-safe)."""
        with self._lock:
            now = datetime.now(timezone.utc)
            elapsed = (now - self._last_refill).total_seconds()
            
            if elapsed > 0:
                tokens_to_add = elapsed * self.refill_rate
                self._tokens = min(self.capacity, self._tokens + tokens_to_add)
                self._last_refill = now
    
    async def acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens from the bucket.
        
        Args:
            tokens: Number of tokens to acquire
            
        Returns:
            True if tokens were acquired, False if rate limited
        """
        if tokens <= 0:
            return True
        
        self._refill_tokens()
        
        with self._lock:
            if self._tokens >= tokens:
                self._tokens -= tokens
                logger.debug(f"TokenBucket: acquired {tokens} tokens, {self._tokens:.2f} remaining")
                return True
            else:
                logger.info(f"TokenBucket: rate limited, need {tokens} tokens but only {self._tokens:.2f} available")
                return False
    
    async def get_wait_time(self) -> float:
        """
        Get estimated wait time until next token is available.
        
        Returns:
            Wait time in seconds
        """
        self._refill_tokens()
        
        with self._lock:
            if self._tokens >= 1:
                return 0.0
            
            # Calculate time needed to get at least 1 token
            tokens_needed = 1.0 - self._tokens
            wait_time = tokens_needed / self.refill_rate if self.refill_rate > 0 else float('inf')
            
            return max(0.0, wait_time)
    
    def get_status(self) -> dict:
        """
        Get current rate limiter status.
        
        Returns:
            Status dictionary with current state
        """
        self._refill_tokens()
        
        with self._lock:
            wait_time = 0.0
            if self._tokens < 1:
                tokens_needed = 1.0 - self._tokens
                wait_time = tokens_needed / self.refill_rate if self.refill_rate > 0 else float('inf')
            
            next_refill_at = self._last_refill + timedelta(seconds=1.0/self.refill_rate) if self.refill_rate > 0 else None
            
            return {
                "tokens_available": int(self._tokens),
                "tokens_capacity": self.capacity,
                "is_rate_limited": self._tokens < 1,
                "wait_time_seconds": max(0.0, wait_time),
                "next_refill_at": next_refill_at,
                "refill_rate_per_second": self.refill_rate
            }
    
    def reset(self):
        """Reset the rate limiter to full capacity."""
        with self._lock:
            self._tokens = float(self.capacity)
            self._last_refill = datetime.now(timezone.utc)
            logger.info("TokenBucket reset to full capacity")
    
    def __repr__(self):
        status = self.get_status()
        return (f"TokenBucketRateLimiter(capacity={self.capacity}, "
                f"tokens={status['tokens_available']}, "
                f"rate_limited={status['is_rate_limited']})")


class GumboRateLimiter:
    """
    Gumbo-specific rate limiter with production-grade features.
    
    Manages suggestion generation rate limiting with proper lifecycle management.
    """
    
    def __init__(self):
        """Initialize Gumbo rate limiter with default settings."""
        # 1 batch per minute, with burst capacity of 2
        self.token_bucket = TokenBucketRateLimiter(
            capacity=2,                    # Allow burst of 2 suggestion batches
            refill_rate=1.0 / 60.0,       # 1 token per minute
            refill_interval=5.0           # Check every 5 seconds
        )
        self._started = False
        logger.info("GumboRateLimiter initialized")
    
    async def start(self):
        """Start the rate limiter."""
        if not self._started:
            await self.token_bucket.start()
            self._started = True
            logger.info("GumboRateLimiter started")
    
    async def stop(self):
        """Stop the rate limiter."""
        if self._started:
            await self.token_bucket.stop()
            self._started = False
            logger.info("GumboRateLimiter stopped")
    
    async def can_generate_suggestions(self) -> bool:
        """
        Check if suggestion generation is allowed.
        
        Returns:
            True if suggestions can be generated, False if rate limited
        """
        return await self.token_bucket.acquire(tokens=1)
    
    async def get_wait_time(self) -> float:
        """Get estimated wait time until next suggestion batch is allowed."""
        return await self.token_bucket.get_wait_time()
    
    def get_status(self) -> dict:
        """Get current rate limit status."""
        return self.token_bucket.get_status()
    
    def reset(self):
        """Reset rate limiter (for testing/admin use)."""
        self.token_bucket.reset()
        logger.info("GumboRateLimiter reset")
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.stop()


# Global rate limiter instance (singleton pattern)
_global_rate_limiter: Optional[GumboRateLimiter] = None


async def get_rate_limiter() -> GumboRateLimiter:
    """
    Get the global Gumbo rate limiter instance.
    
    Returns:
        Initialized GumboRateLimiter instance
    """
    global _global_rate_limiter
    
    if _global_rate_limiter is None:
        _global_rate_limiter = GumboRateLimiter()
        await _global_rate_limiter.start()
    
    return _global_rate_limiter


async def shutdown_rate_limiter():
    """Shutdown the global rate limiter (for cleanup)."""
    global _global_rate_limiter
    
    if _global_rate_limiter is not None:
        await _global_rate_limiter.stop()
        _global_rate_limiter = None
        logger.info("Global GumboRateLimiter shutdown complete")
