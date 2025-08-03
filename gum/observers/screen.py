from __future__ import annotations
###############################################################################
# Imports                                                                     #
###############################################################################

# — Standard library —
import base64
import logging
import os
import sys
import time
from collections import deque
from typing import Any, Dict, Iterable, List, Optional

import asyncio

# — Third-party —
import mss
# Conditional import for macOS-specific Quartz module
try:
    if sys.platform == "darwin":
        import Quartz
    else:
        Quartz = None
except ImportError:
    Quartz = None

from PIL import Image
from pynput import mouse           # still synchronous
from shapely.geometry import box
from shapely.ops import unary_union

# — Local —
from .observer import Observer
from ..schemas import Update

# — OpenAI async client —
from openai import AsyncOpenAI

# — Local —
from gum.prompts.screen import TRANSCRIPTION_PROMPT, SUMMARY_PROMPT

###############################################################################
# Window‑geometry helpers                                                     #
###############################################################################


def _get_global_bounds() -> tuple[float, float, float, float]:
    """Return a bounding box enclosing **all** physical displays.

    Returns
    -------
    (min_x, min_y, max_x, max_y) tuple in Quartz global coordinates.
    """
    if Quartz is None:
        # Fallback for non-macOS systems - use mss to get monitor bounds
        with mss.mss() as sct:
            monitors = sct.monitors[1:]  # Skip the "all monitors" entry
            if not monitors:
                return 0, 0, 1920, 1080  # Default fallback
            
            min_x = min(mon["left"] for mon in monitors)
            min_y = min(mon["top"] for mon in monitors) 
            max_x = max(mon["left"] + mon["width"] for mon in monitors)
            max_y = max(mon["top"] + mon["height"] for mon in monitors)
            return min_x, min_y, max_x, max_y
    
    err, ids, cnt = Quartz.CGGetActiveDisplayList(16, None, None)
    if err != Quartz.kCGErrorSuccess:  # pragma: no cover (defensive)
        raise OSError(f"CGGetActiveDisplayList failed: {err}")

    min_x = min_y = float("inf")
    max_x = max_y = -float("inf")
    for did in ids[:cnt]:
        r = Quartz.CGDisplayBounds(did)
        x0, y0 = r.origin.x, r.origin.y
        x1, y1 = x0 + r.size.width, y0 + r.size.height
        min_x, min_y = min(min_x, x0), min(min_y, y0)
        max_x, max_y = max(max_x, x1), max(max_y, y1)
    return min_x, min_y, max_x, max_y


def _get_visible_windows() -> List[tuple[dict, float]]:
    """List *onscreen* windows with their visible‑area ratio.

    Each tuple is ``(window_info_dict, visible_ratio)`` where *visible_ratio*
    is in ``[0.0, 1.0]``.  Internal system windows (Dock, WindowServer, …) are
    ignored.
    """
    if Quartz is None:
        # Fallback for non-macOS systems - return empty list
        # Window management functionality is not available
        return []
    
    _, _, _, gmax_y = _get_global_bounds()

    opts = (
        Quartz.kCGWindowListOptionOnScreenOnly
        | Quartz.kCGWindowListOptionIncludingWindow
    )
    wins = Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)

    occupied = None  # running union of opaque regions above the current window
    result: list[tuple[dict, float]] = []

    for info in wins:
        owner = info.get("kCGWindowOwnerName", "")
        if owner in ("Dock", "WindowServer", "Window Server"):
            continue

        bounds = info.get("kCGWindowBounds", {})
        x, y, w, h = (
            bounds.get("X", 0),
            bounds.get("Y", 0),
            bounds.get("Width", 0),
            bounds.get("Height", 0),
        )
        if w <= 0 or h <= 0:
            continue  # hidden or minimised

        inv_y = gmax_y - y - h  # Quartz→Shapely Y‑flip
        poly = box(x, inv_y, x + w, inv_y + h)
        if poly.is_empty:
            continue

        visible = poly if occupied is None else poly.difference(occupied)
        if not visible.is_empty:
            ratio = visible.area / poly.area
            result.append((info, ratio))
            occupied = poly if occupied is None else unary_union([occupied, poly])

    return result


def _is_app_visible(names: Iterable[str]) -> bool:
    """Return *True* if **any** window from *names* is at least partially visible."""
    if Quartz is None:
        # Fallback for non-macOS systems - assume app is visible
        return True
    
    targets = set(names)
    return any(
        info.get("kCGWindowOwnerName", "") in targets and ratio > 0
        for info, ratio in _get_visible_windows()
    )

