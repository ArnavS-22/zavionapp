# GUM API Rate Limiting Implementation

## Overview

The GUM application now includes a comprehensive, production-ready rate limiting system that protects API endpoints from abuse while providing excellent user experience through intelligent frontend handling.

## Features

### Backend Rate Limiting
- **Per-endpoint limits**: Configurable limits for different API endpoints
- **Memory-efficient**: Automatic cleanup of old requests with configurable memory limits
- **Thread-safe**: Concurrent request handling without race conditions
- **Production-ready**: Background cleanup worker and comprehensive logging
- **Monitoring**: Built-in statistics and admin endpoints for monitoring

### Frontend Rate Limiting
- **Graceful handling**: User-friendly 429 response handling
- **Countdown timers**: Real-time countdown on disabled buttons
- **Visual feedback**: Progress indicators and status displays
- **Auto-recovery**: Automatic re-enabling when limits reset
- **Comprehensive coverage**: Handles all rate-limited endpoints

## Configuration

### Default Rate Limits

| Endpoint | Limit | Window | Description |
|----------|-------|--------|-------------|
| `/observations/video` | 5 requests | 5 minutes | Video uploads (resource-intensive) |
| `/observations/text` | 20 requests | 1 minute | Text submissions |
| `/query` | 30 requests | 1 minute | Search queries |
| `default` | 100 requests | 1 minute | All other endpoints |

### Customizing Rate Limits

You can configure custom rate limits by modifying the `RATE_LIMITS` dictionary in `controller.py`:

```python
RATE_LIMITS = {
    "/observations/video": (5, 300),    # 5 videos per 5 minutes
    "/observations/text": (20, 60),     # 20 text submissions per minute
    "/query": (30, 60),                 # 30 queries per minute
    "default": (100, 60)                # 100 requests per minute for other endpoints
}
```

### Advanced Configuration

For more advanced configuration, you can use the rate limiter's configuration methods:

```python
from rate_limiter import rate_limiter

# Configure a custom endpoint with advanced options
rate_limiter.configure_endpoint(
    endpoint="/custom/endpoint",
    max_requests=50,
    window_seconds=120,
    cleanup_interval=300,      # Cleanup every 5 minutes
    max_memory_entries=5000    # Keep max 5000 entries in memory
)
```

## Implementation Details

### Backend Architecture

#### Rate Limiter Class (`rate_limiter.py`)
- **Thread-safe**: Uses `threading.RLock()` for concurrent access
- **Memory management**: Automatic cleanup of old requests
- **Background worker**: Dedicated thread for cleanup operations
- **Statistics tracking**: Comprehensive metrics for monitoring

#### Middleware (`controller.py`)
- **Universal coverage**: Applies to all endpoints automatically
- **Header injection**: Adds rate limit headers to all responses
- **Logging**: Detailed logging of rate limit violations
- **Exclusions**: Skips health checks and static files

### Frontend Architecture

#### Rate Limit Handler (`app.js`)
- **Endpoint tracking**: Monitors rate limits for all endpoints
- **Countdown timers**: Real-time countdown with automatic cleanup
- **Visual indicators**: Progress bars and status displays
- **Auto-recovery**: Automatic re-enabling when limits reset

#### UI Components (`styles.css`)
- **Rate-limited buttons**: Distinct styling for disabled state
- **Progress indicators**: Visual feedback for remaining requests
- **Animations**: Smooth transitions and countdown effects
- **Dark mode support**: Consistent theming across modes

## API Endpoints

### Rate Limit Headers

All API responses include rate limit headers:

```
X-RateLimit-Limit: 20
X-RateLimit-Remaining: 15
X-RateLimit-Reset: 1640995200
```

### Admin Endpoints

#### Get Rate Limit Statistics
```http
GET /admin/rate-limits
```

Response:
```json
{
  "global_stats": {
    "total_requests": 1250,
    "rate_limited_requests": 23,
    "cleanup_runs": 45,
    "last_cleanup": 1640995200.0,
    "total_endpoints": 4,
    "total_entries": 156,
    "rate_limit_percentage": 1.84
  },
  "endpoint_stats": {
    "/observations/video": {
      "endpoint": "/observations/video",
      "current_requests": 3,
      "max_requests": 5,
      "window_seconds": 300,
      "remaining_requests": 2,
      "reset_time": 1640995500.0,
      "is_limited": false
    }
  },
  "timestamp": "2022-01-01T12:00:00"
}
```

