# Gumbo Suggestion System - Implementation Fixes

## Fix #1: Bridge SSE Systems

### Problem
Gumbo engine broadcasts to its own SSE connections, but frontend connects to controller SSE endpoint.

### Solution
Create a global SSE manager that both systems can use:

```python
# gum/services/sse_manager.py
import asyncio
import json
import logging
from typing import Set, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class SSEConnection:
    def __init__(self, connection_id: str, queue: asyncio.Queue):
        self.connection_id = connection_id
        self.queue = queue
        self.connected_at = datetime.now(timezone.utc)

class GlobalSSEManager:
    def __init__(self):
        self._connections: Dict[str, SSEConnection] = {}
        self._lock = asyncio.Lock()
    
    async def register_connection(self, connection_id: str, queue: asyncio.Queue):
        async with self._lock:
            self._connections[connection_id] = SSEConnection(connection_id, queue)
            logger.info(f"SSE connection registered: {connection_id}")
    
    async def unregister_connection(self, connection_id: str):
        async with self._lock:
            if connection_id in self._connections:
                del self._connections[connection_id]
                logger.info(f"SSE connection unregistered: {connection_id}")
    
    async def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        async with self._lock:
            if not self._connections:
                logger.debug("No SSE connections to broadcast to")
                return
            
            event_data = {
                "event": event_type,
                "data": json.dumps(data, default=str)
            }
            
            failed_connections = []
            for connection_id, connection in self._connections.items():
                try:
                    await connection.queue.put(event_data)
                    logger.debug(f"Broadcasted {event_type} to {connection_id}")
                except Exception as e:
                    logger.warning(f"Failed to broadcast to {connection_id}: {e}")
                    failed_connections.append(connection_id)
            
            # Clean up failed connections
            for connection_id in failed_connections:
                del self._connections[connection_id]
    
    def get_connection_count(self) -> int:
        return len(self._connections)

# Global instance
_global_sse_manager = None

def get_sse_manager() -> GlobalSSEManager:
    global _global_sse_manager
    if _global_sse_manager is None:
        _global_sse_manager = GlobalSSEManager()
    return _global_sse_manager
```

## Fix #2: Add Database Persistence

### Problem
Suggestions are generated but never saved to database.

### Solution
Add persistence layer to Gumbo engine:

```python
# Add to gum/services/gumbo_engine.py

async def _save_suggestions_to_database(
    self, 
    batch: SuggestionBatch, 
    session: AsyncSession
) -> List[int]:
    """Save suggestion batch to database and return suggestion IDs."""
    try:
        from ..models import Suggestion
        
        suggestion_ids = []
        
        for suggestion_data in batch.suggestions:
            # Create database record
            db_suggestion = Suggestion(
                title=suggestion_data.title,
                description=suggestion_data.description,
                category=suggestion_data.category,
                rationale=suggestion_data.rationale,
                expected_utility=suggestion_data.expected_utility or 0.0,
                probability_useful=suggestion_data.probability_useful or 0.0,
                trigger_proposition_id=batch.trigger_proposition_id,
                batch_id=batch.batch_id,
                delivered=False  # Will be marked True when delivered via SSE
            )
            
            session.add(db_suggestion)
            await session.flush()  # Get the ID
            suggestion_ids.append(db_suggestion.id)
        
        await session.commit()
        
        logger.info(f"Saved {len(suggestion_ids)} suggestions to database")
        return suggestion_ids
        
    except Exception as e:
        logger.error(f"Failed to save suggestions to database: {e}")
        await session.rollback()
        return []

async def _mark_suggestions_delivered(
    self, 
    suggestion_ids: List[int], 
    session: AsyncSession
):
    """Mark suggestions as delivered in database."""
    try:
        from ..models import Suggestion
        from sqlalchemy import update
        
        stmt = (
            update(Suggestion)
            .where(Suggestion.id.in_(suggestion_ids))
            .values(delivered=True)
        )
        
        await session.execute(stmt)
        await session.commit()
        
        logger.info(f"Marked {len(suggestion_ids)} suggestions as delivered")
        
    except Exception as e:
        logger.error(f"Failed to mark suggestions as delivered: {e}")
        await session.rollback()
```

