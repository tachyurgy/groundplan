resource "aws_kms_key" "db" {
  description         = "groundplan RDS + secret encryption"
  enable_key_rotation = true
}

resource "aws_db_subnet_group" "db" {
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_db_parameter_group" "pg17" {
  family = "postgres17"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
}

resource "aws_db_instance" "main" {
  identifier                          = "groundplan-${var.env}"
  engine                              = "postgres"
  engine_version                      = "17"
  instance_class                      = "db.r7g.large"
  allocated_storage                   = 100
  max_allocated_storage               = 500
  storage_type                        = "gp3"
  storage_encrypted                   = true
  kms_key_id                          = aws_kms_key.db.arn
  multi_az                            = true
  db_name                             = "groundplan"
  username                            = "groundplan_admin"
  manage_master_user_password         = true # RDS-managed secret in Secrets Manager
  master_user_secret_kms_key_id       = aws_kms_key.db.arn
  iam_database_authentication_enabled = true
  db_subnet_group_name                = aws_db_subnet_group.db.name
  vpc_security_group_ids              = [aws_security_group.db.id]
  parameter_group_name                = aws_db_parameter_group.pg17.name
  backup_retention_period             = 14
  deletion_protection                 = true
  performance_insights_enabled        = true
  auto_minor_version_upgrade          = true
  copy_tags_to_snapshot               = true
  final_snapshot_identifier           = "groundplan-${var.env}-final"
}
