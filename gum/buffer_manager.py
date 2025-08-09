"""
Smart Data Bundling Buffer Manager

This module implements a time-based buffering system that collects multiple frames/screenshots
over time windows (5-10 minutes) and then sends them as batches to AI for analysis.
This reduces API calls by 80%+ while improving accuracy through better context.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import List, Dict, Optional, Callable, Any
from datetime import datetime, timedelta


@dataclass
class BufferedFrame:
    """Represents a single frame in the buffer."""
    frame_data: str  # base64 encoded image
    timestamp: float
    event_type: str  # "move", "click", "scroll", "periodic"
    monitor_idx: int
    metadata: Dict[str, Any] = None


class BufferManager:
    """
    Manages time-based buffering of frames for batch AI analysis.
    
    Features:
    - Time-based buffers (5-10 minute windows)
    - Activity-based flush triggers
    - Size-based limits to prevent memory issues
    - Automatic cleanup and memory management
    """
    
    def __init__(
        self,
        buffer_minutes: int = 5,
        max_buffer_size: int = 150,
        flush_on_activity: bool = True,
        activity_threshold: int = 3,
        debug: bool = False
    ):
        """
        Initialize the buffer manager.
        
        Args:
            buffer_minutes: How long to collect frames before flushing (default: 5)
            max_buffer_size: Maximum frames to store before forcing flush (default: 15)
            flush_on_activity: Whether to flush on significant activity (default: True)
            activity_threshold: Number of events to trigger activity-based flush (default: 3)
            debug: Enable debug logging (default: False)
        """
        self.buffer_minutes = buffer_minutes
        self.buffer_seconds = buffer_minutes * 60
        self.max_buffer_size = max_buffer_size
        self.flush_on_activity = flush_on_activity
        self.activity_threshold = activity_threshold
        self.debug = debug
        
        # Buffer storage
        self.buffers: Dict[int, deque] = {}  # monitor_idx -> deque of BufferedFrame
        self.buffer_start_times: Dict[int, float] = {}  # monitor_idx -> start time
        self.buffer_timers: Dict[int, asyncio.TimerHandle] = {}
        
        # Activity tracking
        self.recent_events: Dict[int, int] = {}  # monitor_idx -> event count
        self.last_activity_flush: Dict[int, float] = {}
        
        # Callbacks
        self.on_flush_callback: Optional[Callable] = None
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
        
        # Logging
        self.logger = logging.getLogger("BufferManager")
        if debug:
            self.logger.setLevel(logging.DEBUG)
    
    def set_flush_callback(self, callback: Callable):
        """Set the callback function to be called when buffers are flushed."""
        self.on_flush_callback = callback
    
    async def add_frame(
        self, 
        frame_data: str, 
        event_type: str, 
        monitor_idx: int, 
        metadata: Dict[str, Any] = None
    ) -> bool:
        """
        Add a frame to the buffer.
        
        Args:
            frame_data: Base64 encoded image data
            event_type: Type of event ("move", "click", "scroll", "periodic")
            monitor_idx: Monitor index where event occurred
            metadata: Additional metadata for the frame
            
        Returns:
            bool: True if frame was added, False if buffer was flushed
        """
        async with self._lock:
            # Initialize buffer for this monitor if needed
            if monitor_idx not in self.buffers:
                self.buffers[monitor_idx] = deque()
                self.buffer_start_times[monitor_idx] = time.time()
                self.recent_events[monitor_idx] = 0
                self.last_activity_flush[monitor_idx] = 0
                
                # Schedule timer for this buffer
                self._schedule_buffer_timer(monitor_idx)
                
                if self.debug:
                    self.logger.debug(f"Initialized buffer for monitor {monitor_idx}")
            
            # Create buffered frame
            buffered_frame = BufferedFrame(
                frame_data=frame_data,
                timestamp=time.time(),
                event_type=event_type,
                monitor_idx=monitor_idx,
                metadata=metadata or {}
            )
            
            # Add to buffer
            self.buffers[monitor_idx].append(buffered_frame)
            self.recent_events[monitor_idx] += 1
            
            if self.debug:
                self.logger.debug(f"Added frame to monitor {monitor_idx} buffer (size: {len(self.buffers[monitor_idx])})")
            
            # Check if we should flush based on size or activity
            should_flush = False
            
            # Size-based flush
            if len(self.buffers[monitor_idx]) >= self.max_buffer_size:
                if self.debug:
                    self.logger.debug(f"Buffer size limit reached for monitor {monitor_idx}")
                should_flush = True
            
            # Activity-based flush
            elif (self.flush_on_activity and 
                  self.recent_events[monitor_idx] >= self.activity_threshold and
                  time.time() - self.last_activity_flush[monitor_idx] > 30):  # Prevent spam
                if self.debug:
                    self.logger.debug(f"Activity threshold reached for monitor {monitor_idx}")
                should_flush = True
            
            if should_flush:
                await self._flush_buffer(monitor_idx)
                return False  # Frame was flushed, not just added
            
            return True  # Frame was added to buffer
    
    def _schedule_buffer_timer(self, monitor_idx: int):
        """Schedule a timer to flush the buffer after the time window."""
        try:
            loop = asyncio.get_running_loop()
            
            # Cancel existing timer if any
            if monitor_idx in self.buffer_timers and self.buffer_timers[monitor_idx]:
                self.buffer_timers[monitor_idx].cancel()
            
            # Schedule new timer using a safer approach
            def timer_callback():
                # Create task in the event loop
                asyncio.create_task(self._flush_buffer(monitor_idx))
            
            self.buffer_timers[monitor_idx] = loop.call_later(
                self.buffer_seconds,
                timer_callback
            )
            
            if self.debug:
                self.logger.debug(f"Scheduled buffer timer for monitor {monitor_idx} in {self.buffer_seconds} seconds")
        except Exception as e:
            self.logger.error(f"Error scheduling timer for monitor {monitor_idx}: {e}")
    
    async def _flush_buffer(self, monitor_idx: int) -> List[BufferedFrame]:
        """
        Flush the buffer for a specific monitor.
        
        Args:
            monitor_idx: Monitor index to flush
            
        Returns:
            List[BufferedFrame]: The frames that were flushed
        """
        # Don't acquire lock if we're already holding it
        if self._lock.locked():
            # We're already in a locked context, process directly
            return await self._flush_buffer_internal(monitor_idx)
        else:
            async with self._lock:
                return await self._flush_buffer_internal(monitor_idx)
    
    async def _flush_buffer_internal(self, monitor_idx: int) -> List[BufferedFrame]:
        """Internal flush method without lock acquisition."""
        if monitor_idx not in self.buffers or not self.buffers[monitor_idx]:
            return []
        
        # Get frames from buffer
        frames = list(self.buffers[monitor_idx])
        self.buffers[monitor_idx].clear()
        
        # Reset activity tracking
        self.recent_events[monitor_idx] = 0
        self.last_activity_flush[monitor_idx] = time.time()
        
        # Cancel timer
        if monitor_idx in self.buffer_timers and self.buffer_timers[monitor_idx]:
            self.buffer_timers[monitor_idx].cancel()
            self.buffer_timers[monitor_idx] = None
        
        # Reset start time
        self.buffer_start_times[monitor_idx] = time.time()
        
        # Schedule new timer
        self._schedule_buffer_timer(monitor_idx)
        
        if self.debug:
            self.logger.debug(f"Flushed {len(frames)} frames from monitor {monitor_idx} buffer")
        
        # Call flush callback if set
        if self.on_flush_callback and frames:
            try:
                await self.on_flush_callback(monitor_idx, frames)
            except Exception as e:
                self.logger.error(f"Error in flush callback: {e}")
        
        return frames
    
    async def flush_all_buffers(self) -> Dict[int, List[BufferedFrame]]:
        """
        Flush all buffers immediately.
        
        Returns:
            Dict[int, List[BufferedFrame]]: All flushed frames by monitor
        """
        async with self._lock:
            all_flushed = {}
            for monitor_idx in list(self.buffers.keys()):
                frames = await self._flush_buffer(monitor_idx)
                if frames:
                    all_flushed[monitor_idx] = frames
            
            if self.debug:
                total_frames = sum(len(frames) for frames in all_flushed.values())
                self.logger.debug(f"Flushed all buffers: {total_frames} total frames")
            
            return all_flushed
    
    def get_buffer_status(self) -> Dict[str, Any]:
        """Get the current status of all buffers."""
        async def _get_status():
            async with self._lock:
                status = {
                    "total_buffers": len(self.buffers),
                    "total_frames": sum(len(buf) for buf in self.buffers.values()),
                    "buffers": {}
                }
                
                for monitor_idx, buffer in self.buffers.items():
                    start_time = self.buffer_start_times.get(monitor_idx, 0)
                    elapsed = time.time() - start_time if start_time else 0
                    
                    status["buffers"][monitor_idx] = {
                        "frame_count": len(buffer),
                        "elapsed_seconds": elapsed,
                        "recent_events": self.recent_events.get(monitor_idx, 0),
                        "has_timer": monitor_idx in self.buffer_timers and self.buffer_timers[monitor_idx] is not None
                    }
                
                return status
        
        # Run the async function in the current event loop
        try:
            loop = asyncio.get_running_loop()
            return asyncio.run_coroutine_threadsafe(_get_status(), loop).result()
        except RuntimeError:
            # No event loop running, create a new one
            return asyncio.run(_get_status())
    
    async def cleanup(self):
        """Clean up resources and flush any remaining buffers."""
        async with self._lock:
            # Cancel all timers
            for timer in self.buffer_timers.values():
                if timer:
                    timer.cancel()
            
            # Flush all buffers
            await self.flush_all_buffers()
            
            # Clear all data
            self.buffers.clear()
            self.buffer_start_times.clear()
            self.buffer_timers.clear()
            self.recent_events.clear()
            self.last_activity_flush.clear()
            
            if self.debug:
                self.logger.debug("Buffer manager cleaned up")


def create_batch_prompt(frames: List[BufferedFrame], time_span_minutes: float) -> str:
    """
    Create a prompt for batch analysis of multiple frames.
    
    Args:
        frames: List of buffered frames to analyze
        time_span_minutes: Time span covered by the frames in minutes
        
    Returns:
        str: Formatted prompt for batch analysis
    """
    # Create timestamp info
    timestamps = []
    event_types = []
    
    for frame in frames:
        dt = datetime.fromtimestamp(frame.timestamp)
        timestamps.append(f"{dt.strftime('%H:%M:%S')} ({frame.event_type})")
        event_types.append(frame.event_type)
    
    # Count event types
    event_counts = {}
    for event_type in event_types:
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    
    event_summary = ", ".join([f"{count} {event_type}s" for event_type, count in event_counts.items()])
    
    prompt = f"""
