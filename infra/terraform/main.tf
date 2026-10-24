# SKETCH, NOT APPLIED.
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.80" }
  }
  # backend "s3" { ... }   intentionally absent: this sketch is never applied
}

provider "aws" {
  region = var.region
  default_tags { tags = { app = "groundplan", env = var.env } }
}

variable "region" { default = "us-west-2" }
variable "env" { default = "prod" }
variable "image_tag" { type = string }
variable "domain" { default = "app.example.com" }
variable "certificate_arn" { type = string }
