# GUM Monitoring API Usage Guide

This document provides comprehensive usage examples and integration guidance for the GUM monitoring control endpoints.

## Overview

The monitoring API allows external applications (like a hosted frontend) to control the local GUM monitoring process that runs via `python -m gum.cli`. These endpoints provide a clean interface for starting, stopping, and monitoring the status of the GUM monitoring agent.

## Endpoints

### 1. Start Monitoring

**Endpoint:** `POST /monitoring/start`

**Description:** Starts the GUM monitoring process for a specific user.

**Request Body:**
```json
{
  "user_name": "John Doe",
  "model": "gpt-4o-mini",
  "debug": false
}
```

**Parameters:**
- `user_name` (required): The name of the user to monitor
- `model` (optional): AI model to use (default: "gpt-4o-mini")
- `debug` (optional): Enable debug logging (default: false)

**Response:**
```json
{
  "success": true,
  "process_id": 12345,
  "message": "Monitoring started successfully for user: John Doe",
  "user_name": "John Doe"
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8001/monitoring/start" \
     -H "Content-Type: application/json" \
     -d '{"user_name": "John Doe", "model": "gpt-4o-mini"}'
```

**JavaScript Example:**
```javascript
const response = await fetch('http://localhost:8001/monitoring/start', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
  },
  body: JSON.stringify({
    user_name: 'John Doe',
    model: 'gpt-4o-mini',
    debug: false
  })
});

const result = await response.json();
console.log('Monitoring started:', result);
```

### 2. Stop Monitoring

**Endpoint:** `POST /monitoring/stop`

**Description:** Stops the currently running GUM monitoring process.

**Request Body:** None required

**Response:**
```json
{
  "success": true,
  "message": "Monitoring stopped successfully",
  "process_id": 12345
}
```

**cURL Example:**
```bash
curl -X POST "http://localhost:8001/monitoring/stop"
```

**JavaScript Example:**
```javascript
const response = await fetch('http://localhost:8001/monitoring/stop', {
  method: 'POST'
});

const result = await response.json();
console.log('Monitoring stopped:', result);
```

### 3. Get Monitoring Status

**Endpoint:** `GET /monitoring/status`

**Description:** Returns the current status of the GUM monitoring process.

**Request Body:** None required

**Response:**
```json
{
  "is_running": true,
  "process_id": 12345,
  "user_name": "John Doe",
  "model": "gpt-4o-mini",
  "start_time": "2024-01-15T10:30:00Z",
  "uptime_seconds": 3600,
  "status_message": "Monitoring active for user: John Doe"
}
```

**cURL Example:**
```bash
curl "http://localhost:8001/monitoring/status"
```

**JavaScript Example:**
```javascript
const response = await fetch('http://localhost:8001/monitoring/status');
const status = await response.json();
console.log('Monitoring status:', status);
```

## Integration Patterns

### 1. Frontend Integration

Here's how you might integrate these endpoints into a React/Vue/Angular frontend:

```javascript
class MonitoringService {
  constructor(baseUrl = 'http://localhost:8001') {
    this.baseUrl = baseUrl;
  }

  async startMonitoring(userName, model = 'gpt-4o-mini', debug = false) {
    const response = await fetch(`${this.baseUrl}/monitoring/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_name: userName, model, debug })
    });
    
    if (!response.ok) {
      throw new Error(`Failed to start monitoring: ${response.statusText}`);
    }
    
    return response.json();
  }

  async stopMonitoring() {
    const response = await fetch(`${this.baseUrl}/monitoring/stop`, {
      method: 'POST'
    });
    
    if (!response.ok) {
      throw new Error(`Failed to stop monitoring: ${response.statusText}`);
    }
    
    return response.json();
  }

  async getStatus() {
    const response = await fetch(`${this.baseUrl}/monitoring/status`);
    
    if (!response.ok) {
      throw new Error(`Failed to get status: ${response.statusText}`);
    }
    
    return response.json();
  }

  // Polling method for real-time status updates
  startStatusPolling(callback, intervalMs = 5000) {
    const poll = async () => {
      try {
        const status = await this.getStatus();
        callback(status);
      } catch (error) {
        console.error('Status polling error:', error);
      }
    };

    // Initial call
    poll();
    
    // Set up interval
    const intervalId = setInterval(poll, intervalMs);
    
    // Return function to stop polling
    return () => clearInterval(intervalId);
  }
}
```

### 2. Python Client Integration

```python
import requests
import time
from typing import Optional, Dict, Any

class GUMMonitoringClient:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def start_monitoring(self, user_name: str, model: str = "gpt-4o-mini", 
                        debug: bool = False) -> Dict[str, Any]:
        """Start GUM monitoring for a user."""
        response = self.session.post(
            f"{self.base_url}/monitoring/start",
            json={
                "user_name": user_name,
                "model": model,
                "debug": debug
            }
        )
        response.raise_for_status()
        return response.json()
    
    def stop_monitoring(self) -> Dict[str, Any]:
        """Stop the currently running monitoring process."""
        response = self.session.post(f"{self.base_url}/monitoring/stop")
        response.raise_for_status()
        return response.json()
    
    def get_status(self) -> Dict[str, Any]:
        """Get the current monitoring status."""
        response = self.session.get(f"{self.base_url}/monitoring/status")
        response.raise_for_status()
        return response.json()
    
    def wait_for_status(self, target_status: bool, timeout_seconds: int = 60) -> bool:
        """Wait for monitoring to reach a specific status."""
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            try:
                status = self.get_status()
                if status["is_running"] == target_status:
                    return True
                time.sleep(1)
            except Exception as e:
                print(f"Error checking status: {e}")
                time.sleep(1)
        return False

