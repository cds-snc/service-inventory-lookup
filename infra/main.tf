terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ca-central-1"
}

provider "aws" {
  alias  = "dns"
  region = "ca-central-1"
}

provider "aws" {
  alias  = "us-east-1"
  region = "us-east-1"
}

module "website" {
  source = "github.com/cds-snc/terraform-modules//simple_static_website?ref=v11.3.5"

  domain_name_source    = "service-inventory-lookup.gcorgs.cdssandbox.xyz"
  billing_tag_value     = "service-inventory-lookup"
  index_document        = "en"
  hosted_zone_id        = "Z01243811HX0ZVPGI6SN0"
  is_create_hosted_zone = false

  providers = {
    aws           = aws
    aws.dns       = aws.dns
    aws.us-east-1 = aws.us-east-1
  }
}

module "program_website" {
  source = "github.com/cds-snc/terraform-modules//simple_static_website?ref=v11.3.5"

  domain_name_source    = "program-code-lookup.gcorgs.cdssandbox.xyz"
  billing_tag_value     = "program-code-lookup"
  index_document        = "en"
  hosted_zone_id        = "Z01243811HX0ZVPGI6SN0"
  is_create_hosted_zone = false

  providers = {
    aws           = aws
    aws.dns       = aws.dns
    aws.us-east-1 = aws.us-east-1
  }
}

locals {
  common_tags = {
    CostCentre = "service-inventory-lookup"
    Terraform  = "true"
  }

  program_tags = {
    CostCentre = "program-code-lookup"
    Terraform  = "true"
  }
}

resource "aws_s3_object" "service_html_en" {
  bucket       = module.website.s3_bucket_id
  key          = "en"
  source       = "${path.module}/../service_en.html"
  content_type = "text/html; charset=utf-8"
  etag         = filemd5("${path.module}/../service_en.html")
  tags         = local.common_tags
}

resource "aws_s3_object" "service_html_fr" {
  bucket       = module.website.s3_bucket_id
  key          = "fr"
  source       = "${path.module}/../service_fr.html"
  content_type = "text/html; charset=utf-8"
  etag         = filemd5("${path.module}/../service_fr.html")
  tags         = local.common_tags
}

resource "aws_s3_object" "service_js" {
  bucket       = module.website.s3_bucket_id
  key          = "service.js"
  source       = "${path.module}/../service.js"
  content_type = "text/javascript; charset=utf-8"
  etag         = filemd5("${path.module}/../service.js")
  tags         = local.common_tags
}

resource "aws_s3_object" "services_json" {
  bucket       = module.website.s3_bucket_id
  key          = "services.json"
  source       = "${path.module}/../services.json"
  content_type = "application/json"
  etag         = filemd5("${path.module}/../services.json")
  tags         = local.common_tags
}

resource "aws_s3_object" "security_txt" {
  bucket       = module.website.s3_bucket_id
  key          = ".well-known/security.txt"
  source       = "${path.module}/../security.txt"
  content_type = "text/plain"
  etag         = filemd5("${path.module}/../security.txt")
  tags         = local.common_tags
}

resource "aws_s3_object" "program_html_en" {
  bucket       = module.program_website.s3_bucket_id
  key          = "en"
  source       = "${path.module}/../program_en.html"
  content_type = "text/html; charset=utf-8"
  etag         = filemd5("${path.module}/../program_en.html")
  tags         = local.program_tags
}

resource "aws_s3_object" "program_html_fr" {
  bucket       = module.program_website.s3_bucket_id
  key          = "fr"
  source       = "${path.module}/../program_fr.html"
  content_type = "text/html; charset=utf-8"
  etag         = filemd5("${path.module}/../program_fr.html")
  tags         = local.program_tags
}

resource "aws_s3_object" "program_js" {
  bucket       = module.program_website.s3_bucket_id
  key          = "program.js"
  source       = "${path.module}/../program.js"
  content_type = "text/javascript; charset=utf-8"
  etag         = filemd5("${path.module}/../program.js")
  tags         = local.program_tags
}

resource "aws_s3_object" "program_codes_json" {
  bucket       = module.program_website.s3_bucket_id
  key          = "program_codes.json"
  source       = "${path.module}/../program_codes.json"
  content_type = "application/json"
  etag         = filemd5("${path.module}/../program_codes.json")
  tags         = local.program_tags
}

resource "aws_s3_object" "program_security_txt" {
  bucket       = module.program_website.s3_bucket_id
  key          = ".well-known/security.txt"
  source       = "${path.module}/../security.txt"
  content_type = "text/plain"
  etag         = filemd5("${path.module}/../security.txt")
  tags         = local.program_tags
}

output "website_url" {
  value = "https://service-inventory-lookup.gcorgs.cdssandbox.xyz"
}

output "program_website_url" {
  value = "https://program-code-lookup.gcorgs.cdssandbox.xyz"
}