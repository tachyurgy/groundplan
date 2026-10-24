resource "aws_ecr_repository" "api" {
  name                 = "groundplan-api"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/groundplan-api"
  retention_in_days = 90
}

resource "aws_ecs_cluster" "main" {
  name = "groundplan"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "groundplan-ecs-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secret" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
      Resource = [aws_db_instance.main.master_user_secret[0].secret_arn, aws_kms_key.db.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name               = "groundplan-api-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

# The only thing the running API may call: Bedrock, for the optional narrative (off by default).
resource "aws_iam_role_policy" "task_bedrock" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid      = "BedrockNarrativeOnly"
      Effect   = "Allow"
      Action   = ["bedrock:InvokeModel", "bedrock:Converse"]
      Resource = "arn:aws:bedrock:${var.region}::foundation-model/anthropic.*"
    }]
  })
}

resource "aws_ecs_task_definition" "api" {
  family                   = "groundplan-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  # full container definition lives in ../ecs-task-def.json; this references the same shape
  container_definitions = jsonencode([{
    name                   = "api"
    image                  = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8000 }]
    environment = [
      { name = "DB_HOST", value = aws_db_instance.main.address },
      { name = "DB_NAME", value = "groundplan" },
      { name = "GP_LLM_PROVIDER", value = "" },
    ]
    secrets = [
      { name = "DB_USER", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:username::" },
      { name = "DB_PASSWORD", valueFrom = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::" },
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { "awslogs-group" = aws_cloudwatch_log_group.api.name, "awslogs-region" = var.region, "awslogs-stream-prefix" = "api" }
    }
  }])
}

resource "aws_lb" "api" {
  name                       = "groundplan-api"
  load_balancer_type         = "application"
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name        = "groundplan-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id
  health_check { path = "/api/v1/health" }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_service" "api" {
  name            = "groundplan-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 2
  launch_type     = "FARGATE"
  network_configuration {
    subnets          = aws_subnet.app[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
}

resource "aws_wafv2_web_acl" "api" {
  name  = "groundplan-api"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  rule {
    name     = "aws-common"
    priority = 1
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
        rule_action_override {
          name = "SizeRestrictions_BODY" # PDF uploads exceed the 8 KB body default
          action_to_use {
            count {}
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "known-bad-inputs"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "rate-limit"
    priority = 3
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "groundplan-api"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "api" {
  resource_arn = aws_lb.api.arn
  web_acl_arn  = aws_wafv2_web_acl.api.arn
}

# CloudTrail: management + data events to an object-locked bucket
resource "aws_s3_bucket" "trail" {
  bucket              = "groundplan-${var.env}-cloudtrail"
  object_lock_enabled = true
}

resource "aws_s3_bucket_public_access_block" "trail" {
  bucket                  = aws_s3_bucket.trail.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "trail" {
  bucket = aws_s3_bucket.trail.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Sid = "AclCheck", Effect = "Allow", Principal = { Service = "cloudtrail.amazonaws.com" }, Action = "s3:GetBucketAcl",
      Resource = aws_s3_bucket.trail.arn },
      { Sid = "Write", Effect = "Allow", Principal = { Service = "cloudtrail.amazonaws.com" }, Action = "s3:PutObject",
        Resource = "${aws_s3_bucket.trail.arn}/AWSLogs/*",
      Condition = { StringEquals = { "s3:x-amz-acl" = "bucket-owner-full-control" } } },
    ]
  })
}

resource "aws_cloudtrail" "main" {
  name                          = "groundplan"
  s3_bucket_name                = aws_s3_bucket.trail.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_log_file_validation    = true
  kms_key_id                    = aws_kms_key.db.arn
  depends_on                    = [aws_s3_bucket_policy.trail]
}

output "alb_dns" { value = aws_lb.api.dns_name }
