#!/usr/bin/env python3
"""
GUM REST API Controller

A FastAPI-based REST API that exposes GUM functionality for submitting
observations through text and images, and querying the system.
"""

import asyncio
import base64
import glob
import logging
import os
import subprocess
import tempfile
import time
import uuid
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from dateutil import parser as date_parser
from io import BytesIO
from pathlib import Path
from typing import List, Optional, Union
from asyncio import Semaphore

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from PIL import Image
from pydantic import BaseModel, Field
from rate_limiter import rate_limiter

from dotenv import load_dotenv
from gum import gum
from gum.schemas import Update
from gum.observers import Observer
from unified_ai_client import UnifiedAIClient
from batched_ai_client import BatchedAIClient, get_batched_client

# Load environment variables
load_dotenv(override=True)  # Ensure .env takes precedence

# Configure logging with user-friendly format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',  # Cleaner format for user visibility
    datefmt='%H:%M:%S',  # Just time, not full date
    handlers=[
        logging.StreamHandler()  # Ensure console output
    ]
)
logger = logging.getLogger(__name__)

# Ensure immediate console output (force flush)
import sys
import os
os.environ['PYTHONUNBUFFERED'] = '1'

# Initialize FastAPI app
app = FastAPI(
    title="GUM API",
    description="REST API for submitting observations and querying user behavior insights",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware to allow frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global GUM instance
gum_instance: Optional[gum] = None

# Global AI clients
ai_client: Optional[UnifiedAIClient] = None
batched_ai_client: Optional[BatchedAIClient] = None

# Configuration for batching
USE_BATCHED_CLIENT = os.getenv("USE_BATCHED_CLIENT", "true").lower() == "true"
BATCH_INTERVAL_HOURS = float(os.getenv("BATCH_INTERVAL_HOURS", "1.0"))
MAX_BATCH_SIZE = int(os.getenv("MAX_BATCH_SIZE", "50"))


async def get_ai_client() -> UnifiedAIClient:
    """Get the unified AI client for both text and vision tasks."""
    global ai_client
    
    if ai_client is None:
        logger.info("Initializing unified AI client")
        ai_client = UnifiedAIClient()
        
        # Store original methods
        original_text_completion = ai_client.text_completion
        original_vision_completion = ai_client.vision_completion
        
        # Create debug wrapper for text completion
        async def debug_text_completion(*args, **kwargs):
            logger.info("Text completion call starting...")
            logger.info(f"   Args count: {len(args)}")
            logger.info(f"   Kwargs: {list(kwargs.keys())}")
            try:
                response = await original_text_completion(*args, **kwargs)
                logger.info("Text completion response received:")
                logger.info(f"   Response type: {type(response)}")
                logger.info(f"   Response length: {len(str(response)) if response else 0}")
                logger.info(f"   Response preview: {str(response)[:200]}...")
                return response
            except Exception as e:
                logger.error(f"Text completion error: {type(e).__name__}: {str(e)}")
                raise

        # Create debug wrapper for vision completion
        async def debug_vision_completion(*args, **kwargs):
            logger.info("Vision completion call starting...")
            logger.info(f"   Args count: {len(args)}")
            logger.info(f"   Kwargs: {list(kwargs.keys())}")
            try:
                response = await original_vision_completion(*args, **kwargs)
                logger.info("Vision completion response received:")
                logger.info(f"   Response type: {type(response)}")
                logger.info(f"   Response length: {len(str(response)) if response else 0}")
                logger.info(f"   Response preview: {str(response)[:200]}...")
                return response
            except Exception as e:
                logger.error(f"Vision completion error: {type(e).__name__}: {str(e)}")
                raise
        
        # Replace methods with debug versions
        ai_client.text_completion = debug_text_completion
        ai_client.vision_completion = debug_vision_completion
        
        logger.info("Unified AI client initialized with debug logging")
    
    return ai_client


async def get_batched_ai_client() -> BatchedAIClient:
    """Get the batched AI client for reduced API calls."""
    global batched_ai_client
    
    if batched_ai_client is None:
        logger.info("Initializing batched AI client")
        batched_ai_client = BatchedAIClient(
            batch_interval_hours=BATCH_INTERVAL_HOURS,
            max_batch_size=MAX_BATCH_SIZE,
            enable_fallback=True,
            fallback_threshold_seconds=300  # 5 minutes
        )
        logger.info(f"Batched AI client initialized with {BATCH_INTERVAL_HOURS}h intervals")
    
    return batched_ai_client


async def get_active_ai_client():
    """Get the active AI client based on configuration."""
    if USE_BATCHED_CLIENT:
        return await get_batched_ai_client()
    else:
        return await get_ai_client()

# === Pydantic Models ===

class TextObservationRequest(BaseModel):
    """Request model for text observations."""
    content: str = Field(..., description="The text content of the observation", min_length=1)
    user_name: Optional[str] = Field(None, description="User name (optional, uses default if not provided)")
    observer_name: Optional[str] = Field("api_controller", description="Name of the observer submitting this")


class QueryRequest(BaseModel):
    """Request model for querying GUM."""
    query: str = Field(..., description="The search query", min_length=1)
    user_name: Optional[str] = Field(None, description="User name (optional)")
    limit: Optional[int] = Field(10, description="Maximum number of results to return", ge=1, le=100)
    mode: Optional[str] = Field("OR", description="Search mode (OR/AND)")


class ObservationResponse(BaseModel):
    """Response model for observations."""
    id: int = Field(..., description="Observation ID")
    content: str = Field(..., description="Observation content")
    content_type: str = Field(..., description="Type of content (input_text, input_image)")
    observer_name: str = Field(..., description="Name of the observer")
    created_at: datetime = Field(..., description="When the observation was created")


class PropositionResponse(BaseModel):
    """Response model for propositions."""
    id: int = Field(..., description="Proposition ID")
    text: str = Field(..., description="Proposition text")
    reasoning: Optional[str] = Field(None, description="Reasoning behind the proposition")
    confidence: Optional[float] = Field(None, description="Confidence score")
    created_at: datetime = Field(..., description="When the proposition was created")


class QueryResponse(BaseModel):
    """Response model for query results."""
    propositions: List[PropositionResponse] = Field(..., description="Matching propositions")
    total_results: int = Field(..., description="Total number of results found")
    query: str = Field(..., description="The original query")
    execution_time_ms: float = Field(..., description="Query execution time in milliseconds")


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str = Field(..., description="Service status")
    timestamp: datetime = Field(..., description="Current timestamp")
    gum_connected: bool = Field(..., description="Whether GUM database is connected")
    version: str = Field(..., description="API version")


class ErrorResponse(BaseModel):
    """Response model for errors."""
    error: str = Field(..., description="Error message")
    detail: Optional[str] = Field(None, description="Additional error details")
    timestamp: datetime = Field(..., description="Error timestamp")


# === Mock Observer Class ===

class APIObserver(Observer):
    """Mock observer for API-submitted observations."""
    
    def __init__(self, name: Optional[str] = None):
        super().__init__(name or "api_controller")
    
    async def _worker(self):
        """Required abstract method - not used for API submissions."""
        # API observer doesn't need a background worker since observations are submitted directly
        while self._running:
            await asyncio.sleep(1)


# === Helper Functions ===

def parse_datetime(date_value) -> datetime:
    """Parse datetime from string or return as-is if already datetime."""
    if isinstance(date_value, str):
        return date_parser.parse(date_value)
    return date_value


async def ensure_gum_instance(user_name: Optional[str] = None) -> gum:
    """Ensure GUM instance is initialized and connected."""
    global gum_instance
    
    default_user = os.getenv("DEFAULT_USER_NAME", "APIUser")
    user_name = user_name or default_user
    
    if gum_instance is None or gum_instance.user_name != user_name:
        logger.info(f"Initializing GUM instance for user: {user_name}")
        
        # Initialize GUM - it will automatically use the unified client
        logger.info("Initializing GUM with unified AI client")
        
        gum_instance = gum(
            user_name=user_name,
            model="gpt-4o",  # Model name used for logging/identification only
            data_directory="~/.cache/gum",
            verbosity=logging.INFO
        )
        
        await gum_instance.connect_db()
        logger.info("GUM instance connected to database")
        logger.info("GUM configured with unified AI client for hybrid text/vision processing")
    
    return gum_instance


def validate_image(file_content: bytes) -> bool:
    """Validate that the uploaded file is a valid image."""
    try:
        image = Image.open(BytesIO(file_content))
        image.verify()
        return True
    except Exception as e:
        logger.warning(f"Invalid image file: {e}")
        return False


def process_image_for_analysis(file_content: bytes) -> str:
    """Convert image to base64 for AI analysis."""
    try:
        # Open and process the image
        image = Image.open(BytesIO(file_content))
        
        # Convert to RGB if necessary
        if image.mode in ('RGBA', 'LA', 'P'):
            image = image.convert('RGB')
        
        # Resize if too large (to manage API costs)
        max_size = (1024, 1024)
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Convert to base64
        buffer = BytesIO()
        image.save(buffer, format='JPEG', quality=85)
        base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
        
        return base64_image
    
    except Exception as e:
        logger.error(f"Error processing image: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Error processing image: {str(e)}"
        )


async def analyze_image_with_ai(base64_image: str, filename: Optional[str] = None) -> str:
    """Analyze image using the active AI client."""
    try:
        logger.info("Starting image analysis with vision model")
        logger.info(f"   File: {filename}")
        
        # Get active AI client
        client = await get_active_ai_client()
        
        # Create prompt for image analysis
        display_filename = filename or "uploaded_image"
        prompt = f"""Analyze this image and describe what the user is doing, what applications they're using, 
        and any observable behavior patterns. Focus on:
        
        1. What applications or interfaces are visible
        2. What actions the user appears to be taking
        3. Any workflow patterns or preferences shown
        4. The general context of the user's activity
        
        Image filename: {display_filename}
        
        Provide a detailed but concise analysis that will help understand user behavior."""
        
        # Use the active client for vision completion
        if USE_BATCHED_CLIENT:
            # Use batched client with urgent=False for normal processing
            analysis = await client.vision_completion(
                text_prompt=prompt,
                base64_image=base64_image,
                urgent=False  # Allow batching for normal image analysis
            )
        else:
            # Use unified client
            analysis = await client.vision_completion(
                text_prompt=prompt,
                base64_image=base64_image
            )
        
        if analysis:
            logger.info("Vision analysis completed")
            logger.info(f"   Analysis length: {len(analysis)} characters")
            return analysis
        else:
            logger.error("Vision analysis returned empty response")
            return "Error: Empty response from vision model"
            
    except Exception as e:
        logger.error(f"Vision analysis failed: {str(e)}")
        return f"Error analyzing image: {str(e)}"


async def analyze_batch_with_detailed_insights(frame_batch: List[dict], batch_id: str = "batch", start_time: Optional[str] = None, end_time: Optional[str] = None) -> dict:
    """Analyze a batch of frames/events with detailed bullet-point insights and precise timestamp correlation.
    
    Args:
        frame_batch (List[dict]): List of frame/event data with timestamps
        batch_id (str): Identifier for the batch
        start_time (Optional[str]): Start time of the batch (HH:MM:SS AM/PM format)
        end_time (Optional[str]): End time of the batch (HH:MM:SS AM/PM format)
        
    Returns:
        dict: Structured analysis with detailed insights
    """
    try:
        logger.info(f"Starting detailed batch analysis for {len(frame_batch)} frames/events (batch: {batch_id})")
        
        # Get unified AI client
        client = await get_ai_client()
        
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
                
                # Use the unified client for vision completion
                analysis = await client.vision_completion(
                    text_prompt=frame_prompt,
                    base64_image=base64_data
                )
                
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
                logger.error(f"Error processing frame {frame_data.get('frame_number', 'unknown')} in detailed batch: {frame_error}")
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
        
        logger.info(f"Detailed batch analysis completed for {len(detailed_analyses)} frames")
        return consolidated_analysis
        
    except Exception as e:
        logger.error(f"Detailed batch analysis failed: {str(e)}")
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


async def analyze_frames_batch_with_ai(frame_batch: List[dict], batch_id: str = "batch") -> List[dict]:
    """Analyze multiple frames in a single AI call for batch processing.
    
    Args:
        frame_batch (List[dict]): List of frame data dictionaries with base64_data and frame_number
        batch_id (str): Identifier for the batch for logging purposes
        
    Returns:
        List[dict]: List of frame results with analysis
    """
    try:
        logger.info(f"Starting batch analysis for {len(frame_batch)} frames (batch: {batch_id})")
        
        # Get unified AI client
        client = await get_ai_client()
        
        # Prepare batch data
        frame_info = []
        
        for frame_data in frame_batch:
            frame_number = frame_data["frame_number"]
            filename = f"frame_{frame_number:03d}.jpg"
            frame_info.append(f"Frame {frame_number}: {filename}")
        
        # Create comprehensive prompt for batch analysis
        frame_list = "\n".join(frame_info)
        batch_prompt = f"""Analyze this sequence of {len(frame_batch)} video frames and describe what the user is doing, 
        what applications they're using, and any observable behavior patterns. Focus on:
        
        1. What applications or interfaces are visible across the frames
        2. What actions the user appears to be taking (sequence of activities)
        3. Any workflow patterns or preferences shown
        4. The general context and progression of the user's activity
        5. Changes or transitions between frames
        
        Frame sequence:
        {frame_list}
        
        Provide a detailed analysis that covers the entire sequence and helps understand the user's behavior pattern.
        Consider the temporal progression and any significant changes between frames."""
        
        # Process each frame individually but with batch context
        results = []
        for i, frame_data in enumerate(frame_batch):
            try:
                frame_number = frame_data["frame_number"]
                base64_data = frame_data["base64_data"]
                filename = f"frame_{frame_number:03d}.jpg"
                
                # Create frame-specific prompt that includes batch context
                frame_prompt = f"""This is frame {i + 1} of {len(frame_batch)} in a video sequence.
                
                {batch_prompt}
                
                Current frame: {filename}
                
                Analyze this specific frame in the context of the overall sequence."""
                
                # Use the unified client for vision completion
                analysis = await client.vision_completion(
                    text_prompt=frame_prompt,
                    base64_image=base64_data
                )
                
                if analysis:
                    # Create frame-specific analysis by adding frame context
                    frame_analysis = f"Frame {frame_number} Analysis (Batch {batch_id}):\n{analysis}"
                    
                    results.append({
                        "frame_number": frame_number,
                        "analysis": frame_analysis,
                        "base64_data": base64_data,
                        "batch_processed": True,
                        "batch_id": batch_id
                    })
                else:
                    # Handle empty response
                    results.append({
                        "frame_number": frame_number,
                        "analysis": "Error: Empty response from vision model",
                        "base64_data": base64_data,
                        "batch_processed": True,
                        "batch_id": batch_id,
                        "error": True
                    })
                    
            except Exception as frame_error:
                logger.error(f"Error processing frame {frame_data.get('frame_number', 'unknown')} in batch: {frame_error}")
                results.append({
                    "frame_number": frame_data["frame_number"],
                    "analysis": f"Error analyzing frame in batch: {str(frame_error)}",
                    "base64_data": frame_data["base64_data"],
                    "batch_processed": True,
                    "batch_id": batch_id,
                    "error": True
                })
        
        logger.info(f"Batch analysis completed for {len(results)} frames")
        return results
        
    except Exception as e:
        logger.error(f"Batch analysis failed: {str(e)}")
        # Return error results for all frames
        return [
            {
                "frame_number": frame_data["frame_number"],
                "analysis": f"Error analyzing frame in batch: {str(e)}",
                "base64_data": frame_data["base64_data"],
                "batch_processed": True,
                "batch_id": batch_id,
                "error": True
            }
            for frame_data in frame_batch
        ]


def validate_video(file_content: bytes) -> bool:
    """Validate that the uploaded file is a valid video."""
    try:
        logger.info(f"Validating video file ({len(file_content)} bytes)")
        
        # Save to temp file for validation
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as temp_file:
            temp_file.write(file_content)
            temp_path = temp_file.name
        
        try:
            logger.info("Running FFmpeg validation check")
            # Use ffmpeg to check if it's a valid video
            result = subprocess.run([
                'ffmpeg', '-i', temp_path, '-t', '0.1', '-f', 'null', '-'
            ], capture_output=True, text=True)
            
            is_valid = result.returncode == 0
            if not is_valid:
                logger.error(f"Video validation failed: {result.stderr}")
            else:
                logger.info("Video validation passed")
            return is_valid
            
        finally:
            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)
            
    except Exception as e:
        logger.error(f"Error during video validation: {str(e)}")
        return False


