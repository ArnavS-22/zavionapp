# Production CORS Configuration for GUM Backend

## Overview

The GUM backend now includes production-ready CORS (Cross-Origin Resource Sharing) configuration with security best practices.

## Features

- **Restricted Origins**: Only allows requests from specified domains
- **Security Headers**: Comprehensive security headers including CSP, XSS protection
- **Rate Limit Headers**: Exposes rate limiting information to frontend
- **Configurable**: All settings configurable via environment variables
- **Preflight Caching**: OPTIONS requests cached for 24 hours by default

## Environment Variables

### Required
```bash
# Comma-separated list of allowed frontend domains
ALLOWED_ORIGINS=https://zavion.app,https://www.zavion.app,https://app.zavion.app

# Comma-separated list of allowed host headers
ALLOWED_HOSTS=zavion.app,*.zavion.app,www.zavion.app,app.zavion.app
```

### Optional
```bash
# CORS preflight cache time in seconds (default: 86400 = 24 hours)
CORS_MAX_AGE=86400

# Enable strict CORS mode (default: true)
STRICT_CORS=true

# Enable GZIP compression (default: true)
ENABLE_COMPRESSION=true
```

## Security Features

### CORS Headers
- `Access-Control-Allow-Origin`: Only specified domains
- `Access-Control-Allow-Methods`: GET, POST, PUT, DELETE, OPTIONS
- `Access-Control-Allow-Headers`: Explicit list of allowed headers
- `Access-Control-Max-Age`: Configurable preflight caching

### Security Headers
- `X-Content-Type-Options`: nosniff
- `X-Frame-Options`: DENY
- `X-XSS-Protection`: 1; mode=block
- `Referrer-Policy`: strict-origin-when-cross-origin
- `Content-Security-Policy`: Restrictive CSP policy

### Rate Limiting Headers
- `X-RateLimit-Limit`: Request limit
- `X-RateLimit-Remaining`: Remaining requests
- `X-RateLimit-Reset`: Reset time

## Usage

### 1. Copy Environment Template
```bash
cp env.template .env
```

### 2. Update Configuration
Edit `.env` with your production domains:
```bash
ALLOWED_ORIGINS=https://yourdomain.com,https://app.yourdomain.com
ALLOWED_HOSTS=yourdomain.com,*.yourdomain.com
```

### 3. Restart Backend
The changes take effect immediately after restart.

## Monitoring

### Check Current Configuration
```bash
GET /admin/cors-config
```

### Health Check
```bash
GET /health
```

## Development vs Production

### Development
- Uses `env.template` defaults
- Allows localhost for testing
- Less restrictive security

### Production
- Must specify exact domains
- Strict security headers
- Rate limiting enabled
- Compression enabled

## Troubleshooting

### Common Issues

1. **CORS Error**: Check `ALLOWED_ORIGINS` includes your frontend domain
2. **Host Header Error**: Verify `ALLOWED_HOSTS` includes your domain
3. **Preflight Fails**: Check `CORS_MAX_AGE` and browser caching

### Debug Mode
Set `STRICT_CORS=false` temporarily to debug CORS issues.

## Security Best Practices

- ✅ Never use `allow_origins=["*"]` in production
- ✅ Explicitly list allowed methods and headers
- ✅ Use HTTPS for all production domains
- ✅ Regular security header audits
- ✅ Monitor rate limiting violations
- ✅ Log CORS violations for security analysis