#### Reset Rate Limits
```http
POST /admin/rate-limits/reset?endpoint=/observations/video
```

Response:
```json
{
  "message": "Rate limits reset for /observations/video",
  "endpoint": "/observations/video"
}
```

## Monitoring and Logging

### Log Messages

The system logs various events for monitoring:

```
INFO: Configured rate limit for /observations/video: 5 requests per 300s
WARNING: Rate limit exceeded for /observations/video: 5/5 requests in 300s window. Reset in 245s. Client IP: 192.168.1.100
INFO: High usage for /query: 4 requests remaining out of 30
INFO: Cleanup completed: 23 requests, 2 endpoints removed
```

### Metrics

Key metrics tracked:
- Total requests processed
- Rate-limited requests count
- Cleanup operations performed
- Memory usage (total entries)
- Rate limit violation percentage

## Frontend Usage

### Rate Limit Status

Check if an endpoint is rate limited:

```javascript
if (gumApp.isRateLimited('/observations/video')) {
    console.log('Video upload is rate limited');
}
```

### Get Rate Limit Information

```javascript
const status = gumApp.getRateLimitStatus('/observations/video');
if (status) {
    console.log(`Reset in ${Math.ceil((status.resetTime - Date.now()) / 1000)}s`);
}
```

## Error Handling

### 429 Response Format

When rate limits are exceeded, the API returns:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 245
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1640995500

{
  "detail": "Rate limit exceeded. Try again in 245 seconds."
}
```

### Frontend Error Handling

The frontend automatically:
1. Detects 429 responses
2. Extracts rate limit information
3. Shows user-friendly toast notifications
4. Disables affected buttons with countdown
5. Automatically re-enables when limits reset

## Performance Considerations

### Memory Management
- Automatic cleanup of old requests every minute
- Configurable maximum memory entries per endpoint
- Removal of empty endpoints to free memory

### Thread Safety
- All operations are thread-safe using `RLock`
- No race conditions in concurrent environments
- Efficient locking strategy for high-traffic scenarios

### Scalability
- Memory usage scales with request volume
- Cleanup operations prevent memory leaks
- Configurable limits for different deployment scenarios

## Best Practices

### Configuration
1. Set appropriate limits based on endpoint resource usage
2. Monitor rate limit statistics regularly
3. Adjust limits based on actual usage patterns
4. Use different limits for different user tiers if needed

### Monitoring
1. Set up alerts for high rate limit violation percentages
2. Monitor memory usage and cleanup operations
3. Track endpoint-specific usage patterns
4. Review logs for unusual activity

### User Experience
1. Provide clear feedback when limits are exceeded
2. Show countdown timers for better user understanding
3. Use appropriate visual indicators for different states
4. Ensure graceful degradation when limits are hit

## Troubleshooting

### Common Issues

#### High Memory Usage
- Check cleanup frequency and memory limits
- Monitor total entries across all endpoints
- Consider reducing memory limits for high-traffic endpoints

#### Frequent Rate Limiting
- Review rate limit configurations
- Check for client-side issues causing rapid requests
- Consider implementing client-side throttling

#### Missing Rate Limit Headers
- Ensure middleware is properly configured
- Check that endpoints are not excluded from rate limiting
- Verify response header injection is working

### Debug Mode

Enable debug logging by setting the log level to DEBUG:

```python
import logging
logging.getLogger('rate_limiter').setLevel(logging.DEBUG)
```

This will provide detailed information about:
- Request processing
- Memory cleanup operations
- Configuration changes
- Thread safety operations

## Future Enhancements

### Planned Features
- **User-based rate limiting**: Different limits for different user types
- **IP-based rate limiting**: Additional protection against abuse
- **Rate limit analytics**: Advanced reporting and visualization
- **Dynamic rate limiting**: Adaptive limits based on system load
- **Rate limit bypass**: Admin override for legitimate use cases

### Integration Opportunities
- **Redis backend**: Distributed rate limiting for multi-server deployments
- **Prometheus metrics**: Integration with monitoring systems
- **Webhook notifications**: Alerts for rate limit violations
- **Rate limit API**: External API for managing rate limits

## Conclusion

The GUM rate limiting system provides comprehensive protection against API abuse while maintaining excellent user experience. The combination of robust backend implementation and intelligent frontend handling ensures that users understand and can work within the established limits.

For questions or issues with the rate limiting system, please refer to the monitoring endpoints and logs for detailed information about system behavior.