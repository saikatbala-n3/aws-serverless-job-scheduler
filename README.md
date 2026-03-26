# AWS Serverless Job Scheduler

Serverless job scheduling system built on AWS Lambda, SQS, and DynamoDB — the serverless equivalent of the [async-job-scheduler](../async-job-scheduler).

## Architecture

API Gateway → Lambda (Submit) → DynamoDB + SQS Queue → Lambda (Worker) → DynamoDB
                                                              ↓ (3 failures)
                                                         SQS DLQ → Lambda (DLQ Handler)

## Key Features

- **Serverless REST API**: API Gateway + Lambda for job submit, get, list, cancel
- **SQS-Driven Workers**: Auto-scaled Lambda workers triggered by SQS events
- **DynamoDB Single-Table Design**: GSI-based queries by status and job type
- **Retry with Redrive**: SQS visibility timeout + maxReceiveCount + DLQ
- **Lambda Layers**: Shared models, repository, and response utilities across functions
- **X-Ray Tracing**: Distributed tracing enabled on all Lambda functions

## Lambda Functions

### Submit Job (POST /jobs)
Validates request via Pydantic, persists job to DynamoDB, enqueues SQS message.

### Get Job (GET /jobs/{job_id})
Fetches single job by primary key.

### List Jobs (GET /jobs)
Queries GSI1 (by status) or GSI2 (by job type). Defaults to PENDING jobs.

### Cancel Job (DELETE /jobs/{job_id})
Conditional update — only cancels PENDING jobs. Returns 400 if already processing.

### Worker
SQS event source mapping. Processes job payload, updates DynamoDB status. Reports `batchItemFailures` for per-message retry on failure.

### DLQ Handler
Marks jobs as FAILED with `Exhausted N retries` error after SQS redrive.

## Quick Start

### Prerequisites
- Python 3.11+
- AWS SAM CLI
- AWS account with CLI configured (`aws configure`)
- Docker (for local testing)

### Deploy to AWS

```bash
# Build all Lambda functions and layer
sam build

# First deploy (interactive — creates samconfig.toml)
sam deploy --guided

# Subsequent deploys
sam deploy
```

### Local Testing

```bash
# Create shared network
docker network create sam-local

# Start DynamoDB Local
docker run -d --name dynamodb-local --network sam-local -p 8001:8000 \
  amazon/dynamodb-local -jar DynamoDBLocal.jar -sharedDb -inMemory

# Create table
aws dynamodb create-table --endpoint-url http://localhost:8001 \
  --table-name job-scheduler-jobs --billing-mode PAY_PER_REQUEST \
  --attribute-definitions \
    AttributeName=job_id,AttributeType=S AttributeName=GSI1PK,AttributeType=S \
    AttributeName=GSI1SK,AttributeType=S AttributeName=GSI2PK,AttributeType=S \
    AttributeName=GSI2SK,AttributeType=S \
  --key-schema AttributeName=job_id,KeyType=HASH \
  --global-secondary-indexes \
    '[{"IndexName":"status-index","KeySchema":[{"AttributeName":"GSI1PK","KeyType":"HASH"},{"AttributeName":"GSI1SK","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}},{"IndexName":"type-index","KeySchema":[{"AttributeName":"GSI2PK","KeyType":"HASH"},{"AttributeName":"GSI2SK","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}]'

# Invoke function
sam local invoke SubmitJobFunction \
  --event events/submit_job.json \
  --env-vars events/env.json \
  --docker-network sam-local
```

## Technology Stack

┌───────────────────┬───────────────────────────────┬───────────────┐
│     Component     │          Technology           │    Version    │
├───────────────────┼───────────────────────────────┼───────────────┤
│ Compute           │ AWS Lambda                    │ Python 3.11   │
├───────────────────┼───────────────────────────────┼───────────────┤
│ API               │ AWS API Gateway               │ REST (v1)     │
├───────────────────┼───────────────────────────────┼───────────────┤
│ Queue             │ AWS SQS                       │ Standard      │
├───────────────────┼───────────────────────────────┼───────────────┤
│ Database          │ AWS DynamoDB                  │ On-demand     │
├───────────────────┼───────────────────────────────┼───────────────┤
│ IaC               │ AWS SAM                       │ 2016-10-31    │
├───────────────────┼───────────────────────────────┼───────────────┤
│ Tracing           │ AWS X-Ray                     │ -             │
├───────────────────┼───────────────────────────────┼───────────────┤
│ Validation        │ Pydantic                      │ v2            │
└───────────────────┴───────────────────────────────┴───────────────┘

## Project Structure

