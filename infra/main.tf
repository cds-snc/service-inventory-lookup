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
  # Using v10.6.2 because later versions have a bug in waf.tf where dots in the
  # domain name are used directly in WAF resource names, which only allow
  # alphanumeric, hyphen, and underscore characters.
  source = "github.com/cds-snc/terraform-modules//simple_static_website?ref=v10.6.2"

  domain_name_source    = "service-inventory-lookup.gcorgs.cdssandbox.xyz"
  billing_tag_value     = "service-inventory-lookup"
  index_document        = "service_inventory_lookup_en.html"
  hosted_zone_id        = "Z01243811HX0ZVPGI6SN0"
  is_create_hosted_zone = false

  providers = {
    aws           = aws
    aws.dns       = aws.dns
    aws.us-east-1 = aws.us-east-1
  }
}

resource "aws_s3_object" "html_en" {
  bucket       = module.website.s3_bucket_id
  key          = "service_inventory_lookup_en.html"
  source       = "${path.module}/../service_inventory_lookup_en.html"
  content_type = "text/html; charset=utf-8"
  etag         = filemd5("${path.module}/../service_inventory_lookup_en.html")
}

resource "aws_s3_object" "services_json" {
  bucket       = module.website.s3_bucket_id
  key          = "services.json"
  source       = "${path.module}/../services.json"
  content_type = "application/json"
  etag         = filemd5("${path.module}/../services.json")
}

resource "aws_s3_object" "security_txt" {
  bucket       = module.website.s3_bucket_id
  key          = ".well-known/security.txt"
  source       = "${path.module}/../security.txt"
  content_type = "text/plain"
  etag         = filemd5("${path.module}/../security.txt")
}

output "website_url" {
  value = "https://service-inventory-lookup.gcorgs.cdssandbox.xyz"
}