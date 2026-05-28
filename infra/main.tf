terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

variable "aws_region" {
  description = "AWS region to deploy into"
  default     = "ca-central-1"
}

variable "bucket_name" {
  description = "S3 bucket name (must be globally unique)"
  type        = string
  default     = "service-inventory-lookup-kxbrxa"
}

resource "aws_s3_bucket" "site" {
  bucket = var.bucket_name
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket = aws_s3_bucket.site.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_website_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  index_document {
    suffix = "service_inventory_lookup_en.html"
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket     = aws_s3_bucket.site.id
  depends_on = [aws_s3_bucket_public_access_block.site]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
      }
    ]
  })
}

resource "aws_s3_object" "html_en" {
  bucket       = aws_s3_bucket.site.id
  key          = "service_inventory_lookup_en.html"
  source       = "${path.module}/../service_inventory_lookup_en.html"
  content_type = "text/html; charset=utf-8"
  etag         = filemd5("${path.module}/../service_inventory_lookup_en.html")
}

resource "aws_s3_object" "services_json" {
  bucket       = aws_s3_bucket.site.id
  key          = "services.json"
  source       = "${path.module}/../services.json"
  content_type = "application/json"
  etag         = filemd5("${path.module}/../services.json")
}

output "website_url" {
  value = "http://${aws_s3_bucket_website_configuration.site.website_endpoint}"
}