###############################################################################
# Screen observer                                                             #
###############################################################################

class Screen(Observer):
    """Observer that captures and analyzes screen content around user interactions.

    This observer captures screenshots before and after user interactions (mouse movements,
    clicks, and scrolls) and uses GPT-4 Vision to analyze the content. It can also take
    periodic screenshots and skip captures when certain applications are visible.

    Args:
        screenshots_dir (str, optional): Directory to store screenshots. Defaults to "~/.cache/gum/screenshots".
        skip_when_visible (Optional[str | list[str]], optional): Application names to skip when visible.
            Defaults to None.
        transcription_prompt (Optional[str], optional): Custom prompt for transcribing screenshots.
            Defaults to None.
        summary_prompt (Optional[str], optional): Custom prompt for summarizing screenshots.
            Defaults to None.
        model_name (str, optional): GPT model to use for vision analysis. Defaults to "gpt-4o-mini".
        history_k (int, optional): Number of recent screenshots to keep in history. Defaults to 10.
        debug (bool, optional): Enable debug logging. Defaults to False.

    Attributes:
        _CAPTURE_FPS (int): Frames per second for screen capture.
        _DEBOUNCE_SEC (int): Seconds to wait before processing an interaction.
        _MON_START (int): Index of first real display in mss.
    """

    _CAPTURE_FPS: int = 3  # Reduced from 10 to 3 FPS (70% reduction)
    _DEBOUNCE_SEC: int = 1  # Reduced from 2 to 1 second for faster response
    _MON_START: int = 1     # first real display in mss

    # ─────────────────────────────── construction
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        screenshots_dir: str = "~/.cache/gum/screenshots",
        skip_when_visible: Optional[str | list[str]] = None,
        transcription_prompt: Optional[str] = None,
        summary_prompt: Optional[str] = None,
        history_k: int = 10,
        debug: bool = False,
        api_key: str | None = None,
        api_base: str | None = None,
        buffer_minutes: int = 10,  # New: buffer duration in minutes
    ) -> None:
        """Initialize the Screen observer.
        
        Args:
            screenshots_dir (str, optional): Directory to store screenshots. Defaults to "~/.cache/gum/screenshots".
            skip_when_visible (Optional[str | list[str]], optional): Application names to skip when visible.
                Defaults to None.
            transcription_prompt (Optional[str], optional): Custom prompt for transcribing screenshots.
                Defaults to None.
            summary_prompt (Optional[str], optional): Custom prompt for summarizing screenshots.
                Defaults to None.
            model_name (str, optional): GPT model to use for vision analysis. Defaults to "gpt-4o-mini".
            history_k (int, optional): Number of recent screenshots to keep in history. Defaults to 10.
            debug (bool, optional): Enable debug logging. Defaults to False.
            buffer_minutes (int, optional): Buffer duration in minutes before processing. Defaults to 10.
        """
        self.screens_dir = os.path.abspath(os.path.expanduser(screenshots_dir))
        os.makedirs(self.screens_dir, exist_ok=True)

        self._guard = {skip_when_visible} if isinstance(skip_when_visible, str) else set(skip_when_visible or [])

        self.transcription_prompt = transcription_prompt or TRANSCRIPTION_PROMPT
        self.summary_prompt = summary_prompt or SUMMARY_PROMPT
        self.model_name = model_name

        self.debug = debug

        # state shared with worker
        self._frames: Dict[int, Any] = {}
        self._frame_lock = asyncio.Lock()
        
        # Frame deduplication
        self._last_frame_hashes: Dict[int, str] = {}
        self._frame_similarity_threshold = 0.95  # Skip if 95%+ similar

        self._history: deque[str] = deque(maxlen=max(0, history_k))
        self._pending_event: Optional[dict] = None
        self._debounce_handle: Optional[asyncio.TimerHandle] = None
