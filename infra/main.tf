terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
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

module "lookup" {
  source = "github.com/cds-snc/terraform-modules//simple_static_website?ref=v12.1.2"

  domain_name_source    = "lookup.gcorgs.cdssandbox.xyz"
  billing_tag_value     = "lookup"
  index_document        = "index"
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
    CostCentre = "lookup"
    Terraform  = "true"
  }

  html     = "text/html; charset=utf-8"
  js       = "text/javascript; charset=utf-8"
  json     = "application/json"
  security = "text/plain"

  # S3 key => source file and content type
  site_objects = {
    "index"                    = { source = "index.html", content_type = local.html }
    ".well-known/security.txt" = { source = "security.txt", content_type = local.security }

    "service/en"            = { source = "service_en.html", content_type = local.html }
    "service/fr"            = { source = "service_fr.html", content_type = local.html }
    "service/service.js"    = { source = "service.js", content_type = local.js }
    "service/services.json" = { source = "services.json", content_type = local.json }

    "program/en"                 = { source = "program_en.html", content_type = local.html }
    "program/fr"                 = { source = "program_fr.html", content_type = local.html }
    "program/program.js"         = { source = "program.js", content_type = local.js }
    "program/program_codes.json" = { source = "program_codes.json", content_type = local.json }
  }
}

resource "aws_s3_object" "site" {
  for_each = local.site_objects

  bucket       = module.lookup.s3_bucket_id
  key          = each.key
  source       = "${path.module}/../${each.value.source}"
  content_type = each.value.content_type
  etag         = filemd5("${path.module}/../${each.value.source}")
  tags         = local.common_tags
}

output "website_url" {
  value = "https://lookup.gcorgs.cdssandbox.xyz"
}
