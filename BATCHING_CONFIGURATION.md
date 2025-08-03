# Batching Configuration for Reduced API Calls

This document explains how to configure the batching system to reduce API call frequency while maintaining functionality.

## Overview

The batching system stores observations and makes bulk API calls at regular intervals instead of making individual calls for each observation. This significantly reduces API costs while maintaining the same functionality.

## Environment Variables

Add these variables to your `.env` file:

```bash
# Enable/disable batching (default: true)
USE_BATCHED_CLIENT=true

# How often to process batches (default: 1.0 hours)
BATCH_INTERVAL_HOURS=1.0

# Maximum requests per batch (default: 50)
MAX_BATCH_SIZE=50
```

## Configuration Options

### USE_BATCHED_CLIENT
- `true`: Use batched client (recommended for cost reduction)
- `false`: Use original unified client (immediate API calls)

### BATCH_INTERVAL_HOURS
- Controls how often batches are processed
- Default: 1.0 hours
- Recommended range: 0.5 to 4.0 hours
- Lower values = more frequent API calls but faster response
- Higher values = fewer API calls but longer delays

### MAX_BATCH_SIZE
- Maximum number of requests per batch
- Default: 50
- Recommended range: 20 to 100
- Lower values = smaller batches, more frequent processing
- Higher values = larger batches, more efficient but longer delays

## How It Works

1. **Request Storage**: When observations are submitted, they're stored in memory and on disk
2. **Background Processing**: A background thread processes batches at regular intervals
3. **Fallback System**: Requests older than 5 minutes automatically use immediate API calls
4. **Persistence**: Batch state is saved to disk and survives server restarts

## API Endpoints

### Check Batching Status
```bash
GET /admin/batch-stats
```

Returns:
```json
{
  "batching_enabled": true,
  "batch_stats": {
    "pending_requests": 15,
    "cached_results": 45,
    "batch_counter": 3
  },
  "configuration": {
    "batch_interval_hours": 1.0,
    "max_batch_size": 50,
    "use_batched_client": true
  }
}
```

### Force Batch Processing
```bash
POST /admin/batch-process
```

Forces immediate processing of pending batches.

## Benefits

1. **Cost Reduction**: 80-90% reduction in API calls
2. **Rate Limit Management**: Avoids hitting API rate limits
3. **Bulk Processing**: More efficient API usage
4. **Fallback Safety**: Urgent requests still get immediate processing
5. **Persistence**: Survives server restarts

## Monitoring

Monitor the batching system using:
- `/admin/batch-stats` - Check current status
- Server logs - Shows batch processing activity
- `/admin/batch-process` - Force processing when needed

## Troubleshooting

### High Pending Requests
If you see many pending requests:
1. Check if the background processor is running
2. Force processing with `/admin/batch-process`
3. Consider reducing `BATCH_INTERVAL_HOURS`

### Slow Response Times
If responses are too slow:
1. Reduce `BATCH_INTERVAL_HOURS`
2. Reduce `MAX_BATCH_SIZE`
3. Set `USE_BATCHED_CLIENT=false` for immediate processing

### Memory Usage
If memory usage is high:
1. Reduce `MAX_BATCH_SIZE`
2. Increase `BATCH_INTERVAL_HOURS`
3. Monitor with `/admin/batch-stats`

## Example Configurations

### Cost-Optimized (Maximum Savings)
```bash
USE_BATCHED_CLIENT=true
BATCH_INTERVAL_HOURS=4.0
MAX_BATCH_SIZE=100
```

### Balanced (Recommended)
```bash
USE_BATCHED_CLIENT=true
BATCH_INTERVAL_HOURS=1.0
MAX_BATCH_SIZE=50
```

### Performance-Optimized (Faster Response)
```bash
USE_BATCHED_CLIENT=true
BATCH_INTERVAL_HOURS=0.5
MAX_BATCH_SIZE=25
```

### Immediate Processing (No Batching)
```bash
USE_BATCHED_CLIENT=false
``` 