```
aws-serverless-job-scheduler/
├── template.yaml                  # SAM template (Lambda, DynamoDB, SQS, IAM)
├── samconfig.toml                 # Deployment configuration
├── src/
│   ├── layers/shared/             # Lambda Layer — shared across all functions
│   │   ├── requirements.txt
│   │   └── common/
│   │       ├── models.py          # Job, JobStatus, JobCreate, SQSJobMessage
│   │       ├── dynamodb.py        # JobsRepository (GSI queries, conditional updates)
│   │       ├── response.py        # API Gateway response helpers
│   │       └── job_handlers.py    # Job type business logic
│   └── functions/
│       ├── submit_job/app.py      # POST /jobs
│       ├── get_job/app.py         # GET /jobs/{job_id}
│       ├── list_jobs/app.py       # GET /jobs
│       ├── cancel_job/app.py      # DELETE /jobs/{job_id}
│       ├── worker/app.py          # SQS consumer
│       └── dlq_handler/app.py     # DLQ consumer
├── events/                        # Test payloads for sam local invoke
│   ├── env.json                   # Per-function env var overrides (local only)
│   ├── submit_job.json
│   ├── get_job.json
│   ├── list_jobs.json
│   ├── cancel_job.json
│   └── sqs_message.json
└── tests/
```

## Key Concepts

### DynamoDB GSI Single-Table Pattern

```python
# GSI1: query by status — "Get all PENDING jobs"
table.query(
    IndexName="status-index",
    KeyConditionExpression=Key("GSI1PK").eq("PENDING"),
    ScanIndexForward=False,  # newest first
)

# GSI2: query by type — "Get all email jobs"
table.query(
    IndexName="type-index",
    KeyConditionExpression=Key("GSI2PK").eq("email"),
)
```

### Conditional Cancellation

```python
# Only cancels PENDING jobs — prevents race with Worker
table.update_item(
    ConditionExpression="#status = :pending",
    UpdateExpression="SET #status = :cancelled",
)
# Raises ConditionalCheckFailedException if job is already processing
```

### SQS Visibility Timeout Rule

```
Worker Timeout: 60s → SQS VisibilityTimeout: 180s (3x rule)
maxReceiveCount: 3 → after 3 failures, message moves to DLQ
```

## Architecture Decisions

### Why DynamoDB over RDS?

- No servers to manage, scales to zero
- Pay-per-request billing suits low-volume job scheduling
- GSIs provide flexible query patterns without joins
- TTL for automatic job expiry

### Why SQS over EventBridge?

- SQS provides durable queuing with visibility timeout for at-least-once delivery
- Built-in redrive policy to DLQ without custom logic
- Lambda event source mapping handles polling automatically

### Why SAM over CDK/Terraform?

- Native Lambda/API Gateway integration with minimal boilerplate
- `sam local invoke` for local testing without AWS deployment
- `BuildMethod: python3.11` handles Lambda Layer packaging automatically

## Testing

```bash
# Submit a job
sam local invoke SubmitJobFunction \
  --event events/submit_job.json --env-vars events/env.json --docker-network sam-local

# Get the job (update job_id in events/get_job.json first)
sam local invoke GetJobFunction \
  --event events/get_job.json --env-vars events/env.json --docker-network sam-local

# List PENDING jobs
sam local invoke ListJobsFunction \
  --event events/list_jobs.json --env-vars events/env.json --docker-network sam-local

# Cancel the job
sam local invoke CancelJobFunction \
  --event events/cancel_job.json --env-vars events/env.json --docker-network sam-local

# Verify in DynamoDB
aws dynamodb scan --endpoint-url http://localhost:8001 --table-name job-scheduler-jobs
```

## Troubleshooting

### DYNAMODB_ENDPOINT not passed to Lambda

SAM only injects env vars declared in `template.yaml`. Ensure `DYNAMODB_ENDPOINT: ""` exists in `Globals.Function.Environment.Variables`, then override in `events/env.json` using per-function keys (not `"Parameters"`).

### Layer import errors after rebuild

`BuildMethod: python3.11` wraps source in `python/` automatically. Layer source must be at `src/layers/shared/common/` — not `src/layers/shared/python/common/`.

### DynamoDB Local credential mismatch

Start with `-sharedDb` flag so all AWS credentials share one database. Without it, CLI-created tables are invisible to Lambda (different access key isolation).

## Deployment

```bash
sam build
sam deploy --guided          # First time
sam deploy                   # Subsequent

# Tail Lambda logs
sam logs -n WorkerFunction --stack-name job-scheduler --tail

# Tear down all resources
sam delete --stack-name job-scheduler
```

---
**Project Status:** ✅ API functions tested locally (Worker/DLQ require AWS or ElasticMQ)
**Complexity Level:** Advanced
**Key Learning:** Lambda Layers, DynamoDB GSI single-table design, SQS redrive policy