# Usage example
if __name__ == "__main__":
    client = GUMMonitoringClient()
    
    try:
        # Start monitoring
        result = client.start_monitoring("John Doe")
        print(f"Started monitoring: {result}")
        
        # Wait for it to be running
        if client.wait_for_status(True, timeout_seconds=30):
            print("Monitoring is now running")
            
            # Get status
            status = client.get_status()
            print(f"Current status: {status}")
            
            # Stop monitoring
            stop_result = client.stop_monitoring()
            print(f"Stopped monitoring: {stop_result}")
        else:
            print("Failed to start monitoring within timeout")
            
    except Exception as e:
        print(f"Error: {e}")
```

### 3. Shell Script Integration

```bash
#!/bin/bash

# GUM Monitoring Control Script
BASE_URL="http://localhost:8001"

start_monitoring() {
    local user_name="$1"
    local model="${2:-gpt-4o-mini}"
    
    echo "Starting monitoring for user: $user_name"
    curl -s -X POST "$BASE_URL/monitoring/start" \
         -H "Content-Type: application/json" \
         -d "{\"user_name\": \"$user_name\", \"model\": \"$model\"}" | jq .
}

stop_monitoring() {
    echo "Stopping monitoring..."
    curl -s -X POST "$BASE_URL/monitoring/stop" | jq .
}

get_status() {
    echo "Getting monitoring status..."
    curl -s "$BASE_URL/monitoring/status" | jq .
}

# Main script logic
case "$1" in
    "start")
        if [ -z "$2" ]; then
            echo "Usage: $0 start <user_name> [model]"
            exit 1
        fi
        start_monitoring "$2" "$3"
        ;;
    "stop")
        stop_monitoring
        ;;
    "status")
        get_status
        ;;
    *)
        echo "Usage: $0 {start <user_name> [model]|stop|status}"
        exit 1
        ;;
esac
```

## Error Handling

### Common HTTP Status Codes

- **200 OK**: Request successful
- **400 Bad Request**: Invalid request parameters
- **404 Not Found**: No monitoring process running or manager not initialized
- **409 Conflict**: Monitoring already running for another user
- **500 Internal Server Error**: Server-side error during monitoring operations

### Error Response Format

```json
{
  "detail": "Error message describing what went wrong"
}
```

### Handling Errors in JavaScript

```javascript
async function handleMonitoringOperation(operation) {
  try {
    const result = await operation();
    console.log('Success:', result);
    return result;
  } catch (error) {
    if (error.response) {
      // HTTP error response
      const errorData = await error.response.json();
      console.error('API Error:', errorData.detail);
      
      switch (error.response.status) {
        case 409:
          console.error('Monitoring already running');
          break;
        case 404:
          console.error('No monitoring process found');
          break;
        default:
          console.error('Unexpected error:', errorData.detail);
      }
    } else {
      // Network or other error
      console.error('Network error:', error.message);
    }
    throw error;
  }
}

// Usage
await handleMonitoringOperation(() => 
  monitoringService.startMonitoring('John Doe')
);
```

## Security Considerations

1. **Local Access Only**: These endpoints are designed for local access only. The monitoring process runs on the same machine as the backend.

2. **No Authentication**: Currently, no authentication is required. For production use, consider implementing:
   - API key authentication
   - JWT tokens
   - OAuth2 integration

3. **CORS Configuration**: Ensure your CORS settings only allow requests from trusted domains.

4. **Rate Limiting**: The existing rate limiting middleware applies to these endpoints.

## Monitoring and Logging

The monitoring endpoints include comprehensive logging:

- **Start operations**: Logged with user name and model
- **Stop operations**: Logged with process ID
- **Errors**: Detailed error logging for debugging
- **Status checks**: Basic logging for monitoring operations

## Troubleshooting

### Common Issues

1. **"No monitoring manager initialized"**
   - The backend hasn't been properly initialized
   - Restart the backend service

2. **"Monitoring already running"**
   - Another monitoring process is active
   - Use the status endpoint to check current state
   - Stop existing monitoring before starting new

3. **"Failed to start monitoring"**
   - Check if `python -m gum.cli` is available in PATH
   - Verify Python environment and dependencies
   - Check backend logs for detailed error messages

4. **Process not responding**
   - Use `ps aux | grep gum.cli` to check if process exists
   - Check system resources (CPU, memory)
   - Restart monitoring if necessary

### Debug Mode

Enable debug mode when starting monitoring to get more detailed logging:

```json
{
  "user_name": "John Doe",
  "model": "gpt-4o-mini",
  "debug": true
}
```

## Performance Considerations

1. **Status Polling**: Don't poll status more frequently than every 1-2 seconds
2. **Concurrent Requests**: The API handles concurrent requests safely using locks
3. **Process Management**: Process startup/shutdown operations are optimized for responsiveness

## Future Enhancements

Potential improvements for future versions:

1. **WebSocket Support**: Real-time status updates instead of polling
2. **Multiple User Support**: Monitor multiple users simultaneously
3. **Process Recovery**: Automatic restart of failed monitoring processes
4. **Metrics Collection**: Detailed performance and usage metrics
5. **Remote Control**: Secure remote access to monitoring endpoints
