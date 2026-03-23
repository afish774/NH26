# NexDesk Manual Configuration Guide

Complete guide for configuring and deploying NexDesk AI Helpdesk.

## Table of Contents

- [Environment Configuration](#environment-configuration)
- [Feature Flags](#feature-flags)
- [AI Configuration](#ai-configuration)
- [Database Configuration](#database-configuration)
- [Redis Configuration](#redis-configuration)
- [Advanced RAG Configuration](#advanced-rag-configuration)
- [Voice Configuration](#voice-configuration)
- [Performance Tuning](#performance-tuning)
- [Production Deployment](#production-deployment)
- [Monitoring & Diagnostics](#monitoring--diagnostics)

---

## Environment Configuration

### Configuration File Setup

```bash
# Copy the example configuration
cp .env.example .env

# Edit with your preferred editor
nano .env
```

### Environment Variables Overview

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Yes | - | Primary LLM provider |
| `GEMINI_API_KEY` | No | - | Fallback LLM provider |
| `SECRET_KEY` | Yes* | auto | JWT secret (generate for prod) |
| `DATABASE_URL` | Yes | - | PostgreSQL connection string |
| `REDIS_URL` | No | - | Redis connection URL |
| `USE_AWS` | No | false | Enable AWS services |
| `USE_ADVANCED_RAG` | No | true | Enable LangGraph + HyDE |
| `LOG_LEVEL` | No | INFO | Logging verbosity |
| `CHROMA_PERSIST_DIR` | No | chroma_data | ChromaDB persistence path |
| `CHROMA_PERSISTENT` | No | true | Persist vector DB to disk |
| `SMTP_HOST` | No | - | SMTP server for email integration |
| `SLACK_SIGNING_SECRET` | No | - | Slack request verification |

*Required for production

---

## Feature Flags

### AI Features

```bash
# Enable/disable advanced RAG pipeline
USE_ADVANCED_RAG=true

# HyDE (Hypothetical Document Embeddings) for query expansion
HYDE_ENABLED=true

# Cross-encoder reranking for better accuracy
CROSS_ENCODER_ENABLED=true

# Use advanced retrieval in ticket classifier
USE_ADVANCED_RETRIEVAL=true
```

### AWS Features

```bash
# Enable AWS services (Bedrock, Transcribe, Textract)
USE_AWS=false

# When USE_AWS=true, these are used:
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
```

### System Features

```bash
# Performance monitoring middleware
ENABLE_PERFORMANCE_MONITORING=true

# Strict startup validation (exit on config errors)
STRICT_STARTUP=false

# Logging level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO
```

---

## AI Configuration

### Deflection Threshold

Controls when AI answers from knowledge base vs. creates ticket.

```bash
# Range: 0.0 to 1.0
# Higher = stricter matching, more tickets created
# Lower = more deflections, may include less accurate answers
DEFLECT_THRESHOLD=0.72
```

**Recommended Values:**
- `0.65` - Aggressive deflection (reduce ticket volume)
- `0.72` - Balanced (default)
- `0.80` - Conservative (higher accuracy)

### Hybrid Search Weighting

Balance between vector similarity and keyword matching.

```bash
# Range: 0.0 to 1.0
# 0.0 = BM25 only (keyword matching)
# 1.0 = Vector only (semantic similarity)
HYBRID_ALPHA=0.7
```

**Recommended Values:**
- `0.5` - Balanced vector/keyword
- `0.7` - Favor semantic understanding (default)
- `0.9` - Strong semantic focus

### LLM Model Selection

```bash
# Groq (default) - Fast, free tier available
GROQ_API_KEY=gsk_...

# Model used internally (not configurable via env)
# llama-3.3-70b-versatile

# Gemini (fallback)
GEMINI_API_KEY=...
# Model: gemini-1.5-flash

# AWS Bedrock (when USE_AWS=true)
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20241022-v2:0
```

---

## Database Configuration

### PostgreSQL (Required)

```bash
# Docker Compose (recommended)
POSTGRES_USER=nexdesk
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=nexdesk

# Manual connection string
DATABASE_URL=postgresql://nexdesk:password@localhost:5432/nexdesk
```

### Database Migrations

```bash
# Initialize Alembic (first time only)
cd nexdesk-backend
alembic init alembic

# Generate migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head
```

---

## Redis Configuration

### Local Development

```bash
# Start Redis
docker run -d --name redis -p 6379:6379 redis:alpine

# Configure
REDIS_URL=redis://localhost:6379/0
```

### Docker Compose

```bash
# Automatically configured in docker-compose.yml
# No manual configuration needed
```

### Redis Features

Redis provides:
- **Caching**: RAG results, API responses
- **Rate Limiting**: Per-user request limits
- **Queuing**: Background job queue
- **Pub/Sub**: WebSocket message broadcasting

### Without Redis

The system works without Redis (degraded mode):
- No caching (slower repeated queries)
- No rate limiting
- No distributed WebSocket support

---

## Advanced RAG Configuration

### Full Pipeline

```
User Query
    ↓
HyDE Query Expansion (HYDE_ENABLED=true)
    ↓
Hybrid Search (HYBRID_ALPHA=0.7)
    ├── Vector Search (70%)
    └── BM25 Keyword Search (30%)
    ↓
Cross-Encoder Reranking (CROSS_ENCODER_ENABLED=true)
    ↓
Top-K Results
    ↓
Deflection Decision (DEFLECT_THRESHOLD=0.72)
    ↓
Generate Response OR Create Ticket
```

### Disable Advanced RAG

For simpler setup or performance:

```bash
USE_ADVANCED_RAG=false
```

This uses basic vector search without HyDE or reranking.

### Memory Optimization

Cross-encoder models use ~500MB memory. To disable:

```bash
CROSS_ENCODER_ENABLED=false
```

---

## Voice Configuration

### Primary: Groq Whisper

```bash
# Uses the same GROQ_API_KEY
# Model: whisper-large-v3-turbo
# Free tier: 10 hours/month audio
```

### Fallback: AWS Transcribe

```bash
USE_AWS=true
AWS_TRANSCRIBE_BUCKET=your-audio-bucket
```

### Supported Audio Formats

- WAV, MP3, MP4, M4A, WebM, OGG, FLAC
- Maximum file size: 25MB

### Voice Endpoints

```bash
# Transcribe audio
POST /api/voice/transcribe

# Voice chat (transcribe + RAG)
POST /api/voice/chat

# Create ticket from voice
POST /api/voice/ticket
```

---

## Performance Tuning

### Request Timing Thresholds

The performance monitor warns when operations exceed thresholds:

| Operation | Default Threshold |
|-----------|------------------|
| HTTP Request | 1000ms |
| LLM Inference | 5000ms |
| RAG Retrieval | 2000ms |
| Database Query | 100ms |
| Redis Operation | 50ms |
| Transcription | 10000ms |

### Disable Performance Monitoring

For production performance:

```bash
ENABLE_PERFORMANCE_MONITORING=false
```

### Connection Pooling

```bash
# PostgreSQL connection pool (SQLAlchemy)
# Configured in database/connection.py
SQLALCHEMY_POOL_SIZE=10
SQLALCHEMY_MAX_OVERFLOW=20

# Redis connection pool
# Automatic in redis-py
```

---

## Production Deployment

### Recommended Configuration

```bash
# .env.production
GROQ_API_KEY=gsk_xxx
GEMINI_API_KEY=xxx
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

# Database
DATABASE_URL=postgresql://nexdesk:xxx@db.example.com:5432/nexdesk

# Redis
REDIS_URL=redis://:password@redis.example.com:6379/0

# Features
USE_ADVANCED_RAG=true
HYDE_ENABLED=true
CROSS_ENCODER_ENABLED=true
DEFLECT_THRESHOLD=0.72
CHROMA_PERSISTENT=true
CHROMA_PERSIST_DIR=chroma_data

# Performance
ENABLE_PERFORMANCE_MONITORING=false
LOG_LEVEL=WARNING
STRICT_STARTUP=true

# Security
FRONTEND_URL=https://yourdomain.com
```

### Docker Deployment

```bash
# Build and start
docker-compose -f docker-compose.prod.yml up -d

# View logs
docker-compose logs -f backend

# Scale workers
docker-compose up -d --scale backend=3
```

### Health Checks

```bash
# Basic health (for load balancers)
GET /health
# Response: {"status": "ok", "version": "2.3.0"}

# Detailed health (for monitoring)
GET /health/detailed
# Response: Full component status

# Performance metrics
GET /health/performance
# Response: Timing statistics
```

---

## Monitoring & Diagnostics

### Logging

```bash
# Log levels
LOG_LEVEL=DEBUG    # All logs (development)
LOG_LEVEL=INFO     # Standard operations (staging)
LOG_LEVEL=WARNING  # Warnings and errors (production)
LOG_LEVEL=ERROR    # Errors only
```

### Performance Monitoring

Access via API:

```bash
curl http://localhost:8000/health/performance
```

Returns:
```json
{
  "health_score": 98.5,
  "total_operations": 1523,
  "slow_operations": 23,
  "operations": {
    "rag_retrieval": {
      "count": 500,
      "avg_ms": 245.5,
      "p95_ms": 890.2,
      "slow_count": 12
    }
  }
}
```

### Analytics Dashboard

```bash
# Overall metrics
GET /api/analytics/

# Trends over time
GET /api/analytics/trends?days=7

# AI audit log
GET /api/analytics/ai-audit?hours=24

# Performance stats
GET /api/analytics/performance
```

### Common Issues

**High Latency:**
1. Check `/health/performance` for slow operations
2. Verify Redis is connected
3. Consider disabling cross-encoder

**Low Deflection Rate:**
1. Review knowledge base coverage
2. Lower `DEFLECT_THRESHOLD`
3. Check HyDE is enabled

**Memory Usage:**
1. Disable cross-encoder (`CROSS_ENCODER_ENABLED=false`)
2. Reduce embedding model cache
3. Scale horizontally instead

---

## Quick Reference

### Minimum Configuration

```bash
GROQ_API_KEY=gsk_your_key_here
```

### Recommended Configuration

```bash
GROQ_API_KEY=gsk_xxx
GEMINI_API_KEY=xxx
SECRET_KEY=random_32_char_string
USE_ADVANCED_RAG=true
DEFLECT_THRESHOLD=0.72
```

### Full Production Configuration

```bash
# See Production Deployment section above
```

---

## Support

- **Health Check:** `GET /health/detailed`
- **Logs:** `docker-compose logs -f backend`
- **Performance:** `GET /health/performance`
- **Documentation:** `/docs` (Swagger UI)
### ChromaDB Persistence

ChromaDB is configured for persistence in production and Docker.

```bash
CHROMA_PERSISTENT=true
CHROMA_PERSIST_DIR=chroma_data
```

In Docker, this path is mounted to a volume (see `docker-compose.yml`).

# Email (optional)
SMTP_HOST=smtp.example.com
SMTP_USERNAME=user
SMTP_PASSWORD=pass
EMAIL_FROM_ADDRESS=support@yourdomain.com
EMAIL_AUTO_REPLY=true

# Integrations (optional)
SLACK_SIGNING_SECRET=...
SLACK_VERIFICATION_TOKEN=...
TEAMS_WEBHOOK_URL=...