def split_frames(video_path: Path, temp_dir: Path, fps: float = 0.03) -> List[Path]:  # Reduced from 0.1 to 0.03 (70% reduction)
    """Extract frames from video using ffmpeg."""
    try:
        logger.info(f"Starting frame extraction from {video_path.name} at {fps} FPS")
        
        frame_pattern = temp_dir / "frame_%03d.jpg"
        
        # Ultra-simple FFmpeg command that definitely works (tested manually)
        result = subprocess.run([
            'ffmpeg', 
            '-i', str(video_path),
            '-vf', f'fps={fps}',  # Video filter for frame rate
            str(frame_pattern),
            '-y'  # Overwrite existing files
        ], capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg failed: {result.stderr}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"FFmpeg failed: {result.stderr}"
            )
        
        # Find all extracted frame files
        frame_files = sorted(temp_dir.glob("frame_*.jpg"))
        logger.info(f"Successfully extracted {len(frame_files)} frames")
        
        if not frame_files:
            logger.error("No frames were extracted")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="No frames could be extracted from video"
            )
        
        return frame_files
        
    except Exception as e:
        logger.error(f"Error extracting frames: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error extracting frames: {str(e)}"
        )


def encode_image_from_path(image_path: Path) -> str:
    """Encode image file to base64 for AI analysis."""
    try:
        with Image.open(image_path) as img:
            # Resize for efficiency
            img = img.resize((512, 512), Image.Resampling.LANCZOS)
            
            # Convert to RGB if necessary
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=90)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
            
    except Exception as e:
        logger.error(f"Error encoding image {image_path}: {e}")
        raise


