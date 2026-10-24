# Terraform sketch (NOT APPLIED)

Shape of a production deployment for the API. Nothing here has been planned or applied, there is no backend
configured and no credentials. It exists to make the architecture concrete in a review.

- `network.tf`: VPC across 2 AZs, public subnets (ALB, NAT), private app subnets (Fargate), isolated DB subnets.
- `data.tf`: RDS PostgreSQL 17 Multi-AZ, encrypted with a CMK, RDS-managed master secret in Secrets Manager,
  IAM auth on, deletion protection, 14-day PITR.
- `app.tf`: ECR, ECS cluster, Fargate service behind an ALB (HTTPS only), WAF (AWS managed common + known-bad
  inputs + rate limit), task/execution roles (Bedrock invoke only, secret read only), CloudTrail to an
  object-locked bucket, CloudWatch log group with 90-day retention.

Uploaded documents are processed in the task's memory and never written to S3; the only S3 bucket is the
CloudTrail sink.