<<<<<<< Updated upstream
        
        # Buffer system for 10-minute processing
        self._buffer_minutes = buffer_minutes
        self._buffer_seconds = buffer_minutes * 60
        self._buffer: List[dict] = []  # Store buffered events
        self._buffer_lock = asyncio.Lock()  # Thread safety for buffer
        self._buffer_timer: Optional[asyncio.TimerHandle] = None  # Timer for batch processing
        self._buffer_start_time: Optional[float] = None  # When current buffer started
        
        self.client = AsyncOpenAI(
            # try the class, then the env for screen, then the env for gum
            base_url=api_base or os.getenv("SCREEN_LM_API_BASE") or os.getenv("GUM_LM_API_BASE"), 
=======
        # Check if batching is enabled
        use_batched = os.getenv("USE_BATCHED_CLIENT", "false").lower() == "true"
        
        if use_batched:
            # Use batched client - will be initialized when needed
            self.client = None
            self.use_batched = True
        else:
            # Use direct OpenAI client
            self.client = AsyncOpenAI(
                # try the class, then the env for screen, then the env for gum
                base_url=api_base or os.getenv("SCREEN_LM_API_BASE") or os.getenv("GUM_LM_API_BASE"), 
>>>>>>> Stashed changes

                # try the class, then the env for screen, then the env for GUM, then none
                api_key=api_key or os.getenv("SCREEN_LM_API_KEY") or os.getenv("GUM_LM_API_KEY") or os.getenv("OPENAI_API_KEY") or "None"
            )
            self.use_batched = False

        # call parent
        super().__init__()

    # ─────────────────────────────── tiny sync helpers
    @staticmethod
    def _mon_for(x: float, y: float, mons: list[dict]) -> Optional[int]:
        """Find which monitor contains the given coordinates.
        
        Args:
            x (float): X coordinate.
            y (float): Y coordinate.
            mons (list[dict]): List of monitor information dictionaries.
            
        Returns:
            Optional[int]: Monitor index if found, None otherwise.
        """
        for idx, m in enumerate(mons, 1):
            if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
                return idx
        return None

    @staticmethod
    def _encode_image(img_path: str) -> str:
        """Encode an image file as base64.
        
        Args:
            img_path (str): Path to the image file.
            
        Returns:
            str: Base64 encoded image data.
        """
        with open(img_path, "rb") as fh:
            return base64.b64encode(fh.read()).decode()
    
    def _get_frame_hash(self, frame) -> str:
        """Get a simple hash of frame data for deduplication."""
        import hashlib
        # Use frame RGB data for hashing
        frame_data = frame.rgb[:1000]  # Use first 1000 bytes for quick hash
        return hashlib.md5(frame_data).hexdigest()
    
    def _is_frame_similar(self, frame, monitor_idx: int) -> bool:
        """Check if frame is similar to previous frame (deduplication)."""
        current_hash = self._get_frame_hash(frame)
        last_hash = self._last_frame_hashes.get(monitor_idx)
        
        if last_hash is None:
            self._last_frame_hashes[monitor_idx] = current_hash
            return False
        
        # Simple similarity check - if hashes are identical, skip
        if current_hash == last_hash:
            return True
        
        self._last_frame_hashes[monitor_idx] = current_hash
        return False

    # ─────────────────────────────── buffer management
    async def _add_to_buffer(self, before_path: str, after_path: str, event_type: str, monitor_idx: int) -> None:
        """Add an event to the buffer for batch processing.
        
        Args:
            before_path (str): Path to the "before" screenshot.
            after_path (str): Path to the "after" screenshot.
            event_type (str): Type of event (move, click, scroll).
            monitor_idx (int): Monitor index where event occurred.
        """
        async with self._buffer_lock:
            # Start buffer timer if this is the first event
            if not self._buffer and self._buffer_start_time is None:
                self._buffer_start_time = time.time()
                loop = asyncio.get_running_loop()
                self._buffer_timer = loop.call_later(self._buffer_seconds, self._schedule_buffer_processing)
                if self.debug:
                    log = logging.getLogger("Screen")
                    log.info(f"Buffer started - will process in {self._buffer_minutes} minutes")
            
            # Add event to buffer
            self._buffer.append({
                'before_path': before_path,
                'after_path': after_path,
                'event_type': event_type,
                'monitor_idx': monitor_idx,
                'timestamp': time.time()
            })
            
            if self.debug:
                log = logging.getLogger("Screen")
                log.info(f"Added event to buffer (size: {len(self._buffer)})")

    def _schedule_buffer_processing(self) -> None:
        """Schedule buffer processing as an async task."""
        loop = asyncio.get_running_loop()
        asyncio.run_coroutine_threadsafe(self._process_buffer(), loop)

    async def _process_buffer(self) -> None:
        """Process all buffered events in a single batch."""
        async with self._buffer_lock:
            if not self._buffer:
                return
            
            buffer_copy = self._buffer.copy()
            self._buffer.clear()
            self._buffer_start_time = None
            self._buffer_timer = None
            
            if self.debug:
                log = logging.getLogger("Screen")
                log.info(f"Processing buffer with {len(buffer_copy)} events")
        
        # Process all events in the buffer
        try:
            # Group events by monitor for better context
            monitor_events = {}
            for event in buffer_copy:
                monitor_idx = event['monitor_idx']
                if monitor_idx not in monitor_events:
                    monitor_events[monitor_idx] = []
                monitor_events[monitor_idx].append(event)
            
            # Process each monitor's events
            for monitor_idx, events in monitor_events.items():
                await self._process_monitor_events(monitor_idx, events)
                
        except Exception as e:
            log = logging.getLogger("Screen")
            log.error(f"Error processing buffer: {e}")
            # Fallback: process events individually
            for event in buffer_copy:
                try:
                    await self._process_single_event(event)
                except Exception as single_error:
                    log.error(f"Error processing single event: {single_error}")

    async def _process_monitor_events(self, monitor_idx: int, events: List[dict]) -> None:
        """Process all events for a specific monitor in batch with detailed insights.
        
        Args:
            monitor_idx (int): Monitor index.
            events (List[dict]): List of events for this monitor.
        """
        if not events:
            return
        
        # Prepare frame batch data for detailed analysis
        frame_batch = []
        event_summaries = []
        
        for i, event in enumerate(events):
            # Encode images to base64 for analysis
            before_base64 = self._encode_image(event['before_path'])
            after_base64 = self._encode_image(event['after_path'])
            
            # Create frame data with timestamps
            frame_data = {
                "frame_number": i + 1,
                "timestamp": event.get('timestamp', time.time()),
                "event_type": event['event_type'],
                "base64_data": before_base64,  # Use before image as primary
                "after_base64_data": after_base64,
                "monitor_idx": event['monitor_idx'],
                "before_path": event['before_path'],
                "after_path": event['after_path']
            }
            frame_batch.append(frame_data)
            event_summaries.append(f"{event['event_type']} on monitor {event['monitor_idx']}")
        
        # Add to history for context
        for event in events:
            self._history.append(event['before_path'])
        
        # Calculate time range for detailed analysis
        start_time = None
        end_time = None
        if frame_batch:
            first_timestamp = frame_batch[0].get("timestamp", 0)
            last_timestamp = frame_batch[-1].get("timestamp", 0)
            
            if isinstance(first_timestamp, (int, float)):
                hours = int(first_timestamp // 3600)
                minutes = int((first_timestamp % 3600) // 60)
                seconds = int(first_timestamp % 60)
                start_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            if isinstance(last_timestamp, (int, float)):
                hours = int(last_timestamp // 3600)
                minutes = int((last_timestamp % 3600) // 60)
                seconds = int(last_timestamp % 60)
                end_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        # Use detailed batch analysis
        try:
            detailed_analysis = await self._analyze_batch_with_detailed_insights(
                frame_batch, 
                f"monitor_{monitor_idx}_batch", 
                start_time, 
                end_time
            )
            
            # Extract insights from detailed analysis
            if detailed_analysis and 'detailed_analyses' in detailed_analysis:
                insights = []
                for analysis in detailed_analysis['detailed_analyses']:
                    if 'analysis' in analysis and analysis['analysis']:
                        insights.append(analysis['analysis'])
                
                # Combine insights into comprehensive analysis
                combined_analysis = "\n\n".join(insights)
                
                # Add batch summary if available
                if 'summary' in detailed_analysis:
                    combined_analysis += f"\n\nBatch Summary: {detailed_analysis['summary']}"
                
                # Emit detailed analysis result
                await self.update_queue.put(Update(content=combined_analysis, content_type="input_text"))
                
            else:
                # Fallback to original method if detailed analysis fails
                await self._process_monitor_events_fallback(monitor_idx, events)
                
        except Exception as exc:
            logging.getLogger("Screen").error(f"Detailed batch analysis failed: {exc}")
            # Fallback to original method
            await self._process_monitor_events_fallback(monitor_idx, events)
        
        if self.debug:
            log = logging.getLogger("Screen")
            log.info(f"Processed {len(events)} events for monitor {monitor_idx} with detailed analysis")

    async def _process_single_event(self, event: dict) -> None:
        """Process a single event (fallback method).
        
        Args:
            event (dict): Event data.
        """
        await self._process_and_emit(event['before_path'], event['after_path'])

    async def _process_monitor_events_fallback(self, monitor_idx: int, events: List[dict]) -> None:
        """Fallback method for processing monitor events using original approach.
        
        Args:
            monitor_idx (int): Monitor index.
            events (List[dict]): List of events for this monitor.
        """
        if not events:
            return
        
        # Collect all image paths for batch processing
        all_paths = []
        event_summaries = []
        
        for event in events:
            all_paths.extend([event['before_path'], event['after_path']])
            event_summaries.append(f"{event['event_type']} on monitor {event['monitor_idx']}")
        
        # Get historical context
        prev_paths = list(self._history)
        
        # Batch process with AI
        try:
            # Create a comprehensive prompt for batch processing
            batch_prompt = f"""Analyze this sequence of screen interactions: {', '.join(event_summaries)}.
            
            {self.transcription_prompt}"""
            
            transcription = await self._call_gpt_vision(batch_prompt, all_paths)
        except Exception as exc:
            transcription = f"[batch transcription failed: {exc}]"
        
        # Create summary with historical context
        try:
            summary_prompt = f"""Summarize this batch of screen interactions with historical context: {', '.join(event_summaries)}.
            
            {self.summary_prompt}"""
            
            summary_paths = prev_paths + all_paths
            summary = await self._call_gpt_vision(summary_prompt, summary_paths)
        except Exception as exc:
            summary = f"[batch summary failed: {exc}]"
        
        # Emit combined result
        txt = (transcription + summary).strip()
        await self.update_queue.put(Update(content=txt, content_type="input_text"))

    async def _analyze_batch_with_detailed_insights(self, frame_batch: List[dict], batch_id: str = "batch", start_time: Optional[str] = None, end_time: Optional[str] = None) -> dict:
        """Analyze a batch of frames/events with detailed bullet-point insights and precise timestamp correlation.
        
        Args:
            frame_batch (List[dict]): List of frame/event data with timestamps
            batch_id (str): Identifier for the batch
            start_time (Optional[str]): Start time of the batch (HH:MM:SS format)
            end_time (Optional[str]): End time of the batch (HH:MM:SS format)
            
        Returns:
            dict: Structured analysis with detailed insights
        """
        try:
            logging.getLogger("Screen").info(f"Starting detailed batch analysis for {len(frame_batch)} frames/events (batch: {batch_id})")
            
            # Prepare batch data with timestamps
            frame_info = []
            event_timeline = []
            
            for i, frame_data in enumerate(frame_batch):
                frame_number = frame_data.get("frame_number", i + 1)
                timestamp = frame_data.get("timestamp", 0)
                event_type = frame_data.get("event_type", "screen_capture")
                
                # Convert timestamp to readable format
                if isinstance(timestamp, (int, float)):
                    # Convert seconds to HH:MM:SS format
                    hours = int(timestamp // 3600)
                    minutes = int((timestamp % 3600) // 60)
                    seconds = int(timestamp % 60)
                    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                else:
                    time_str = str(timestamp)
                
                filename = f"frame_{frame_number:03d}.jpg"
                frame_info.append(f"Frame {frame_number}: {filename} at {time_str}")
                event_timeline.append(f"{time_str}: {event_type}")
            
            # Determine time range
            if not start_time and frame_batch:
                first_timestamp = frame_batch[0].get("timestamp", 0)
                if isinstance(first_timestamp, (int, float)):
                    hours = int(first_timestamp // 3600)
                    minutes = int((first_timestamp % 3600) // 60)
                    seconds = int(first_timestamp % 60)
                    start_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            if not end_time and frame_batch:
                last_timestamp = frame_batch[-1].get("timestamp", 0)
                if isinstance(last_timestamp, (int, float)):
                    hours = int(last_timestamp // 3600)
                    minutes = int((last_timestamp % 3600) // 60)
                    seconds = int(last_timestamp % 60)
                    end_time = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            time_range = f"{start_time or '00:00:00'} - {end_time or '00:00:00'}"
            
            # Create comprehensive system prompt for detailed analysis
            frame_list = "\n".join(frame_info)
            timeline = "\n".join(event_timeline)
            
            system_prompt = f"""You are a professional workflow analyst specializing in user behavior and productivity optimization. Analyze this sequence of {len(frame_batch)} screen captures and events to provide detailed insights about the user's workflow, productivity patterns, and behavioral tendencies.

EVENT TIMELINE:
{timeline}

FRAME SEQUENCE:
{frame_list}

ANALYSIS REQUIREMENTS:
You must provide a structured analysis following this EXACT format:

WORKFLOW ANALYSIS ({time_range})

• Specific Problem Moments (exact timestamps)
HH:MM:SS: [Specific issue or distraction], [duration/impact]
HH:MM:SS: [Another issue], [resolution time]

• Productivity Patterns
Peak focus: [time range] ([activity description])
Distraction trigger: [specific event] at [time]
Recovery pattern: [time to regain focus]

• Application Usage
Most used: [App name] ([X.X minutes])
Context switches: [number] times in [duration]
Switch cost: Average [X] seconds per switch

• Behavioral Insights
[Specific observation about user behavior with evidence]
[Pattern identified with supporting details]
[Recommendation based on observed data]

ANALYSIS GUIDELINES:
1. Extract precise timestamps from the event timeline
2. Identify specific moments of productivity loss or distraction
3. Analyze application switching patterns and context costs
4. Look for behavioral patterns that impact workflow efficiency
5. Provide actionable recommendations based on observed behavior
6. Use exact HH:MM:SS format for all timestamps
7. Be specific about durations, frequencies, and impact
8. Focus on actionable insights that can improve productivity

Provide a comprehensive analysis that helps understand and optimize the user's workflow."""
            
            # Process each frame individually but with enhanced context
            detailed_analyses = []
            for i, frame_data in enumerate(frame_batch):
                try:
                    frame_number = frame_data.get("frame_number", i + 1)
                    base64_data = frame_data.get("base64_data", "")
                    timestamp = frame_data.get("timestamp", 0)
                    event_type = frame_data.get("event_type", "screen_capture")
                    
                    # Convert timestamp to readable format
                    if isinstance(timestamp, (int, float)):
                        hours = int(timestamp // 3600)
                        minutes = int((timestamp % 3600) // 60)
                        seconds = int(timestamp % 60)
                        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        time_str = str(timestamp)
                    
                    filename = f"frame_{frame_number:03d}.jpg"
                    
                    # Create frame-specific prompt with enhanced context
                    frame_prompt = f"""This is frame {i + 1} of {len(frame_batch)} in a detailed workflow analysis sequence.

{system_prompt}

CURRENT FRAME CONTEXT:
- Frame: {filename}
- Timestamp: {time_str}
- Event Type: {event_type}
- Position in sequence: {i + 1}/{len(frame_batch)}

Analyze this specific frame in the context of the overall workflow sequence, focusing on the user's behavior at this exact moment and how it relates to the broader productivity patterns."""
                    
                    # Use the existing vision completion method
                    analysis = await self._call_gpt_vision(frame_prompt, [frame_data.get("before_path", "")])
                    
                    if analysis:
                        detailed_analyses.append({
                            "frame_number": frame_number,
                            "timestamp": time_str,
                            "event_type": event_type,
                            "analysis": analysis,
                            "base64_data": base64_data,
                            "batch_processed": True,
                            "batch_id": batch_id
                        })
                    else:
                        detailed_analyses.append({
                            "frame_number": frame_number,
                            "timestamp": time_str,
                            "event_type": event_type,
                            "analysis": "Error: Empty response from vision model",
                            "base64_data": base64_data,
                            "batch_processed": True,
                            "batch_id": batch_id,
                            "error": True
                        })
                        
                except Exception as frame_error:
                    logging.getLogger("Screen").error(f"Error processing frame {frame_data.get('frame_number', 'unknown')} in detailed batch: {frame_error}")
                    detailed_analyses.append({
                        "frame_number": frame_data.get("frame_number", i + 1),
                        "timestamp": str(frame_data.get("timestamp", 0)),
                        "event_type": frame_data.get("event_type", "screen_capture"),
                        "analysis": f"Error analyzing frame in detailed batch: {str(frame_error)}",
                        "base64_data": frame_data.get("base64_data", ""),
                        "batch_processed": True,
                        "batch_id": batch_id,
                        "error": True
                    })
            
            # Create consolidated analysis
            consolidated_analysis = {
                "batch_id": batch_id,
                "time_range": time_range,
                "frame_count": len(frame_batch),
                "detailed_analyses": detailed_analyses,
                "summary": {
                    "start_time": start_time,
                    "end_time": end_time,
                    "total_duration": len(frame_batch),
                    "event_types": list(set(f.get("event_type", "screen_capture") for f in frame_batch))
                }
            }
            
            logging.getLogger("Screen").info(f"Detailed batch analysis completed for {len(detailed_analyses)} frames")
            return consolidated_analysis
            
        except Exception as e:
            logging.getLogger("Screen").error(f"Detailed batch analysis failed: {str(e)}")
            return {
                "batch_id": batch_id,
                "time_range": f"{start_time or '00:00:00'} - {end_time or '00:00:00'}",
                "frame_count": len(frame_batch),
                "detailed_analyses": [],
                "error": str(e),
                "summary": {
                    "start_time": start_time,
                    "end_time": end_time,
                    "total_duration": len(frame_batch),
                    "event_types": []
                }
            }

    def get_buffer_status(self) -> dict:
        """Get current buffer status for monitoring.
        
        Returns:
            dict: Buffer status information.
        """
        async def _get_status():
            async with self._buffer_lock:
                buffer_size = len(self._buffer)
                time_remaining = 0
                if self._buffer_start_time and self._buffer_timer:
                    elapsed = time.time() - self._buffer_start_time
                    time_remaining = max(0, self._buffer_seconds - elapsed)
                
                return {
                    'buffer_size': buffer_size,
                    'buffer_minutes': self._buffer_minutes,
                    'time_remaining_seconds': time_remaining,
                    'is_active': self._buffer_timer is not None,
                    'events': [
                        {
                            'type': event['event_type'],
                            'monitor': event['monitor_idx'],
                            'timestamp': event['timestamp']
                        }
                        for event in self._buffer
                    ]
                }
        
        # Since this is called from sync context, we need to handle it carefully
        try:
            loop = asyncio.get_running_loop()
            # If we're in an async context, we can't use run_coroutine_threadsafe
            # So we'll return a simple status without the full details
            return {
                'buffer_size': len(self._buffer),
                'buffer_minutes': self._buffer_minutes,
                'is_active': self._buffer_timer is not None
            }
        except RuntimeError:
            # Not in async context, return basic info
            return {
                'buffer_size': len(self._buffer),
                'buffer_minutes': self._buffer_minutes,
                'is_active': self._buffer_timer is not None
            }

    # ─────────────────────────────── OpenAI Vision (async)
    async def _call_gpt_vision(self, prompt: str, img_paths: list[str]) -> str:
        """Call GPT Vision API to analyze images.
        
        Args:
            prompt (str): Prompt to guide the analysis.
            img_paths (list[str]): List of image paths to analyze.
            
        Returns:
            str: GPT's analysis of the images.
        """
        if self.use_batched:
            # Use batched client for vision completion
            from batched_ai_client import get_batched_client
            batched_client = await get_batched_client()
            
            # Encode images to base64
            encoded_images = await asyncio.gather(
                *[asyncio.to_thread(self._encode_image, p) for p in img_paths]
            )
            
            # Use the first image for batched vision completion
            # Note: Batched client currently supports single image, so we'll use the first one
            base64_image = encoded_images[0] if encoded_images else ""
            
            return await batched_client.vision_completion(
                text_prompt=prompt,
                base64_image=base64_image,
                max_tokens=2000,
                temperature=0.1,
                urgent=False  # Allow batching for screen analysis
            )
        else:
            # Use direct OpenAI client
            content = [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                }
                for encoded in (await asyncio.gather(
                    *[asyncio.to_thread(self._encode_image, p) for p in img_paths]
                ))
            ]
            content.append({"type": "text", "text": prompt})

            rsp = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": content}],
                response_format={"type": "text"},
            )
            return rsp.choices[0].message.content

    # ─────────────────────────────── I/O helpers
    async def _save_frame(self, frame, tag: str) -> str:
        """Save a frame as a JPEG image.
        
        Args:
            frame: Frame data to save.
            tag (str): Tag to include in the filename.
            
        Returns:
            str: Path to the saved image.
        """
        ts   = f"{time.time():.5f}"
        path = os.path.join(self.screens_dir, f"{ts}_{tag}.jpg")
        await asyncio.to_thread(
            Image.frombytes("RGB", (frame.width, frame.height), frame.rgb).save,
            path,
            "JPEG",
            quality=70,
        )
        return path

    async def _process_and_emit(self, before_path: str, after_path: str, event_type: str = "interaction", monitor_idx: int = 1) -> None:
        """Process screenshots and emit an update.
        
        Args:
            before_path (str): Path to the "before" screenshot.
            after_path (str | None): Path to the "after" screenshot, if any.
            event_type (str): Type of event (move, click, scroll, interaction).
            monitor_idx (int): Monitor index where event occurred.
        """
        # Add to buffer for batch processing instead of immediate processing
        await self._add_to_buffer(before_path, after_path, event_type, monitor_idx)

    # ─────────────────────────────── skip guard
    def _skip(self) -> bool:
        """Check if capture should be skipped based on visible applications.
        
        Returns:
            bool: True if capture should be skipped, False otherwise.
        """
        return _is_app_visible(self._guard) if self._guard else False

    # ─────────────────────────────── main async worker
    async def _worker(self) -> None:          # overrides base class
        """Main worker method that captures and processes screenshots.
        
        This method runs in a background task and handles:
        - Mouse event monitoring
        - Screen capture
        - Periodic screenshots
        - Image processing and analysis
        """
        log = logging.getLogger("Screen")
        if self.debug:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s [Screen] %(message)s", datefmt="%H:%M:%S")
        else:
            log.addHandler(logging.NullHandler())
            log.propagate = False

        CAP_FPS  = self._CAPTURE_FPS
        DEBOUNCE = self._DEBOUNCE_SEC

        loop = asyncio.get_running_loop()

        # ------------------------------------------------------------------
        # All calls to mss / Quartz are wrapped in `to_thread`
        # ------------------------------------------------------------------
        sct = mss.mss()  # Create mss context in main thread
        mons = sct.monitors[self._MON_START:]

        # ---- mouse event reception ----
        async def mouse_event(x: float, y: float, typ: str):
            """Handle mouse events.
            
            Args:
                x (float): X coordinate.
                y (float): Y coordinate.
                typ (str): Event type ("move", "click", or "scroll").
            """
            idx = self._mon_for(x, y, mons)
            log.info(
                f"{typ:<6} @({x:7.1f},{y:7.1f}) → mon={idx}   {'(guarded)' if self._skip() else ''}"
            )
            if self._skip() or idx is None:
                return

            # lazily grab before-frame
            if self._pending_event is None:
                async with self._frame_lock:
                    bf = self._frames.get(idx)
                if bf is None:
                    # Wait a bit for frames to be populated
                    await asyncio.sleep(0.1)
                    async with self._frame_lock:
                        bf = self._frames.get(idx)
                    if bf is None:
                        return
                self._pending_event = {"type": typ, "mon": idx, "before": bf}

            # reset debounce timer
            if self._debounce_handle:
                self._debounce_handle.cancel()
            self._debounce_handle = loop.call_later(DEBOUNCE, debounce_flush)

        # ---- mouse callbacks (pynput is sync → schedule into loop) ----
        def schedule_event(x: float, y: float, typ: str):
            asyncio.run_coroutine_threadsafe(mouse_event(x, y, typ), loop)

        listener = mouse.Listener(
            on_move=lambda x, y: schedule_event(x, y, "move"),
            on_click=lambda x, y, btn, prs: schedule_event(x, y, "click") if prs else None,
            on_scroll=lambda x, y, dx, dy: schedule_event(x, y, "scroll"),
        )
        listener.start()

        # ---- nested helper inside the async context ----
        async def flush():
            """Process pending event and emit update."""
            if self._pending_event is None:
                return
            if self._skip():
                self._pending_event = None
                return

            ev = self._pending_event
            aft = sct.grab(mons[ev["mon"] - 1])  # Use sct directly, not in thread

            bef_path = await self._save_frame(ev["before"], "before")
            aft_path = await self._save_frame(aft, "after")
            await self._process_and_emit(bef_path, aft_path, ev["type"], ev["mon"])

            log.info(f"{ev['type']} captured on monitor {ev['mon']}")
            self._pending_event = None

        def debounce_flush():
            """Schedule flush as a task."""
            asyncio.run_coroutine_threadsafe(flush(), loop)

        # ---- main capture loop ----
        log.info(f"Screen observer started — guarding {self._guard or '∅'}")
        
        # Add initial frame population
        for idx, m in enumerate(mons, 1):
            try:
                frame = sct.grab(m)  # Use sct directly
                async with self._frame_lock:
                    self._frames[idx] = frame
            except Exception as e:
                log.error(f"Failed to populate frame for monitor {idx}: {e}")

        while self._running:                         # flag from base class
            t0 = time.time()

            # refresh 'before' buffers
            for idx, m in enumerate(mons, 1):
                try:
                    frame = sct.grab(m)  # Use sct directly
                    
                    # Skip if frame is too similar to previous (deduplication)
                    if self._is_frame_similar(frame, idx):
                        continue
                    
                    async with self._frame_lock:
                        self._frames[idx] = frame
                except Exception as e:
                    log.error(f"Failed to refresh frame for monitor {idx}: {e}")

            # fps throttle
            dt = time.time() - t0
            await asyncio.sleep(max(0, (1 / CAP_FPS) - dt))

        # shutdown
        listener.stop()
        if self._debounce_handle:
            self._debounce_handle.cancel()
        if self._buffer_timer:
            self._buffer_timer.cancel()
        # Process any remaining buffered events
        if self._buffer:
            await self._process_buffer()
        sct.close()  # Close mss context