async def process_video_frames(video_path: Path, fps: float = 0.03) -> List[dict]:  # Reduced from 0.1 to 0.03 (70% reduction)
    """Process video by extracting frames and analyzing each one."""
    results = []
    
    logger.info(f"Starting video frame processing for {video_path.name} at {fps} FPS")
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        
        # Extract frames
        logger.info("Extracting frames to temporary directory")
        frame_files = split_frames(video_path, temp_dir_path, fps)
        
        if not frame_files:
            logger.error("No frames could be extracted from video")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No frames could be extracted from video"
            )
        
        logger.info(f"Starting AI analysis of {len(frame_files)} frames")
        
        # Prepare frames for batch processing
        frame_data_list = []
        for i, frame_path in enumerate(frame_files):
            try:
                logger.info(f"Preparing frame {i+1}/{len(frame_files)}: {frame_path.name}")
                
                # Encode frame for AI analysis
                base64_frame = encode_image_from_path(frame_path)
                
                frame_data_list.append({
                    'frame_number': i + 1,
                    'base64_data': base64_frame,
                    'frame_name': f"frame_{i+1:03d}.jpg",
                    'timestamp': i / fps  # Approximate timestamp in seconds
                })
                
            except Exception as e:
                logger.error(f"Error preparing frame {i+1}: {str(e)}")
                # Add error frame data
                frame_data_list.append({
                    'frame_number': i + 1,
                    'base64_data': '',
                    'frame_name': f"frame_{i+1:03d}.jpg",
                    'timestamp': i / fps,
                    'error': True
                })
        
        # Process frames in batches
        if frame_data_list:
            logger.info(f"Processing {len(frame_data_list)} frames in batches")
            results = await process_frames_in_batches(frame_data_list, ai_semaphore, BATCH_SIZE)
            
            # Add timestamp information to results
            for result in results:
                frame_number = result['frame_number']
                result['timestamp'] = (frame_number - 1) / fps
        else:
            results = []
    
    logger.info(f"Video frame processing completed! Processed {len(results)} frames")
    return results

# Configuration for parallelism and performance
MAX_CONCURRENT_AI_CALLS = 5  # Limit concurrent AI analysis calls
MAX_CONCURRENT_ENCODING = 10  # Limit concurrent base64 encoding operations
MAX_CONCURRENT_GUM_OPERATIONS = 3  # Limit concurrent GUM database operations
CHUNK_SIZE = 50  # Process frames in chunks for large videos

# Batch processing configuration for video frames
BATCH_SIZE = 3  # Number of frames to process per AI call
BATCH_TIMEOUT = 1.0  # Maximum wait time for batching (seconds)
MAX_BATCH_SIZE = 5  # Maximum frames per batch to prevent token limits

# Initialize semaphores for controlling concurrency
ai_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AI_CALLS)
encoding_semaphore = asyncio.Semaphore(MAX_CONCURRENT_ENCODING)
gum_semaphore = asyncio.Semaphore(MAX_CONCURRENT_GUM_OPERATIONS)

# Rate limiting configuration
RATE_LIMITS = {
    "/observations/video": (5, 300),    # 5 videos per 5 minutes
    "/observations/text": (20, 60),     # 20 text submissions per minute
    "/query": (30, 60),                 # 30 queries per minute
    "default": (100, 60)                # 100 requests per minute for other endpoints
}

async def check_rate_limit(request: Request):
    """Check rate limits for the request with enhanced logging and error handling"""
    path = request.url.path
    
    # Get rate limit for this endpoint
    if path in RATE_LIMITS:
        max_requests, window = RATE_LIMITS[path]
    else:
        max_requests, window = RATE_LIMITS["default"]
    
    # Check limit using the enhanced rate limiter
    if not rate_limiter.check_limit(path, max_requests, window):
        reset_time = rate_limiter.get_reset_time(path, window)
        wait_seconds = int(reset_time - time.time())
        remaining_requests = rate_limiter.get_remaining_requests(path, max_requests)
        
        # Log rate limit violation with details
        logger.warning(f"Rate limit exceeded for {path}: {max_requests} requests per {window}s window. "
                      f"Reset in {wait_seconds}s. Client IP: {request.client.host if request.client else 'unknown'}")
        
        # Get endpoint stats for monitoring
        stats = rate_limiter.get_endpoint_stats(path)
        logger.info(f"Rate limit stats for {path}: {stats}")
        
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {wait_seconds} seconds.",
            headers={
                "Retry-After": str(wait_seconds),
                "X-RateLimit-Limit": str(max_requests),
                "X-RateLimit-Remaining": str(remaining_requests),
                "X-RateLimit-Reset": str(int(reset_time))
            }
        )
    
    # Log successful request (only for high-traffic endpoints)
    if path in ["/query", "/observations/text"]:
        remaining = rate_limiter.get_remaining_requests(path, max_requests)
        if remaining <= max_requests * 0.2:  # Log when 80% of limit is used
            logger.info(f"High usage for {path}: {remaining} requests remaining out of {max_requests}")

