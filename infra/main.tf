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

# Old per-tool domains, kept as redirects to lookup.gcorgs.cdssandbox.xyz
# until 2026-12-16. Delete this block and the redirect template to retire them.
locals {
  old_domains = {
    service = "service-inventory-lookup.gcorgs.cdssandbox.xyz"
    program = "program-code-lookup.gcorgs.cdssandbox.xyz"
  }

  redirect_text = {
    en = {
      title   = "This page has moved"
      message = "This page has moved. You will be redirected to"
    }
    fr = {
      title   = "Cette page a déménagé"
      message = "Cette page a déménagé. Vous serez redirigé vers"
    }
  }

  # "<tool>/<lang>" => S3 key and redirect page
  redirect_objects = merge([
    for tool, _ in local.old_domains : {
      for lang, text in local.redirect_text : "${tool}/${lang}" => {
        tool = tool
        key  = lang
        content = templatefile("${path.module}/redirect.html.tftpl", {
          lang    = lang
          target  = "https://lookup.gcorgs.cdssandbox.xyz/${tool}/${lang}"
          title   = text.title
          message = text.message
        })
      }
    }
  ]...)
}

module "old_domain" {
  for_each = local.old_domains
  source   = "github.com/cds-snc/terraform-modules//simple_static_website?ref=v12.1.2"

  domain_name_source    = each.value
  billing_tag_value     = "lookup"
  index_document        = "en"
  hosted_zone_id        = "Z01243811HX0ZVPGI6SN0"
  is_create_hosted_zone = false

  providers = {
    aws           = aws
    aws.dns       = aws.dns
    aws.us-east-1 = aws.us-east-1
  }
}

resource "aws_s3_object" "old_domain_redirect" {
  for_each = local.redirect_objects

  bucket       = module.old_domain[each.value.tool].s3_bucket_id
  key          = each.value.key
  content      = each.value.content
  content_type = local.html
  tags         = local.common_tags
}

output "website_url" {
  value = "https://lookup.gcorgs.cdssandbox.xyz"
}