Analyze these {len(frames)} sequential frames captured over {time_span_minutes:.1f} minutes.

TIMELINE: {", ".join(timestamps)}
ACTIVITY SUMMARY: {event_summary}

Focus on:
1. User behavior patterns and workflow changes
2. Application usage and transitions between programs
3. Significant events or state changes in the interface
4. Overall activity context and productivity patterns
5. Mouse movement patterns and interaction frequency
6. Any notable patterns or anomalies in user behavior

Provide a comprehensive analysis of the user's activity during this period, identifying key behaviors, workflow patterns, and any significant changes or events.
"""
    
    return prompt.strip()

def create_pillar_specific_prompt(frames: List[BufferedFrame], time_span_minutes: float, pillar: str, user_name: str = "the user") -> str:
    """
    Create a pillar-specific prompt for batch analysis.
    
    Args:
        frames: List of buffered frames to analyze
        time_span_minutes: Time span covered by the frames in minutes
        pillar: Which pillar to analyze ("daily", "patterns", "preferences")
        user_name: Name of the user being analyzed
        
    Returns:
        str: Formatted pillar-specific prompt
    """
    # Import the pillar prompts
    from gum.prompts.gum import get_pillar_prompt
    
    # Get the base pillar prompt
    base_prompt = get_pillar_prompt(pillar, user_name, time_span_minutes)
    
    # Create timestamp info
    timestamps = []
    event_types = []
    
    for frame in frames:
        dt = datetime.fromtimestamp(frame.timestamp)
        timestamps.append(f"{dt.strftime('%H:%M:%S')} ({frame.event_type})")
        event_types.append(frame.event_type)
    
    # Count event types
    event_counts = {}
    for event_type in event_types:
        event_counts[event_type] = event_counts.get(event_type, 0) + 1
    
    event_summary = ", ".join([f"{count} {event_type}s" for event_type, count in event_counts.items()])
    
    # Create pillar-specific context
    pillar_context = {
        "daily": f"""
# CONTEXT: Analyzing {user_name}'s daily activities over {time_span_minutes:.1f} minutes
TIMELINE: {", ".join(timestamps)}
ACTIVITY SUMMARY: {event_summary}

Focus on WHAT {user_name} was working on, not HOW they interacted with it.
""",
        "patterns": f"""
# CONTEXT: Analyzing {user_name}'s work patterns over {time_span_minutes:.1f} minutes
TIMELINE: {", ".join(timestamps)}
ACTIVITY SUMMARY: {event_summary}

Balance between WHAT {user_name} worked on and HOW they worked.
""",
        "preferences": f"""
# CONTEXT: Learning about {user_name}'s preferences over {time_span_minutes:.1f} minutes
TIMELINE: {", ".join(timestamps)}
ACTIVITY SUMMARY: {event_summary}

Focus on building understanding of {user_name}'s preferences and characteristics.
"""
    }
    
    # Combine base prompt with pillar-specific context
    full_prompt = f"""{base_prompt}

{pillar_context.get(pillar, "")}

Please analyze the provided screen captures and provide insights specific to {pillar} understanding.
"""
    
    return full_prompt.strip() 