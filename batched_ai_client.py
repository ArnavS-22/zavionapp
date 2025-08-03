#!/usr/bin/env python3
"""
Batched AI Client for Reduced API Calls

This client stores observations and makes bulk API calls at regular intervals
to reduce the frequency of API calls while maintaining functionality.
"""

import asyncio
import logging
import time
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import threading
from queue import Queue
import pickle

# Import the original unified client for fallback
from unified_ai_client import UnifiedAIClient

logger = logging.getLogger(__name__)


class BatchType(Enum):
    """Types of batch operations."""
    TEXT = "text"
    VISION = "vision"
    MIXED = "mixed"


@dataclass
class BatchedRequest:
    """Represents a single request to be batched."""
    id: str
    batch_type: BatchType
    messages: Optional[List[Dict[str, Any]]] = None
    text_prompt: Optional[str] = None
    base64_image: Optional[str] = None
    max_tokens: int = 1000
    temperature: float = 0.1
    timestamp: float = None
    priority: int = 1  # Higher number = higher priority
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


@dataclass
class BatchResult:
    """Result of a batch operation."""
    batch_id: str
    request_id: str
    content: str
    success: bool
    error: Optional[str] = None
    processing_time: float = 0.0


class BatchedAIClient:
    """
    AI client that batches requests to reduce API calls.
    
    Features:
    - Stores requests in memory and on disk for persistence
    - Processes batches at regular intervals (hourly by default)
    - Supports priority queuing
    - Provides immediate fallback for urgent requests
    - Maintains compatibility with existing API
    """
    
    def __init__(self,
                 batch_interval_hours: float = 1.0,
                 max_batch_size: int = 50,
                 storage_dir: str = "~/.cache/gum/batches",
                 enable_fallback: bool = True,
                 fallback_threshold_seconds: int = 300):  # 5 minutes
        """
        Initialize the batched AI client.
        
        Args:
            batch_interval_hours: How often to process batches (in hours)
            max_batch_size: Maximum number of requests per batch
            storage_dir: Directory to store batch data
            enable_fallback: Whether to use immediate API calls for urgent requests
            fallback_threshold_seconds: Age threshold for fallback (seconds)
        """
        self.batch_interval_hours = batch_interval_hours
        self.max_batch_size = max_batch_size
        self.storage_dir = Path(storage_dir).expanduser()
        self.enable_fallback = enable_fallback
        self.fallback_threshold_seconds = fallback_threshold_seconds
        
        # Create storage directory
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize storage
        self.pending_requests: List[BatchedRequest] = []
        self.results_cache: Dict[str, BatchResult] = {}
        self.batch_counter = 0
        
        # Threading for background processing
        self.processing_thread = None
        self.shutdown_event = threading.Event()
        self.request_queue = Queue()
        
        # Initialize the original client for fallback
        self.fallback_client = None
        if self.enable_fallback:
            self.fallback_client = UnifiedAIClient()
        
        # Start background processing
        self._start_background_processing()
        
        logger.info(f"Batched AI Client initialized:")
        logger.info(f"   Batch interval: {batch_interval_hours} hours")
        logger.info(f"   Max batch size: {max_batch_size}")
        logger.info(f"   Storage directory: {self.storage_dir}")
        logger.info(f"   Fallback enabled: {enable_fallback}")
        logger.info(f"   Fallback threshold: {fallback_threshold_seconds} seconds")
    
    def _start_background_processing(self):
        """Start the background processing thread."""
        self.processing_thread = threading.Thread(
            target=self._background_processor,
            daemon=True
        )
        self.processing_thread.start()
        logger.info("Background processing thread started")
    
    def _background_processor(self):
        """Background thread that processes batches at regular intervals."""
        last_batch_time = time.time()
        logger.info(f"Background processor started with batch interval: {self.batch_interval_hours} hours")
        
        while not self.shutdown_event.is_set():
            try:
                current_time = time.time()
                
                # Check if it's time for a batch
                if current_time - last_batch_time >= self.batch_interval_hours * 3600:
                    logger.info(f"Processing batch after {current_time - last_batch_time:.1f}s")
                    asyncio.run(self._process_batch())
                    last_batch_time = current_time
                
                # Process any urgent requests from queue
                try:
                    while not self.request_queue.empty():
                        request = self.request_queue.get_nowait()
                        self.pending_requests.append(request)
                except:
                    pass
                
                # Sleep for a short interval
                time.sleep(10)  # Check every 10 seconds
                
            except Exception as e:
                logger.error(f"Error in background processor: {e}")
                time.sleep(30)  # Wait longer on error
    
    async def _process_batch(self):
        """Process the current batch of requests."""
        if not self.pending_requests:
            logger.info("No pending requests to process")
            return
        
        logger.info(f"Processing batch of {len(self.pending_requests)} requests")
        
        # Group requests by type
        text_requests = [req for req in self.pending_requests if req.batch_type == BatchType.TEXT]
        vision_requests = [req for req in self.pending_requests if req.batch_type == BatchType.VISION]
        
        # Process text requests
        if text_requests:
            await self._process_text_batch(text_requests)
        
        # Process vision requests
        if vision_requests:
            await self._process_vision_batch(vision_requests)
        
        # Clear processed requests
        self.pending_requests = []
        
        # Save state
        self._save_state()
        
        logger.info("Batch processing completed")
    
    async def _process_text_batch(self, requests: List[BatchedRequest]):
        """Process a batch of text requests."""
        if not self.fallback_client:
            logger.error("No fallback client available for text processing")
            return
        
        logger.info(f"Processing {len(requests)} text requests")
        
        # Group by similar parameters
        batches = self._group_text_requests(requests)
        
        for batch in batches:
            try:
                # Use the first request's parameters as template
                template = batch[0]
                
                # Create a combined prompt
                combined_messages = self._combine_text_messages(batch)
                
                # Make the API call
                start_time = time.time()
                response = await self.fallback_client.text_completion(
                    messages=combined_messages,
                    max_tokens=template.max_tokens,
                    temperature=template.temperature
                )
                processing_time = time.time() - start_time
                
                # Split response and distribute to individual requests
                responses = self._split_text_response(response, len(batch))
                
                # Create results
                for i, request in enumerate(batch):
                    result = BatchResult(
                        batch_id=f"text_batch_{self.batch_counter}",
                        request_id=request.id,
                        content=responses[i] if i < len(responses) else "Error: No response generated",
                        success=True,
                        processing_time=processing_time
                    )
                    self.results_cache[request.id] = result
                
                self.batch_counter += 1
                
            except Exception as e:
                logger.error(f"Error processing text batch: {e}")
                # Mark all requests in batch as failed
                for request in batch:
                    result = BatchResult(
                        batch_id=f"text_batch_{self.batch_counter}",
                        request_id=request.id,
                        content="",
                        success=False,
                        error=str(e),
                        processing_time=0.0
                    )
                    self.results_cache[request.id] = result
    
    async def _process_vision_batch(self, requests: List[BatchedRequest]):
        """Process a batch of vision requests."""
        if not self.fallback_client:
            logger.error("No fallback client available for vision processing")
            return
        
        logger.info(f"Processing {len(requests)} vision requests")
        
        # Process vision requests individually (they can't be easily batched)
        for request in requests:
            try:
                start_time = time.time()
                response = await self.fallback_client.vision_completion(
                    text_prompt=request.text_prompt,
                    base64_image=request.base64_image,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature
                )
                processing_time = time.time() - start_time
                
                result = BatchResult(
                    batch_id=f"vision_batch_{self.batch_counter}",
                    request_id=request.id,
                    content=response,
                    success=True,
                    processing_time=processing_time
                )
                self.results_cache[request.id] = result
                
            except Exception as e:
                logger.error(f"Error processing vision request {request.id}: {e}")
                result = BatchResult(
                    batch_id=f"vision_batch_{self.batch_counter}",
                    request_id=request.id,
                    content="",
                    success=False,
                    error=str(e),
                    processing_time=0.0
                )
                self.results_cache[request.id] = result
        
        self.batch_counter += 1
    
    def _group_text_requests(self, requests: List[BatchedRequest]) -> List[List[BatchedRequest]]:
        """Group text requests by similar parameters."""
        # Simple grouping by max_tokens and temperature
        groups = {}
        
        for request in requests:
            key = (request.max_tokens, request.temperature)
            if key not in groups:
                groups[key] = []
            groups[key].append(request)
        
        # Split large groups to respect max_batch_size
        batches = []
        for group in groups.values():
            for i in range(0, len(group), self.max_batch_size):
                batches.append(group[i:i + self.max_batch_size])
        
        return batches
    
    def _combine_text_messages(self, requests: List[BatchedRequest]) -> List[Dict[str, Any]]:
        """Combine multiple text requests into a single prompt."""
        combined_content = "Please process the following requests separately:\n\n"
        
        for i, request in enumerate(requests):
            # Extract the user message content
            user_message = None
            for message in request.messages:
                if message.get("role") == "user":
                    user_message = message.get("content", "")
                    break
            
            if user_message:
                combined_content += f"Request {i+1}:\n{user_message}\n\n"
        
        combined_content += "Please provide separate responses for each request, numbered accordingly."
        
        return [{"role": "user", "content": combined_content}]
    
    def _split_text_response(self, response: str, num_requests: int) -> List[str]:
        """Split a combined response into individual responses."""
        # Simple splitting by numbered responses
        responses = []
        
        # Look for numbered responses (1. 2. 3. etc.)
        import re
        parts = re.split(r'\n\s*\d+\.\s*', response)
        
        if len(parts) > 1:
            # Remove the first part (it's before the first number)
            parts = parts[1:]
            
            # Clean up each part
            for part in parts:
                cleaned = part.strip()
                if cleaned:
                    responses.append(cleaned)
        else:
            # Fallback: split by paragraphs
            paragraphs = response.split('\n\n')
            for paragraph in paragraphs:
                cleaned = paragraph.strip()
                if cleaned:
                    responses.append(cleaned)
        
        # Ensure we have enough responses
        while len(responses) < num_requests:
            responses.append("Response not available")
        
        return responses[:num_requests]
    
    def _save_state(self):
        """Save current state to disk."""
        try:
            state = {
                'pending_requests': [asdict(req) for req in self.pending_requests],
                'results_cache': {k: asdict(v) for k, v in self.results_cache.items()},
                'batch_counter': self.batch_counter
            }
            
            state_file = self.storage_dir / "batch_state.pkl"
            with open(state_file, 'wb') as f:
                pickle.dump(state, f)
            
            logger.debug("Batch state saved to disk")
            
        except Exception as e:
            logger.error(f"Error saving batch state: {e}")
    
    def _load_state(self):
        """Load state from disk."""
        try:
            state_file = self.storage_dir / "batch_state.pkl"
            if state_file.exists():
                with open(state_file, 'rb') as f:
                    state = pickle.load(f)
                
                # Reconstruct objects
                self.pending_requests = [BatchedRequest(**req) for req in state.get('pending_requests', [])]
                self.results_cache = {k: BatchResult(**v) for k, v in state.get('results_cache', {}).items()}
                self.batch_counter = state.get('batch_counter', 0)
                
                logger.info(f"Loaded {len(self.pending_requests)} pending requests from disk")
                
        except Exception as e:
            logger.error(f"Error loading batch state: {e}")
    
    async def text_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 1000,
        temperature: float = 0.1,
        urgent: bool = False
    ) -> str:
        """
        Submit a text completion request for batching.
        
        Args:
            messages: List of message dictionaries
            max_tokens: Maximum tokens to generate
            temperature: Temperature for generation
            urgent: If True, use immediate fallback instead of batching
            
        Returns:
            The AI response content as a string
        """
        request_id = f"text_{int(time.time() * 1000)}"
        
        # Check if request is urgent or fallback is disabled
        if urgent or not self.enable_fallback:
            if self.fallback_client:
                logger.info("Using immediate fallback for urgent text request")
                return await self.fallback_client.text_completion(
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
            else:
                raise RuntimeError("No fallback client available for urgent request")
        
        # Create batched request
        request = BatchedRequest(
            id=request_id,
            batch_type=BatchType.TEXT,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        # Add to pending requests
        self.pending_requests.append(request)
        
        # Wait for result (with timeout)
        # Use 2x the batch interval as timeout to allow for processing time
        timeout = int(self.batch_interval_hours * 3600 * 2)
        return await self._wait_for_result(request_id, timeout=timeout)
    
    async def vision_completion(
        self,
        text_prompt: str,
        base64_image: str,
        max_tokens: int = 1000,
        temperature: float = 0.1,
        urgent: bool = False
    ) -> str:
        """
        Submit a vision completion request for batching.
        
        Args:
            text_prompt: Text prompt for the image analysis
            base64_image: Base64 encoded image data
            max_tokens: Maximum tokens to generate
            temperature: Temperature for generation
            urgent: If True, use immediate fallback instead of batching
            
        Returns:
            The AI response content as a string
        """
        request_id = f"vision_{int(time.time() * 1000)}"
        
        # Check if request is urgent or fallback is disabled
        if urgent or not self.enable_fallback:
            if self.fallback_client:
                logger.info("Using immediate fallback for urgent vision request")
                return await self.fallback_client.vision_completion(
                    text_prompt=text_prompt,
                    base64_image=base64_image,
                    max_tokens=max_tokens,
                    temperature=temperature
                )
            else:
                raise RuntimeError("No fallback client available for urgent request")
        
        # Create batched request
        request = BatchedRequest(
            id=request_id,
            batch_type=BatchType.VISION,
            text_prompt=text_prompt,
            base64_image=base64_image,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        # Add to pending requests
        self.pending_requests.append(request)
        
        # Wait for result (with timeout)
        # Use 2x the batch interval as timeout to allow for processing time
        timeout = int(self.batch_interval_hours * 3600 * 2)
        return await self._wait_for_result(request_id, timeout=timeout)
    
    async def _wait_for_result(self, request_id: str, timeout: int = 60) -> str:
        """Wait for a result to become available."""
        start_time = time.time()
        logger.info(f"Waiting for request {request_id} with timeout {timeout}s")
        
        while time.time() - start_time < timeout:
            if request_id in self.results_cache:
                result = self.results_cache[request_id]
                
                if result.success:
                    return result.content
                else:
                    raise RuntimeError(f"Request failed: {result.error}")
            
            # Check if request is too old for fallback
            if self.enable_fallback and self.fallback_client:
                for req in self.pending_requests:
                    if req.id == request_id:
                        age = time.time() - req.timestamp
                        if age > self.fallback_threshold_seconds:
                            logger.info(f"Request {request_id} is {age:.1f}s old, using fallback")
                            
                            # Remove from pending and use fallback
                            self.pending_requests = [r for r in self.pending_requests if r.id != request_id]
                            
                            if req.batch_type == BatchType.TEXT:
                                return await self.fallback_client.text_completion(
                                    messages=req.messages,
                                    max_tokens=req.max_tokens,
                                    temperature=req.temperature
                                )
                            elif req.batch_type == BatchType.VISION:
                                return await self.fallback_client.vision_completion(
                                    text_prompt=req.text_prompt,
                                    base64_image=req.base64_image,
                                    max_tokens=req.max_tokens,
                                    temperature=req.temperature
                                )
            
            await asyncio.sleep(0.1)
        
        raise TimeoutError(f"Request {request_id} timed out after {timeout} seconds")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the batched client."""
        return {
            'pending_requests': len(self.pending_requests),
            'cached_results': len(self.results_cache),
            'batch_counter': self.batch_counter,
            'batch_interval_hours': self.batch_interval_hours,
            'max_batch_size': self.max_batch_size,
            'enable_fallback': self.enable_fallback
        }
    
    def shutdown(self):
        """Shutdown the batched client."""
        logger.info("Shutting down batched AI client")
        self.shutdown_event.set()
        
        if self.processing_thread:
            self.processing_thread.join(timeout=5)
        
        # Save final state
        self._save_state()
        
        logger.info("Batched AI client shutdown complete")


# Global batched client instance
_batched_client = None

async def get_batched_client() -> BatchedAIClient:
    """Get the global batched AI client instance."""
    global _batched_client
    if _batched_client is None:
        # Read configuration from environment variables
        import os
        batch_interval_hours = float(os.getenv('BATCH_INTERVAL_HOURS', '1.0'))
        max_batch_size = int(os.getenv('MAX_BATCH_SIZE', '50'))
        enable_fallback = os.getenv('ENABLE_FALLBACK', 'true').lower() == 'true'
        
        _batched_client = BatchedAIClient(
            batch_interval_hours=batch_interval_hours,
            max_batch_size=max_batch_size,
            enable_fallback=enable_fallback
        )
    return _batched_client


# Convenience functions that match the original unified client interface
async def batched_text_completion(
    messages: List[Dict[str, Any]],
    max_tokens: int = 1000,
    temperature: float = 0.1,
    urgent: bool = False
) -> str:
    """
    Convenience function for batched text completion.
    
    Args:
        messages: List of message dictionaries
        max_tokens: Maximum tokens to generate
        temperature: Temperature for generation
        urgent: If True, use immediate API call instead of batching
        
    Returns:
        The AI response content as a string
    """
    client = await get_batched_client()
    return await client.text_completion(messages, max_tokens, temperature, urgent)


async def batched_vision_completion(
    text_prompt: str,
    base64_image: str,
    max_tokens: int = 1000,
    temperature: float = 0.1,
    urgent: bool = False
) -> str:
    """
    Convenience function for batched vision completion.
    
    Args:
        text_prompt: Text prompt for the image analysis
        base64_image: Base64 encoded image data
        max_tokens: Maximum tokens to generate
        temperature: Temperature for generation
        urgent: If True, use immediate API call instead of batching
        
    Returns:
        The AI response content as a string
    """
    client = await get_batched_client()
    return await client.vision_completion(text_prompt, base64_image, max_tokens, temperature, urgent)


async def test_batched_client():
    """Test the batched AI client."""
    print("Testing Batched AI Client...")
    
    client = await get_batched_client()
    
    # Test text completion
    try:
        print("Testing batched text completion...")
        response = await batched_text_completion(
            messages=[{"role": "user", "content": "Say 'Batched text working'"}],
            max_tokens=20,
            temperature=0.0
        )
        print(f"Batched Text Success: {response}")
    except Exception as e:
        print(f"Batched Text Failed: {e}")
    
    # Test urgent text completion (immediate)
    try:
        print("Testing urgent text completion...")
        response = await batched_text_completion(
            messages=[{"role": "user", "content": "Say 'Urgent text working'"}],
            max_tokens=20,
            temperature=0.0,
            urgent=True
        )
        print(f"Urgent Text Success: {response}")
    except Exception as e:
        print(f"Urgent Text Failed: {e}")
    
    # Test vision completion
    try:
        print("Testing batched vision completion...")
        
        # Create a simple test image
        import base64
        from io import BytesIO
        from PIL import Image
        
        img = Image.new('RGB', (50, 50), color='red')
        buffer = BytesIO()
        img.save(buffer, format='JPEG', quality=85)
        test_base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        response = await batched_vision_completion(
            text_prompt="What color is this image? Just say the color.",
            base64_image=test_base64_image,
            max_tokens=10,
            temperature=0.0
        )
        print(f"Batched Vision Success: {response}")
    except Exception as e:
        print(f"Batched Vision Failed: {e}")
    
    # Show stats
    stats = client.get_stats()
    print(f"\nClient Stats: {stats}")


if __name__ == "__main__":
    # Set up logging for testing
    logging.basicConfig(level=logging.INFO)
    
    asyncio.run(test_batched_client())
    print("\nBatched AI Client testing completed!") 