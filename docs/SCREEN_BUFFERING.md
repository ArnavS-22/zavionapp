# Screen Observer Buffering System

## Overview

The Screen Observer now includes a 10-minute buffering system that batches screen capture events before processing them with AI. This significantly reduces API costs by processing multiple events in a single AI call instead of making individual calls for each interaction.

## Features

### Buffer Management
- **10-minute buffer duration** (configurable)
- **Event batching** by monitor for better context
- **Automatic processing** when buffer timer expires
- **Thread-safe** buffer operations
- **Graceful shutdown** with remaining event processing

### Preserved Functionality
- **Cross-platform compatibility** (macOS Quartz, Windows/Linux mss)
- **Mouse/keyboard event correlation** maintained
- **Debounce logic** unchanged
- **Frame deduplication** preserved
- **Skip guard** functionality intact
- **Same observer interface** - no breaking changes

## Configuration

### Buffer Duration
```python
# Default: 10 minutes
screen = Screen(buffer_minutes=10)

# Custom duration: 5 minutes
screen = Screen(buffer_minutes=5)

# Short duration for testing: 1 minute
screen = Screen(buffer_minutes=1)
```

### Debug Mode
```python
# Enable debug logging for buffer operations
screen = Screen(debug=True)
```

## How It Works

### 1. Event Capture
- Mouse events (move, click, scroll) are captured as before
- Screenshots are saved to disk immediately
- Events are added to buffer instead of immediate AI processing

### 2. Buffer Accumulation
- Events accumulate in memory buffer
- Timer starts when first event is added
- Buffer groups events by monitor for better context

### 3. Batch Processing
- After buffer duration expires, all events are processed together
- AI receives multiple images in a single API call
- Comprehensive prompt includes all event types and monitor information

### 4. Result Emission
- Single combined result is emitted to GUM
- Historical context is maintained
- Error handling with fallback to individual processing

## API Changes

### New Parameters
- `buffer_minutes: int = 10` - Buffer duration in minutes

### New Methods
- `get_buffer_status() -> dict` - Get current buffer information
- `_add_to_buffer()` - Internal buffer management
- `_process_buffer()` - Batch processing logic
- `_process_monitor_events()` - Monitor-specific processing

### Modified Methods
- `_process_and_emit()` - Now adds to buffer instead of immediate processing
- `__init__()` - Added buffer configuration parameters

## Buffer Status Monitoring

```python
# Get current buffer status
status = screen.get_buffer_status()
print(f"Buffer size: {status['buffer_size']}")
print(f"Time remaining: {status['time_remaining_seconds']} seconds")
print(f"Active: {status['is_active']}")
```

## Cost Reduction Benefits

### Before Buffering
- Each mouse event → 2 AI API calls (transcription + summary)
- 10 events = 20 API calls
- High cost per interaction

### After Buffering
- 10 events → 2 AI API calls (batch transcription + batch summary)
- 90% reduction in API calls
- Significant cost savings

## Error Handling

### Fallback Processing
- If batch processing fails, events are processed individually
- Original `_process_and_emit()` logic preserved as fallback
- No data loss during errors

### Buffer Cleanup
- Timer cancellation on shutdown
- Remaining events processed before exit
- Memory cleanup and resource management

## Testing

Run the test script to verify functionality:

```bash
python test_screen_buffer.py
```

The test script:
- Creates a screen observer with short buffer duration
- Simulates multiple events
- Verifies buffer accumulation and processing
- Tests fallback functionality

## Performance Considerations

### Memory Usage
- Buffer stores event metadata and file paths
- Images remain on disk until processing
- Automatic cleanup after processing

### Processing Time
- Batch processing may take longer than individual calls
- Trade-off: fewer API calls vs. longer processing time
- Overall system responsiveness maintained

## Migration Guide

### Existing Code
```python
# Old code - still works
screen = Screen()
await screen.start()
# Events are now buffered automatically
```

### New Code with Custom Buffer
```python
# New code with custom buffer duration
screen = Screen(buffer_minutes=5, debug=True)
await screen.start()
# Monitor buffer status
status = screen.get_buffer_status()
```

## Troubleshooting

### Buffer Not Processing
- Check if `_buffer_timer` is active
- Verify `_buffer_start_time` is set
- Ensure observer is running

### Memory Issues
- Monitor buffer size with `get_buffer_status()`
- Consider reducing `buffer_minutes` if needed
- Check for proper cleanup on shutdown

### API Errors
- Fallback processing handles individual errors
- Check AI provider configuration
- Verify image file accessibility

## Future Enhancements

### Planned Features
- Configurable batch sizes
- Priority processing for certain events
- Buffer persistence across restarts
- Real-time buffer monitoring API

### Optimization Opportunities
- Dynamic buffer duration based on activity
- Smart event grouping algorithms
- Compression for large image batches 