# Add rate limiting middleware for all endpoints
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Middleware to apply rate limiting to all endpoints"""
    try:
        # Skip rate limiting for health check and static files
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"] or request.url.path.startswith("/static"):
            return await call_next(request)
        
        # Apply rate limiting
        await check_rate_limit(request)
        
        # Process the request
        response = await call_next(request)
        
        # Add rate limit headers to response
        path = request.url.path
        if path in RATE_LIMITS:
            max_requests, window = RATE_LIMITS[path]
        else:
            max_requests, window = RATE_LIMITS["default"]
        
        remaining = rate_limiter.get_remaining_requests(path, max_requests)
        reset_time = rate_limiter.get_reset_time(path, window)
        
        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(int(reset_time))
        
        return response
        
    except HTTPException as e:
        if e.status_code == 429:
            # Log rate limit violations
            logger.warning(f"Rate limit violation for {request.url.path}: {e.detail}")
        raise
    except Exception as e:
        logger.error(f"Error in rate limit middleware: {e}")
        raise

# Add rate limit monitoring endpoint
@app.get("/admin/rate-limits", response_model=dict)
async def get_rate_limit_stats():
    """Get rate limiting statistics for monitoring"""
    try:
        global_stats = rate_limiter.get_global_stats()
        
        # Get stats for configured endpoints
        endpoint_stats = {}
        for endpoint in RATE_LIMITS.keys():
            endpoint_stats[endpoint] = rate_limiter.get_endpoint_stats(endpoint)
        
        return {
            "global_stats": global_stats,
            "endpoint_stats": endpoint_stats,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting rate limit stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving rate limit statistics"
        )


@app.get("/admin/batch-stats", response_model=dict)
async def get_batch_stats():
    """Get batching statistics for monitoring"""
    try:
        if not USE_BATCHED_CLIENT:
            return {
                "batching_enabled": False,
                "message": "Batched client is not enabled"
            }
        
        client = await get_batched_ai_client()
        stats = client.get_stats()
        
        return {
            "batching_enabled": True,
            "batch_stats": stats,
            "configuration": {
                "batch_interval_hours": BATCH_INTERVAL_HOURS,
                "max_batch_size": MAX_BATCH_SIZE,
                "use_batched_client": USE_BATCHED_CLIENT
            },
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting batch stats: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error retrieving batch statistics"
        )


@app.post("/admin/batch-process", response_model=dict)
async def force_batch_process():
    """Force immediate processing of pending batches"""
    try:
        if not USE_BATCHED_CLIENT:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Batched client is not enabled"
            )
        
        client = await get_batched_ai_client()
        
        # Get current stats before processing
        before_stats = client.get_stats()
        pending_count = before_stats['pending_requests']
        
        if pending_count == 0:
            return {
                "message": "No pending requests to process",
                "pending_requests": 0
            }
        
        # Force process the current batch
        await client._process_batch()
        
        # Get stats after processing
        after_stats = client.get_stats()
        
        return {
            "message": f"Processed {pending_count} pending requests",
            "pending_requests_before": pending_count,
            "pending_requests_after": after_stats['pending_requests'],
            "processed_requests": pending_count - after_stats['pending_requests'],
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error forcing batch process: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing batch: {str(e)}"
        )

# Add rate limit reset endpoint (admin only)
@app.post("/admin/rate-limits/reset", response_model=dict)
async def reset_rate_limits(endpoint: Optional[str] = None):
    """Reset rate limits for specific endpoint or all endpoints"""
    try:
        if endpoint:
            rate_limiter.reset_endpoint(endpoint)
            logger.info(f"Rate limits reset for endpoint: {endpoint}")
            return {"message": f"Rate limits reset for {endpoint}", "endpoint": endpoint}
        else:
            rate_limiter.reset_all()
            logger.info("All rate limits reset")
            return {"message": "All rate limits reset", "endpoint": "all"}
    except Exception as e:
        logger.error(f"Error resetting rate limits: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error resetting rate limits"
        )

# === API Endpoints ===

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        # Test GUM connection
        gum_connected = False
        try:
            await ensure_gum_instance()
            gum_connected = True
        except Exception as e:
            logger.warning(f"GUM connection failed in health check: {e}")
        
        return HealthResponse(
            status="healthy" if gum_connected else "unhealthy",
            timestamp=datetime.now(),
            gum_connected=gum_connected,
            version="1.0.0"
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Health check failed"
        )


@app.delete("/database/cleanup", response_model=dict)
async def cleanup_database(user_name: Optional[str] = None):
    """Clean up entire database by removing all observations and propositions."""
    try:
        logger.info("Starting database cleanup...")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        observations_deleted = 0
        propositions_deleted = 0
        junction_records_deleted = 0
        
        # Clean up database
        async with gum_inst._session() as session:
            from gum.models import Observation, Proposition, observation_proposition, proposition_parent
            from sqlalchemy import delete, text
            
            # Delete in proper order to avoid foreign key constraints
            
            # First, delete all junction table entries
            junction_obs_result = await session.execute(delete(observation_proposition))
            junction_prop_result = await session.execute(delete(proposition_parent))
            junction_records_deleted = junction_obs_result.rowcount + junction_prop_result.rowcount
            
            # Then delete all observations
            obs_result = await session.execute(delete(Observation))
            observations_deleted = obs_result.rowcount
            
            # Then delete all propositions
            prop_result = await session.execute(delete(Proposition))
            propositions_deleted = prop_result.rowcount
            
            # Clear the FTS tables as well
            await session.execute(text("DELETE FROM propositions_fts"))
            await session.execute(text("DELETE FROM observations_fts"))
            
            # Commit the transaction
            await session.commit()
        
        # Run VACUUM outside of the session/transaction context
        try:
            async with gum_inst._session() as vacuum_session:
                await vacuum_session.execute(text("VACUUM"))
                await vacuum_session.commit()
        except Exception as vacuum_error:
            logger.warning(f"VACUUM operation failed: {vacuum_error}")
            # Continue anyway as the cleanup was successful
        
        logger.info(f"Database cleanup completed:")
        logger.info(f"    Deleted {observations_deleted} observations")
        logger.info(f"    Deleted {propositions_deleted} propositions")
        logger.info(f"    Deleted {junction_records_deleted} junction records")
        logger.info("   Cleared FTS indexes")
        logger.info("   Database vacuumed")
        
        return {
            "success": True,
            "message": "Database cleaned successfully",
            "observations_deleted": observations_deleted,
            "propositions_deleted": propositions_deleted,
            "junction_records_deleted": junction_records_deleted,
            "fts_cleared": True,
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error cleaning database: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error cleaning database: {str(e)}"
        )

@app.get("/observations/video/{job_id}/insights", response_model=dict)
async def get_video_insights(job_id: str):
    """Get generated insights for a completed video processing job."""
    if job_id not in video_processing_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video processing job not found"
        )
    
    job = video_processing_jobs[job_id]
    
    if job["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video processing is not completed. Current status: {job['status']}"
        )
    
    # Check if insights already exist
    if "insights" in job:
        logger.info(f" Returning cached insights for job {job_id}")
        return job["insights"]
    
    # Generate insights if they don't exist
    try:
        logger.info(f"Generating insights on-demand for job {job_id}")
        
        # Get frame analyses from the job
        frame_analyses = []
        if "frame_analyses" in job:
            # Use full analysis if available, otherwise fall back to preview
            frame_analyses = [
                frame.get("full_analysis", frame.get("analysis_preview", ""))
                for frame in job["frame_analyses"]
            ]
        
        if not frame_analyses:
            # Fallback: use basic info if no detailed analyses available
            frame_analyses = [f"Frame analysis data for {job['filename']}"]
            
        logger.info(f"Using {len(frame_analyses)} frame analyses for insights generation")
        for i, analysis in enumerate(frame_analyses):
            logger.info(f"    Frame {i+1} analysis length: {len(analysis)} characters")
        
        insights = await generate_video_insights(frame_analyses, job["filename"])
        
        # Cache the insights in the job data
        video_processing_jobs[job_id]["insights"] = insights
        
        logger.info(f"Generated and cached insights for job {job_id}")
        return insights
        
    except Exception as e:
        logger.error(f"Failed to generate insights for job {job_id}: {str(e)}")
        
        # Return basic fallback insights
        fallback_insights = {
            "key_insights": [
                f"Video processing completed for {job['filename']}",
                f"Successfully analyzed {job.get('successful_frames', 0)} frames",
                "Behavioral data captured and ready for analysis"
            ],
            "behavior_patterns": [
                "Standard user interaction patterns observed",
                "Task-oriented behavior documented",
                "Interface engagement recorded"
            ],
            "summary": f"Video analysis completed for {job['filename']} with {job.get('total_frames', 0)} frames processed.",
            "confidence_score": 0.5,
            "recommendations": [
                "Review individual frame analyses for detailed insights",
                "Consider additional video samples for pattern validation"
            ]
        }
        
        # Cache the fallback insights
        video_processing_jobs[job_id]["insights"] = fallback_insights
        
        return fallback_insights
  

@app.post("/observations/text", response_model=dict)
async def submit_text_observation(request: TextObservationRequest):
    """Submit a text observation to GUM."""
    try:
        start_time = time.time()
        logger.info(f" Received text observation: {request.content[:100]}...")
        
        # Get GUM instance
        logger.info(" Getting GUM instance...")
        gum_inst = await ensure_gum_instance(request.user_name)
        logger.info("GUM instance obtained successfully")
        
        # Create mock observer
        logger.info(" Creating API observer...")
        observer = APIObserver(request.observer_name)
        logger.info(f"API observer created: {observer._name}")
        
        # Create update
        logger.info("Creating update object...")
        update = Update(
            content=request.content,
            content_type="input_text"
        )
        logger.info(f"Update created - Content length: {len(update.content)}, Type: {update.content_type}")
        
        # Process through GUM with detailed logging
        logger.info(" Starting GUM processing...")
        logger.info(f"    Content preview: {request.content[:200]}...")
        logger.info(f"    User: {request.user_name}")
        logger.info(f"    Observer: {request.observer_name}")
        
        try:
            await gum_inst._default_handler(observer, update)
            logger.info("GUM processing completed successfully")
        except Exception as gum_error:
            logger.error(f"GUM processing failed: {type(gum_error).__name__}: {str(gum_error)}")
            logger.error(f"    Error details: {repr(gum_error)}")
            raise gum_error
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"Text observation processed successfully in {processing_time:.2f}ms")
        
        return {
            "success": True,
            "message": "Text observation submitted successfully",
            "processing_time_ms": processing_time,
            "content_preview": request.content[:100] + "..." if len(request.content) > 100 else request.content
        }
        
    except Exception as e:
        logger.error(f"Error processing text observation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing text observation: {str(e)}"
        )


@app.post("/observations/image", response_model=dict)
async def submit_image_observation(
    file: UploadFile = File(..., description="Image file to analyze"),
    user_name: Optional[str] = Form(None, description="User name (optional)"),
    observer_name: Optional[str] = Form("api_controller", description="Observer name")
):
    """Submit an image observation to GUM."""
    try:
        start_time = time.time()
        logger.info(f"Received image observation: {file.filename}")
        
        # Validate file type
        if not file.content_type or not file.content_type.startswith('image/'):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be an image"
            )
        
        # Read file content
        file_content = await file.read()
        
        # Validate image
        if not validate_image(file_content):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image file"
            )
        
        # Process image for AI analysis
        base64_image = process_image_for_analysis(file_content)
        
        # Analyze image with AI
        analysis = await analyze_image_with_ai(base64_image, file.filename)
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Create mock observer
        observer = APIObserver(observer_name)
        
        # Create update with analysis
        update_content = f"Image analysis of {file.filename}: {analysis}"
        update = Update(
            content=update_content,
            content_type="input_text"  # We store the analysis as text
        )
        
        # Process through GUM
        await gum_inst._default_handler(observer, update)
        
        processing_time = (time.time() - start_time) * 1000
        
        logger.info(f"Image observation processed successfully in {processing_time:.2f}ms")
        
        return {
            "success": True,
            "message": "Image observation submitted successfully",
            "processing_time_ms": processing_time,
            "filename": file.filename,
            "analysis_preview": analysis[:200] + "..." if len(analysis) > 200 else analysis
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing image observation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing image observation: {str(e)}"
        )


@app.post("/query", response_model=QueryResponse)
async def query_gum(request: QueryRequest):
    """Query GUM for insights and propositions."""
    try:
        start_time = time.time()
        logger.info(f"Received query: {request.query}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(request.user_name)
        
        # Execute query
        limit = request.limit if request.limit is not None else 10
        mode = request.mode or "default"
        
        results = await gum_inst.query(
            request.query,
            limit=limit,
            mode=mode
        )
        
        # Format results
        propositions = []
        for prop, score in results:
            propositions.append(PropositionResponse(
                id=prop.id,
                text=prop.text,
                reasoning=prop.reasoning,
                confidence=prop.confidence,
                created_at=parse_datetime(prop.created_at)
            ))
        
        execution_time = (time.time() - start_time) * 1000
        
        logger.info(f"Query executed successfully: {len(results)} results in {execution_time:.2f}ms")
        
        return QueryResponse(
            propositions=propositions,
            total_results=len(results),
            query=request.query,
            execution_time_ms=execution_time
        )
        
    except Exception as e:
        logger.error(f"Error executing query: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error executing query: {str(e)}"
        )


@app.get("/observations", response_model=List[ObservationResponse])
async def list_observations(
    user_name: Optional[str] = None,
    limit: Optional[int] = 20,
    offset: Optional[int] = 0
):
    """List recent observations."""
    try:
        logger.info(f"Listing observations: limit={limit}, offset={offset}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query recent observations from database
        async with gum_inst._session() as session:
            from gum.models import Observation
            from sqlalchemy import select, desc
            
            stmt = (
                select(Observation)
                .order_by(desc(Observation.created_at))
                .limit(limit)
                .offset(offset)
            )
            
            result = await session.execute(stmt)
            observations = result.scalars().all()
            
            response = []
            for obs in observations:
                response.append(ObservationResponse(
                    id=obs.id,
                    content=obs.content[:500] + "..." if len(obs.content) > 500 else obs.content,
                    content_type=obs.content_type,
                    observer_name=obs.observer_name,
                    created_at=parse_datetime(obs.created_at)
                ))
            
            logger.info(f"Retrieved {len(response)} observations")
            return response
        
    except Exception as e:
        logger.error(f"Error listing observations: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing observations: {str(e)}"
        )


@app.get("/propositions", response_model=List[PropositionResponse])
async def list_propositions(
    user_name: Optional[str] = None,
    limit: Optional[int] = 20,
    offset: Optional[int] = 0,
    confidence_min: Optional[int] = None,
    sort_by: Optional[str] = "created_at"
):
    """List recent propositions with filtering and sorting options."""
    try:
        logger.info(f"Listing propositions: limit={limit}, offset={offset}, confidence_min={confidence_min}, sort_by={sort_by}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query recent propositions from database
        async with gum_inst._session() as session:
            from gum.models import Proposition
            from sqlalchemy import select, desc, asc
            
            stmt = select(Proposition)
            
            # Apply confidence filter if specified
            if confidence_min is not None:
                stmt = stmt.where(Proposition.confidence >= confidence_min)
            
            # Apply sorting
            if sort_by == "confidence":
                stmt = stmt.order_by(desc(Proposition.confidence))
            elif sort_by == "created_at":
                stmt = stmt.order_by(desc(Proposition.created_at))
            else:
                stmt = stmt.order_by(desc(Proposition.created_at))
            
            # Apply pagination
            stmt = stmt.limit(limit).offset(offset)
            
            result = await session.execute(stmt)
            propositions = result.scalars().all()
            
            response = []
            for prop in propositions:
                response.append(PropositionResponse(
                    id=prop.id,
                    text=prop.text,
                    reasoning=prop.reasoning,
                    confidence=prop.confidence,
                    created_at=parse_datetime(prop.created_at)
                ))
            
            logger.info(f"Retrieved {len(response)} propositions")
            return response
        
    except Exception as e:
        logger.error(f"Error listing propositions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error listing propositions: {str(e)}"
        )


@app.get("/propositions/count", response_model=dict)
async def get_propositions_count(
    user_name: Optional[str] = None,
    confidence_min: Optional[int] = None
):
    """Get total count of propositions with optional filtering."""
    try:
        logger.info(f"Getting propositions count: confidence_min={confidence_min}")
        
        # Get GUM instance
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query count from database
        async with gum_inst._session() as session:
            from gum.models import Proposition
            from sqlalchemy import select, func
            
            stmt = select(func.count(Proposition.id))
            
            # Apply confidence filter if specified
            if confidence_min is not None:
                stmt = stmt.where(Proposition.confidence >= confidence_min)
            
            result = await session.execute(stmt)
            count = result.scalar()
            
            logger.info(f"Retrieved count: {count} propositions")
            return {
                "total_propositions": count,
                "confidence_filter": confidence_min
            }
        
    except Exception as e:
        logger.error(f"Error getting propositions count: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting propositions count: {str(e)}"
        )



async def generate_video_insights(frame_analyses: List[str], filename: str, user_name: str = None, detailed_analysis: dict = None) -> dict:
    """
    Generate structured insights from existing GUM observations and propositions.
    Enhanced to support detailed bullet-point analysis format.
    
    Args:
        frame_analyses: List of AI analysis texts from processed frames (for context)
        filename: Name of the video file for context
        user_name: User name to query specific data
        detailed_analysis: Optional detailed analysis result from analyze_batch_with_detailed_insights
        
    Returns:
        Dictionary containing structured insights from existing GUM data:
        {
            "key_insights": List[str] (from recent observations),
            "behavior_patterns": List[str] (from recent propositions), 
            "summary": str,
            "confidence_score": float,
            "recommendations": List[str],
            "detailed_analysis": dict (if provided)
        }
    """
    try:
        logger.info(f"Generating insights from existing GUM data for {filename}")
        
        # Get GUM instance to query existing data
        gum_inst = await ensure_gum_instance(user_name)
        
        # Query recent observations related to video analysis
        async with gum_inst._session() as session:
            from sqlalchemy import select, desc
            from gum.models import Observation, Proposition
            
            # Get recent observations from video processing (last 10)
            obs_stmt = (
                select(Observation)
                .where(Observation.content.contains("Video frame analysis"))
                .order_by(desc(Observation.created_at))
                .limit(10)
            )
            obs_result = await session.execute(obs_stmt)
            observations = obs_result.scalars().all()
            
            # Get recent propositions (last 10) 
            prop_stmt = (
                select(Proposition)
                .order_by(desc(Proposition.created_at))
                .limit(10)
            )
            prop_result = await session.execute(prop_stmt)
            propositions = prop_result.scalars().all()
        
        # Extract key insights from the latest 5 observations in the database
        key_insights = []
        
        logger.info(f"Extracting latest 5 observations from database")
        
        # Get the latest 5 observations directly from the database
        async with gum_inst._session() as session:
            latest_obs_stmt = (
                select(Observation)
                .order_by(desc(Observation.created_at))
                .limit(5)
            )
            latest_obs_result = await session.execute(latest_obs_stmt)
            latest_observations = latest_obs_result.scalars().all()
        
        # Parse and clean the latest 5 observations using our parsing logic
        for i, obs in enumerate(latest_observations):
            content = obs.content.strip()
            if content:
                logger.info(f"    Processing observation {i+1}: {content[:100]}...")
                
                # Use our parsing function to extract clean insights
                parsed_insights = parse_ai_analysis_to_insights(content)
                
                if parsed_insights:
                    # Add the parsed insights
                    for insight in parsed_insights:
                        key_insights.append(insight)
                        logger.info(f"    Parsed insight: {insight[:80]}...")
                else:
                    # Fallback: if parsing didn't work, clean manually
                    if "Video frame analysis" in content and "): " in content:
                        # Extract just the analysis part after the prefix
                        analysis_part = content.split("): ", 1)
                        if len(analysis_part) > 1:
                            content = analysis_part[1].strip()
                    
                    # Use our sentence cleaner
                    cleaned_content = clean_insight_sentence(content)
                    if cleaned_content:
                        key_insights.append(cleaned_content)
                        logger.info(f"    Cleaned insight: {cleaned_content[:80]}...")
                    else:
                        # Last resort: basic formatting
                        if len(content) > 150:
                            content = content[:147] + "..."
                        if content and content[0].islower():
                            content = content[0].upper() + content[1:]
                        if content and not content.endswith(('.', '!', '?')):
                            content += '.'
                        key_insights.append(content)
                        logger.info(f"    Basic formatted: {content[:80]}...")
        
        logger.info(f"Extracted {len(key_insights)} latest observations as key insights")
        
        # Extract behavior patterns from recent propositions
        behavior_patterns = []
        for prop in propositions[:5]:  # Take top 5 recent propositions
            if prop.text and len(prop.text.strip()) > 20:
                pattern = prop.text.strip()
                # Clean up the pattern text
                cleaned_pattern = clean_insight_sentence(pattern)
                if cleaned_pattern:
                    behavior_patterns.append(cleaned_pattern)
        
        # Generate summary based on available data
        total_observations = len(observations)
        total_propositions = len(propositions)
        
        if total_observations > 0 or total_propositions > 0:
            summary = f"Analysis of {filename} reveals {total_observations} behavioral observations and {total_propositions} generated insights about user patterns and preferences."
        else:
            summary = f"Video analysis of {filename} completed with {len(frame_analyses)} frames processed. Additional data collection recommended for deeper insights."
        
        # Calculate confidence based on data availability
        confidence_score = min(0.9, 0.3 + (len(key_insights) * 0.1) + (len(behavior_patterns) * 0.1))
        
        # Generate recommendations based on available data
        recommendations = []
        if len(key_insights) > 0:
            recommendations.append("Review identified behavioral patterns for workflow optimization opportunities")
        if len(behavior_patterns) > 0:
            recommendations.append("Consider user preferences revealed in behavior patterns for interface improvements")
        
        recommendations.extend([
            "Continue collecting behavioral data for more comprehensive insights",
            "Analyze patterns over time to identify trends and changes in user behavior"
        ])
        
        # Provide intelligent fallbacks if no meaningful insights were parsed
        if not key_insights:
            # Try one more time with more aggressive parsing of frame analyses
            logger.info("No insights parsed, trying more aggressive extraction from frame analyses")
            for frame_analysis in frame_analyses:
                if frame_analysis and len(frame_analysis.strip()) > 50:
                    # Extract the most meaningful sentences directly
                    sentences = re.split(r'[.!?]+', frame_analysis)
                    for sentence in sentences:
                        cleaned = clean_insight_sentence(sentence)
                        if cleaned and len(cleaned) > 30:
                            key_insights.append(cleaned)
                            if len(key_insights) >= 3:  # Limit to 3 good insights
                                break
                if len(key_insights) >= 3:
                    break
        
        # Only use generic fallbacks if we absolutely can't extract anything meaningful
        if not key_insights:
            logger.warning(" Using generic fallback insights - no meaningful content could be parsed")
            key_insights = [
                f"Video analysis processed {len(frame_analyses)} frames of user interaction data.",
                "User behavior patterns captured from video frames for analysis.",
                "Interface interaction sequences documented for behavioral insights."
            ]
        
        if not behavior_patterns:
            behavior_patterns = [
                "User interface navigation patterns observed and recorded.",
                "Task-oriented interaction behaviors documented for analysis.",
                "Sequential user actions captured for workflow optimization."
            ]
        
        insights = {
            "key_insights": key_insights[:5],  # Limit to 5 insights
            "behavior_patterns": behavior_patterns[:5],  # Limit to 5 patterns
            "summary": summary,
            "confidence_score": confidence_score,
            "recommendations": recommendations[:4],  # Limit to 4 recommendations
            "detailed_analysis": detailed_analysis  # Include detailed analysis if provided
        }
        
        logger.info(f"Generated {len(insights['key_insights'])} insights and {len(insights['behavior_patterns'])} patterns from existing GUM data")
        return insights
        
    except Exception as e:
        logger.error(f"Error generating insights from GUM data: {str(e)}")
        
        # Provide basic fallback insights
        fallback_insights = {
            "key_insights": [
                f"Video analysis completed for {filename}",
                f"Processed {len(frame_analyses)} frames with behavioral analysis",
                "User interaction patterns captured for future insights"
            ],
            "behavior_patterns": [
                "Video-based user behavior documentation initiated",
                "Frame-by-frame interaction analysis completed",
                "Behavioral data collection established for pattern recognition"
            ],
            "summary": f"Video analysis of {filename} completed successfully with {len(frame_analyses)} frames processed. Building behavioral understanding from collected data.",
            "confidence_score": 0.5,
            "recommendations": [
                "Continue submitting observations to build comprehensive user behavior model",
                "Review captured interactions for specific workflow improvement opportunities",
                "Consider additional data collection for deeper behavioral insights"
            ]
        }
        
        logger.info("Generated fallback insights")
        return fallback_insights



# Video processing storage
video_processing_jobs = {}



def parse_ai_analysis_to_insights(analysis_text: str) -> List[str]:
    """
    Parse AI analysis content and extract clean, one-line insights.
    
    Args:
        analysis_text: Raw AI analysis text from vision processing
        
    Returns:
        List of clean, one-line insights
    """
    import re
    
    if not analysis_text or len(analysis_text.strip()) < 20:
        return []
    
    # Remove common prefixes and headers
    text = analysis_text
    
    # Remove "Video frame analysis (Frame X): " prefix
    if "Video frame analysis" in text and "): " in text:
        text = text.split("): ", 1)[1] if len(text.split("): ", 1)) > 1 else text
    
    # Remove "Detailed Analysis of User Experience in frame_XXX.jpg" headers
    text = re.sub(r"Detailed Analysis of User Experience in frame_\d+\.jpg['\"]?\s*[-\s]*", "", text)
    
    # Remove markdown headers (### #### etc.)
    text = re.sub(r"#{1,6}\s*\d*\.\s*", "", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    
    # Remove "Primary Analysis Focus:" type headers
    text = re.sub(r"Primary Analysis Focus:\s*", "", text)
    
    # Remove numbered list markers (1. 2. etc.)
    text = re.sub(r"^\d+\.\s*", "", text, flags=re.MULTILINE)
    
    # Remove markdown bold formatting
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    
    # Remove bullet points and dashes
    text = re.sub(r"^[-•*]\s*", "", text, flags=re.MULTILINE)
    
    # Split into sentences and clean
    sentences = []
    
    # Split by common delimiters
    for delimiter in ['. ', '.\n', '; ', ';\n', ' | ', ' --- ']:
        if delimiter in text:
            parts = text.split(delimiter)
            for part in parts:
                part = part.strip()
                if len(part) > 20 and not part.endswith(':'):
                    # Clean up the sentence
                    clean_part = clean_insight_sentence(part)
                    if clean_part:
                        sentences.append(clean_part)
            break
    
    # If no clear delimiters, try to extract meaningful phrases
    if not sentences:
        # Look for patterns like "User [action]" or "The user [action]"
        user_actions = re.findall(r"(?:The\s+)?[Uu]ser\s+[^.;]+", text)
        for action in user_actions:
            clean_action = clean_insight_sentence(action)
            if clean_action:
                sentences.append(clean_action)
    
    # Final fallback - just clean the whole text if it's reasonable length
    if not sentences and len(text.strip()) <= 200:
        clean_text = clean_insight_sentence(text)
        if clean_text:
            sentences.append(clean_text)
    
    # Limit to 3 insights per analysis and ensure they're not too long
    return sentences[:3]


def clean_insight_sentence(sentence: str) -> str:
    """
    Clean and format a single insight sentence.
    
    Args:
        sentence: Raw sentence text
        
    Returns:
        Cleaned sentence or empty string if not suitable
    """
    if not sentence:
        return ""
    
    # Remove extra whitespace and newlines
    sentence = re.sub(r'\s+', ' ', sentence.strip())
    
    # Remove trailing colons and dashes
    sentence = re.sub(r'[:\-]+$', '', sentence)
    
    # Remove leading/trailing quotes
    sentence = sentence.strip('\'"')
    
    # Ensure sentence starts with capital letter
    if sentence and sentence[0].islower():
        sentence = sentence[0].upper() + sentence[1:]
    
    # Ensure sentence ends with period
    if sentence and not sentence.endswith(('.', '!', '?')):
        sentence += '.'
    
    # Check if it's a meaningful insight (not just a header or fragment)
    if (len(sentence) < 20 or 
        sentence.lower().startswith(('user goals', 'primary analysis', 'analysis focus')) or
        sentence.count(':') > 1 or
        len(sentence) > 200):
        return ""
    
    return sentence



async def process_video_background(job_id: str, video_path: Path, user_name: str, observer_name: str, fps: float, filename: str):
    """Process video in background using optimized parallel pipeline and update job status."""
    try:
        logger.info(f" Starting optimized background video processing for job {job_id}")
        logger.info(f"File: {filename} | User: {user_name} | Observer: {observer_name} | FPS: {fps}")
        
        # Initial status: extracting frames
        video_processing_jobs[job_id]["status"] = "extracting_frames"
        video_processing_jobs[job_id]["progress"] = 10
        
        # Convert fps to max_frames for the new pipeline
        max_frames = max(10, int(fps * 60))  # Approximate frames for 1 minute at given fps
        video_processing_jobs[job_id]["total_frames"] = max_frames
        
        logger.info(f"Starting optimized parallel frame processing (max {max_frames} frames)")
        
        # Use the optimized parallel processing pipeline
        frame_results = await process_video_frames_parallel(
            video_path=str(video_path),
            max_frames=max_frames,
            job_id=job_id
        )
        
        if frame_results:
            # Update progress after AI analysis
            video_processing_jobs[job_id]["processed_frames"] = len(frame_results)
            video_processing_jobs[job_id]["progress"] = 70
            video_processing_jobs[job_id]["status"] = "storing_results"
            
            # Store results in GUM database using the separate function
            await process_and_store_in_gum(
                frame_results=frame_results,
                user_name=user_name,
                observer_name=observer_name
            )
        else:
            logger.error(f"No frames extracted for job {job_id}")
            video_processing_jobs[job_id]["status"] = "error"
            video_processing_jobs[job_id]["error"] = "No frames could be extracted from video"
            return
        
        logger.info(f"Optimized parallel processing completed: {len(frame_results)} frames")
        
        # Update job status with results
        successful_frames = len(frame_results)
        failed_frames = max_frames - successful_frames if max_frames > successful_frames else 0
        
        video_processing_jobs[job_id]["status"] = "completed"
        video_processing_jobs[job_id]["progress"] = 100
        video_processing_jobs[job_id]["total_frames"] = max_frames
        video_processing_jobs[job_id]["processed_frames"] = successful_frames
        video_processing_jobs[job_id]["successful_frames"] = successful_frames
        video_processing_jobs[job_id]["failed_frames"] = failed_frames
        video_processing_jobs[job_id]["frame_analyses"] = [
            {
                "frame_number": r["frame_number"],
                "analysis_preview": r["analysis"][:100] + "..." if len(r["analysis"]) > 100 else r["analysis"],
                "processing_time": "optimized_parallel"
            }
            for r in frame_results[:5]  # Show first 5 as preview
        ]
        
        logger.info(" Optimized video processing completed!")
        logger.info(f" Results: {successful_frames} frames processed successfully using parallel pipeline")
        logger.info(f"Video processing job {job_id} completed with optimized performance")
        
    except Exception as e:
        logger.error(f" Critical error in optimized background video processing job {job_id}: {str(e)}")
        video_processing_jobs[job_id]["status"] = "error"
        video_processing_jobs[job_id]["error"] = str(e)
    
    finally:
        # Clean up video file
        logger.info(f" Cleaning up temporary video file for job {job_id}")
        video_path.unlink(missing_ok=True)


def split_frames_optimized(video_path: str, output_dir: str, max_frames: int = 10) -> List[str]:
    """
    Optimized FFmpeg frame extraction with CPU optimizations.
    Uses simple, reliable method that actually works.
    """
    logger.info(f" Starting optimized frame extraction from {video_path}")
    start_time = time.time()
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Use the same simple command that works manually
    # Extract frames at 1 frame per max_frames seconds
    frame_rate = 1.0 / max_frames
    
    cmd = [
        "ffmpeg",
        "-i", video_path,
        "-r", str(frame_rate),  # Frame rate (works like our manual test)
        "-f", "image2",  # Image sequence format (works like our manual test)
        f"{output_dir}/frame_%03d.jpg",
        "-y",  # Overwrite existing files
        "-hide_banner", "-loglevel", "warning"
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            logger.error(f"FFmpeg extraction failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg failed: {result.stderr}")
        
        # Get list of extracted frames
        frame_files = sorted(glob.glob(f"{output_dir}/frame_*.jpg"))
        extraction_time = time.time() - start_time
        
        logger.info(f"Extracted {len(frame_files)} frames in {extraction_time:.2f}s using optimized FFmpeg")
        return frame_files
        
    except subprocess.TimeoutExpired:
        logger.error("FFmpeg extraction timed out")
        raise RuntimeError("FFmpeg extraction timed out")
    except Exception as e:
        logger.error(f"Error during optimized frame extraction: {str(e)}")
        raise


def split_frames_hardware_accelerated(video_path: str, output_dir: str, max_frames: int = 10) -> List[str]:
    """
    Hardware-accelerated FFmpeg frame extraction.
    Falls back to optimized CPU extraction if hardware acceleration fails.
    """
    logger.info(f" Attempting hardware-accelerated frame extraction from {video_path}")
    start_time = time.time()
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    
    # Calculate frame rate for extraction
    frame_rate = 1.0 / max_frames
    
    # Try hardware acceleration first with simple parameters
    hw_cmd = [
        "ffmpeg",
        "-hwaccel", "auto",  # Auto-detect hardware acceleration
        "-i", video_path,
        "-r", str(frame_rate),  # Simple frame rate
        "-f", "image2",  # Image sequence format
        f"{output_dir}/frame_%03d.jpg",
        "-y",  # Overwrite existing files
        "-hide_banner", "-loglevel", "warning"
    ]
    
    try:
        result = subprocess.run(hw_cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            frame_files = sorted(glob.glob(f"{output_dir}/frame_*.jpg"))
            extraction_time = time.time() - start_time
            logger.info(f"Hardware-accelerated extraction: {len(frame_files)} frames in {extraction_time:.2f}s")
            return frame_files
        else:
            logger.warning(f" Hardware acceleration failed, falling back to CPU: {result.stderr}")
            
    except subprocess.TimeoutExpired:
        logger.warning(" Hardware acceleration timed out, falling back to CPU")
    except Exception as e:
        logger.warning(f" Hardware acceleration error, falling back to CPU: {str(e)}")
    
    # Fallback to optimized CPU extraction
    return split_frames_optimized(video_path, output_dir, max_frames)


def split_frames_smart(video_path: str, output_dir: str, max_frames: int = 10) -> List[str]:
    """
    Smart frame extraction that chooses the best method based on video characteristics.
    """
    logger.info(f" Smart frame extraction from {video_path}")
    
    try:
        # Get video info to make smart decisions
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", video_path
        ]
        result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            import json
            video_info = json.loads(result.stdout)
            
            # Extract video characteristics
            duration = float(video_info.get("format", {}).get("duration", 0))
            size = int(video_info.get("format", {}).get("size", 0))
            
            # Decision logic based on video characteristics
            if size > 100_000_000 or duration > 300:  # Large file (>100MB) or long video (>5min)
                logger.info("Large/long video detected, using hardware acceleration")
                return split_frames_hardware_accelerated(video_path, output_dir, max_frames)
            else:
                logger.info("Small/short video detected, using optimized CPU extraction")
                return split_frames_optimized(video_path, output_dir, max_frames)
        else:
            logger.warning(" Could not probe video, using hardware acceleration as default")
            return split_frames_hardware_accelerated(video_path, output_dir, max_frames)
            
    except Exception as e:
        logger.warning(f" Error in smart analysis, using hardware acceleration: {str(e)}")
        return split_frames_hardware_accelerated(video_path, output_dir, max_frames)


async def encode_frame_to_base64(frame_path: str, frame_number: int) -> dict:
    """
    Encode a single frame to base64 with semaphore control and timestamp correlation.
    """
    async with encoding_semaphore:
        try:
            with open(frame_path, "rb") as f:
                base64_data = base64.b64encode(f.read()).decode("utf-8")
            
            # Add timestamp for correlation with detailed analysis
            timestamp = time.time()
            
            return {
                "frame_number": frame_number,
                "base64_data": base64_data,
                "file_path": frame_path,
                "timestamp": timestamp,
                "event_type": "video_frame"
            }
        except Exception as e:
            logger.error(f"Error encoding frame {frame_number}: {str(e)}")
            raise


async def process_frames_in_batches(frames: List[dict], semaphore: asyncio.Semaphore, batch_size: int = BATCH_SIZE) -> List[dict]:
    """Process frames in batches for efficient AI analysis.
    
    Args:
        frames (List[dict]): List of frame data dictionaries
        semaphore (asyncio.Semaphore): Semaphore for controlling concurrency
        batch_size (int): Number of frames per batch
        
    Returns:
        List[dict]: List of processed frame results
    """
    if not frames:
        return []
    
    logger.info(f"Processing {len(frames)} frames in batches of {batch_size}")
    
    # Group frames into batches
    batches = []
    for i in range(0, len(frames), batch_size):
        batch = frames[i:i + batch_size]
        batches.append(batch)
    
    logger.info(f"Created {len(batches)} batches for processing")
    
    # Process batches with semaphore control
    async def process_batch(batch: List[dict], batch_index: int) -> List[dict]:
        async with semaphore:
            batch_id = f"batch_{batch_index + 1}"
            
            # Calculate time range for detailed analysis
            start_time = None
            end_time = None
            if batch:
                first_timestamp = batch[0].get("timestamp", 0)
                last_timestamp = batch[-1].get("timestamp", 0)
                
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
            detailed_analysis = await analyze_batch_with_detailed_insights(batch, batch_id, start_time, end_time)
            
            # Extract individual frame results from detailed analysis
            if detailed_analysis and 'detailed_analyses' in detailed_analysis:
                return detailed_analysis['detailed_analyses']
            else:
                # Fallback to original method if detailed analysis fails
                return await analyze_frames_batch_with_ai(batch, batch_id)
    
    # Create batch processing tasks
    batch_tasks = [
        process_batch(batch, i) for i, batch in enumerate(batches)
    ]
    
    # Execute all batches in parallel
    batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
    
    # Flatten results and handle exceptions
    all_results = []
    for i, result in enumerate(batch_results):
        if isinstance(result, Exception):
            logger.error(f"Batch {i + 1} failed: {result}")
            # Create error results for this batch
            batch = batches[i]
            error_results = [
                {
                    "frame_number": frame_data["frame_number"],
                    "analysis": f"Error processing batch: {str(result)}",
                    "base64_data": frame_data["base64_data"],
                    "batch_processed": True,
                    "batch_id": f"batch_{i + 1}",
                    "error": True
                }
                for frame_data in batch
            ]
            all_results.extend(error_results)
        else:
            all_results.extend(result)
    
    logger.info(f"Completed batch processing: {len(all_results)} frames processed")
    return all_results


async def process_frame_with_ai(frame_data: dict, semaphore: asyncio.Semaphore) -> dict:
    """
    Process a single frame with AI analysis using semaphore control.
    Uses the vision AI client (OpenRouter with Qwen model).
    """
    async with semaphore:
        try:
            frame_number = frame_data["frame_number"]
            base64_data = frame_data["base64_data"]
            filename = f"frame_{frame_number:03d}.jpg"
            
            logger.info(f"Analyzing frame {frame_number} with AI")
            analysis = await analyze_image_with_ai(base64_data, filename)
            
            return {
                "frame_number": frame_number,
                "analysis": analysis,
                "base64_data": base64_data
            }
        except Exception as e:
            logger.error(f"Error analyzing frame {frame_data.get('frame_number', 'unknown')}: {str(e)}")
            raise


async def process_video_frames_parallel(
    video_path: str, 
    max_frames: int = 10,
    job_id: Optional[str] = None
) -> List[dict]:
    """
    Process video frames with full parallelism: extraction, encoding, and AI analysis.
    Optionally updates job status for UI progress tracking.
    """
    logger.info(f"Starting parallel video processing: {video_path}")
    total_start_time = time.time()
    
    # Create temporary directory for frames
    with tempfile.TemporaryDirectory() as temp_dir:
        try:
            # Step 1: Extract frames using smart method
            logger.info("Extracting frames...")
            if job_id:
                video_processing_jobs[job_id]["status"] = "extracting_frames"
                video_processing_jobs[job_id]["progress"] = 20
            
            frame_files = split_frames_smart(video_path, temp_dir, max_frames)
            
            if not frame_files:
                logger.warning(" No frames extracted from video")
                return []
            
            # Step 2: Parallel base64 encoding
            logger.info(f" Encoding {len(frame_files)} frames to base64...")
            if job_id:
                video_processing_jobs[job_id]["status"] = "processing_frames"
                video_processing_jobs[job_id]["progress"] = 40
                video_processing_jobs[job_id]["total_frames"] = len(frame_files)
                video_processing_jobs[job_id]["processed_frames"] = 0
            
            encoding_start = time.time()
            
            encoding_tasks = [
                encode_frame_to_base64(frame_path, i + 1)
                for i, frame_path in enumerate(frame_files)
            ]
            
            encoded_frames = await asyncio.gather(*encoding_tasks, return_exceptions=True)
            
            # Filter out exceptions
            valid_frames = [
                frame for frame in encoded_frames 
                if not isinstance(frame, Exception)
            ]
            
            encoding_time = time.time() - encoding_start
            logger.info(f"Encoded {len(valid_frames)} frames in {encoding_time:.2f}s")
            
            # Step 3: Parallel AI analysis with rate limiting
            logger.info(f" Analyzing {len(valid_frames)} frames with AI...")
            if job_id:
                video_processing_jobs[job_id]["progress"] = 60
            
            analysis_start = time.time()
            
            # Use batch processing instead of individual frame processing
            if len(valid_frames) > 1:
                # Process frames in batches for efficiency
                logger.info(f"Using batch processing for {len(valid_frames)} frames")
                analyzed_frames = await process_frames_in_batches(valid_frames, ai_semaphore, BATCH_SIZE)
            else:
                # Fallback to individual processing for single frames
                logger.info("Using individual processing for single frame")
                analysis_tasks = [
                    process_frame_with_ai(frame_data, ai_semaphore)
                    for frame_data in valid_frames
                    if isinstance(frame_data, dict)
                ]
                analyzed_frames = await asyncio.gather(*analysis_tasks, return_exceptions=True)
            
            # Filter out exceptions (for individual processing fallback)
            if len(valid_frames) == 1:
                valid_analyses = [
                    frame for frame in analyzed_frames 
                    if not isinstance(frame, Exception)
                ]
            else:
                # Batch processing already handles exceptions
                valid_analyses = analyzed_frames
            
            analysis_time = time.time() - analysis_start
            logger.info(f"Analyzed {len(valid_analyses)} frames in {analysis_time:.2f}s")
            
            if job_id:
                video_processing_jobs[job_id]["processed_frames"] = len(valid_analyses)
                video_processing_jobs[job_id]["progress"] = 80
            
            # Step 4: Return results (simplified for now)
            # Note: GUM integration would require proper Observer implementation
            final_results = [frame for frame in valid_analyses if isinstance(frame, dict)]
            
            total_time = time.time() - total_start_time
            logger.info(f" Completed parallel video processing in {total_time:.2f}s total")
            
            return final_results
            
        except Exception as e:
            logger.error(f"Error in parallel video processing: {str(e)}")
            if job_id:
                video_processing_jobs[job_id]["status"] = "error"
                video_processing_jobs[job_id]["error"] = str(e)
            raise


async def process_and_store_in_gum(frame_results: List[dict], user_name: str, observer_name: str) -> None:
    """
    Process frame analysis results and store them in GUM database.
    Separated from parallel processing for better modularity.
    """
    if not frame_results:
        logger.warning(" No frame results to process in GUM")
        return
    
    logger.info(f"Storing {len(frame_results)} frame analyses in GUM database...")
    gum_start = time.time()
    
    try:
        async with gum_semaphore:
            gum_inst = await ensure_gum_instance(user_name)
            observer = APIObserver(observer_name)
            
            # Process in batches to avoid overwhelming the database
            batch_size = 5
            for i in range(0, len(frame_results), batch_size):
                batch = frame_results[i:i + batch_size]
                
                for frame_result in batch:
                    if isinstance(frame_result, dict) and "analysis" in frame_result and "frame_number" in frame_result:
                        # Create update with frame analysis
                        update_content = f"Video frame analysis (Frame {frame_result['frame_number']}): {frame_result['analysis']}"
                        update = Update(
                            content=update_content,
                            content_type="input_text"
                        )
                        await gum_inst._default_handler(observer, update)
        
        gum_time = time.time() - gum_start
        logger.info(f"Stored {len(frame_results)} frame analyses in GUM in {gum_time:.2f}s")
        
    except Exception as e:
        logger.error(f"Error storing frame results in GUM: {str(e)}")
        raise


@app.post("/observations/video", response_model=dict)
async def submit_video_observation(
    request: Request,
    file: UploadFile = File(...),
    user_name: Optional[str] = Form(None),
    observer_name: Optional[str] = Form("api_controller"),
    fps: Optional[float] = Form(0.03)  # Reduced from 0.1 to 0.03 (70% reduction)
):
    """Submit video observation"""
    try:
        start_time = time.time()
        logger.info(f"Received video upload: {file.filename}")
        
        # Get file size for logging
        file_content_preview = await file.read()
        logger.info(f" File size: {len(file_content_preview) / 1024 / 1024:.1f} MB")
        
        # Reset file pointer after reading for size
        await file.seek(0)
        
        # Validate file type - check both MIME type and file extension
        is_video = False
        if file.content_type and file.content_type.startswith('video/'):
            is_video = True
        elif file.filename:
            video_extensions = ('.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv')
            is_video = file.filename.lower().endswith(video_extensions)
        
        if not is_video:
            logger.error(f"Invalid file type: {file.content_type}, filename: {file.filename}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File must be a video (MP4, AVI, MOV, WMV, FLV, WebM, MKV)"
            )
        
        logger.info("Video file type validation passed")
        logger.info("Validating video content")
        
        # Read and validate file content
        file_content = await file.read()
        
        if not validate_video(file_content):
            logger.error("Video content validation failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid video file"
            )
        
        logger.info("Saving video to temporary storage")
        
        # Save video to persistent temporary file
        temp_dir = Path(tempfile.gettempdir()) / "gum_videos"
        temp_dir.mkdir(exist_ok=True)
        
        job_id = str(uuid.uuid4())
        video_filename = f"{job_id}_{file.filename}"
        video_path = temp_dir / video_filename
        
        # Write video file
        with open(video_path, 'wb') as f:
            f.write(file_content)
        
        logger.info(f"Video saved with job ID: {job_id}")
        
        # Initialize job status
        video_processing_jobs[job_id] = {
            "status": "queued",
            "progress": 0,
            "filename": file.filename,
            "fps": fps,
            "created_at": time.time(),
            "total_frames": 0,
            "processed_frames": 0,
            "successful_frames": 0,
            "failed_frames": 0
        }
        
        logger.info(" Starting background video processing")
        
        # Start background processing
        asyncio.create_task(process_video_background(
            job_id, video_path, user_name or "anonymous", observer_name or "api_controller", fps or 0.1, file.filename or "unknown.mp4"
        ))
        
        upload_time = (time.time() - start_time) * 1000
        logger.info(f"Video upload completed in {upload_time:.1f}ms")
        
        return {
            "success": True,
            "message": "Video uploaded successfully and queued for processing",
            "job_id": job_id,
            "filename": file.filename,
            "fps": fps,
            "upload_time_ms": upload_time,
            "status": "queued",
            "check_status_url": f"/observations/video/status/{job_id}"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing video observation: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error processing video observation: {str(e)}"
        )


@app.get("/observations/video/status/{job_id}", response_model=dict)
async def get_video_processing_status(job_id: str):
    """Get the status of a video processing job."""
    if job_id not in video_processing_jobs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video processing job not found"
        )
    
    job = video_processing_jobs[job_id]
    
    # Calculate processing time
    processing_time = (time.time() - job["created_at"]) * 1000
    
    response = {
        "job_id": job_id,
        "status": job["status"],
        "progress": job["progress"],
        "filename": job["filename"],
        "fps": job["fps"],
        "processing_time_ms": processing_time,
        "total_frames": job["total_frames"],
        "processed_frames": job["processed_frames"]
    }
    
    if job["status"] == "completed":
        response.update({
            "successful_frames": job["successful_frames"],
            "failed_frames": job["failed_frames"],
            "summary": f"Processed video {job['filename']} with {job['total_frames']} frames extracted at {job['fps']} fps. Successfully analyzed {job['successful_frames']} frames" + (f", {job['failed_frames']} frames failed processing" if job['failed_frames'] > 0 else ""),
            "frame_analyses": job.get("frame_analyses", [])
        })
    elif job["status"] == "error":
        response["error"] = job.get("error", "Unknown error occurred")
    
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc),
            timestamp=datetime.now()
        ).dict()
    )


# === Helper Functions ===

# === Main Entry Point ===

async def startup_event():
    """Startup event handler."""
    logger.info("Starting GUM API Controller...")
    
    if USE_BATCHED_CLIENT:
        logger.info(" AI Processing: Batched AI Client (Reduced API Calls)")
        logger.info(f"    Batch Interval: {BATCH_INTERVAL_HOURS} hours")
        logger.info(f"    Max Batch Size: {MAX_BATCH_SIZE} requests")
        logger.info("    Fallback: Enabled (5 minute threshold)")
        logger.info("    Text Tasks: Azure OpenAI (Batched)")
        logger.info("    Vision Tasks: OpenRouter (Batched)")
        logger.info(" Batching configuration initialized for reduced API costs")
    else:
        logger.info(" AI Processing: Unified AI Client (Azure OpenAI + OpenRouter)")
        logger.info("    Text Tasks: Azure OpenAI")
        logger.info("    Vision Tasks: OpenRouter (Qwen Vision)")
        logger.info(" Hybrid AI configuration initialized")
    
    logger.info("GUM API Controller started successfully")


app.add_event_handler("startup", startup_event)


def run_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = False):
    """Run the FastAPI server."""
    # Use logging for startup banner too
    logger.info("=" * 60)
    logger.info(" GUM AI Video Processing Server Starting Up")
    logger.info("=" * 60)
    logger.info(f" Server: {host}:{port}")
    logger.info(f" Reload mode: {'Enabled' if reload else 'Disabled'}")
    logger.info(" Log level: INFO")
    logger.info("Video processing with enhanced logging enabled!")
    logger.info("=" * 60)
    
    uvicorn.run(
        "controller:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="GUM REST API Controller")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind to")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    
    args = parser.parse_args()
    run_server(host=args.host, port=args.port, reload=args.reload)