## Fix #3: Update Gumbo Engine Integration

### Problem
Gumbo engine needs to use global SSE manager and save to database.

### Solution
Modify the main trigger function:

```python
# Update in gum/services/gumbo_engine.py

async def trigger_gumbo_suggestions(
    self, 
    proposition_id: int, 
    session: AsyncSession
) -> Optional[SuggestionBatch]:
    """Main Gumbo algorithm with database persistence and proper SSE broadcasting."""
    
    if not self._started:
        await self.start()
    
    start_time = time.time()
    batch_id = str(uuid.uuid4())
    
    try:
        logger.info(f"🎯 Gumbo triggered for proposition {proposition_id}")
        
        # ... existing code for rate limiting, retrieval, generation, scoring ...
        
        # Step 6: Create suggestion batch
        processing_time = time.time() - start_time
        batch = SuggestionBatch(
            suggestions=scored_suggestions,
            trigger_proposition_id=proposition_id,
            generated_at=datetime.now(timezone.utc),
            processing_time_seconds=processing_time,
            context_propositions_used=len(context_result.related_propositions),
            batch_id=batch_id
        )
        
        # Step 7: Save to database
        suggestion_ids = await self._save_suggestions_to_database(batch, session)
        
        # Step 8: Broadcast via global SSE manager
        from .sse_manager import get_sse_manager
        sse_manager = get_sse_manager()
        
        await sse_manager.broadcast_event("suggestion_batch", {
            "suggestions": [s.dict() for s in batch.suggestions],
            "trigger_proposition_id": batch.trigger_proposition_id,
            "generated_at": batch.generated_at.isoformat(),
            "processing_time_seconds": batch.processing_time_seconds,
            "batch_id": batch.batch_id,
            "suggestion_ids": suggestion_ids
        })
        
        # Step 9: Mark as delivered
        if suggestion_ids:
            await self._mark_suggestions_delivered(suggestion_ids, session)
        
        # Update metrics
        self._update_metrics(batch)
        
        logger.info(f"✅ Gumbo completed for proposition {proposition_id} in {processing_time:.2f}s")
        return batch
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"❌ Gumbo failed for proposition {proposition_id} after {processing_time:.2f}s: {e}")
        
        # Broadcast error via SSE
        from .sse_manager import get_sse_manager
        sse_manager = get_sse_manager()
        
        await sse_manager.broadcast_event("error", {
            "error_type": "suggestion_generation_failed",
            "message": f"Failed to generate suggestions: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "proposition_id": proposition_id
        })
        
        return None
```

## Fix #4: Update Controller SSE Endpoint

### Problem
Controller SSE endpoint needs to use global SSE manager.

### Solution
Replace controller SSE implementation:

```python
# Update in controller.py

@app.get("/suggestions/stream")
async def stream_suggestions_endpoint(
    request: Request,
    user_name: Optional[str] = None,
    include_heartbeat: bool = True,
    heartbeat_interval: int = 30
):
    """Stream real-time suggestions via Server-Sent Events using global SSE manager."""
    
    if not GUMBO_AVAILABLE or not EventSourceResponse:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Gumbo suggestion streaming not available - missing dependencies"
        )
    
    async def event_generator() -> AsyncIterator[dict]:
        connection_id = str(uuid.uuid4())
        event_queue = asyncio.Queue()
        
        logger.info(f"SSE connection established: {connection_id}")
        
        try:
            # Register with global SSE manager
            from gum.services.sse_manager import get_sse_manager
            sse_manager = get_sse_manager()
            await sse_manager.register_connection(connection_id, event_queue)
            
            # Send initial connection event
            yield {
                "event": "connected",
                "data": json.dumps({
                    "status": "connected",
                    "connection_id": connection_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "message": "Real-time suggestion stream active"
                })
            }
            
            # Handle events
            last_heartbeat = time.time()
            
            while True:
                try:
                    # Check if client disconnected
                    if await request.is_disconnected():
                        logger.info(f"SSE client disconnected: {connection_id}")
                        break
                    
                    # Wait for events with timeout for heartbeat
                    try:
                        event = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                        yield event
                    except asyncio.TimeoutError:
                        # Send heartbeat if needed
                        if include_heartbeat and (time.time() - last_heartbeat) >= heartbeat_interval:
                            yield {
                                "event": "heartbeat",
                                "data": json.dumps({
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "connections_active": sse_manager.get_connection_count()
                                })
                            }
                            last_heartbeat = time.time()
                    
                except asyncio.CancelledError:
                    logger.info(f"SSE connection cancelled: {connection_id}")
                    break
                except Exception as e:
                    logger.error(f"Error in SSE event generator: {e}")
                    yield {
                        "event": "error",
                        "data": json.dumps({
                            "error_type": "stream_error",
                            "message": f"Stream error: {str(e)}",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                    }
                    
        except Exception as e:
            logger.error(f"Fatal SSE error for {connection_id}: {e}")
            yield {
                "event": "error",
                "data": json.dumps({
                    "error_type": "fatal_error",
                    "message": f"Connection error: {str(e)}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            }
        finally:
            # Cleanup connection
            await sse_manager.unregister_connection(connection_id)
            logger.info(f"SSE connection cleaned up: {connection_id}")
    
    return EventSourceResponse(event_generator())
```

## Fix #5: Add Historical Suggestions Endpoint

### Problem
No way to retrieve past suggestions if SSE fails or for historical review.

### Solution
Add REST endpoint for suggestion history:

```python
# Add to controller.py

@app.get("/suggestions/history", response_model=List[dict])
async def get_suggestion_history(
    user_name: Optional[str] = None,
    limit: Optional[int] = 50,
    offset: Optional[int] = 0,
    delivered_only: Optional[bool] = None
):
    """Get historical suggestions from database."""
    
    try:
        gum_inst = await ensure_gum_instance(user_name)
        
        async with gum_inst._session() as session:
            from gum.models import Suggestion
            from sqlalchemy import select, desc
            
            stmt = select(Suggestion).order_by(desc(Suggestion.created_at))
            
            if delivered_only is not None:
                stmt = stmt.where(Suggestion.delivered == delivered_only)
            
            stmt = stmt.limit(limit).offset(offset)
            
            result = await session.execute(stmt)
            suggestions = result.scalars().all()
            
            return [
                {
                    "id": s.id,
                    "title": s.title,
                    "description": s.description,
                    "category": s.category,
                    "rationale": s.rationale,
                    "expected_utility": s.expected_utility,
                    "probability_useful": s.probability_useful,
                    "trigger_proposition_id": s.trigger_proposition_id,
                    "batch_id": s.batch_id,
                    "delivered": s.delivered,
                    "created_at": serialize_datetime(parse_datetime(s.created_at))
                }
                for s in suggestions
            ]
            
    except Exception as e:
        logger.error(f"Error getting suggestion history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error getting suggestion history: {str(e)}"
        )
```

## Implementation Order

1. **Create SSE Manager** - Add `gum/services/sse_manager.py`
2. **Update Gumbo Engine** - Add database persistence and SSE integration
3. **Update Controller** - Replace SSE endpoint with global manager integration
4. **Add History Endpoint** - For fallback and historical review
5. **Test Integration** - Verify suggestions flow from generation to frontend

## Testing Strategy

1. **Unit Tests**: Test each component in isolation
2. **Integration Tests**: Test full flow from proposition to frontend
3. **SSE Tests**: Test connection handling and event broadcasting
4. **Database Tests**: Verify persistence and delivery tracking
5. **Frontend Tests**: Verify UI updates and error handling

This comprehensive fix addresses all the critical issues while maintaining the existing functionality and adding proper error handling and fallback mechanisms.
