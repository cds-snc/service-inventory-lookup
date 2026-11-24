# Old per-tool domains, kept as 301 redirects to lookup.gcorgs.cdssandbox.xyz

locals {
  # Hostnames are repeated in old_domain_redirect.js; keep the two in sync
  old_domains = {
    service = "service-inventory-lookup.gcorgs.cdssandbox.xyz"
    program = "program-code-lookup.gcorgs.cdssandbox.xyz"
  }

  hosted_zone_id = "Z01243811HX0ZVPGI6SN0"
}

resource "aws_cloudfront_function" "old_domain_redirect" {
  name    = "lookup-old-domain-redirect"
  runtime = "cloudfront-js-2.0"
  comment = "301 redirects from the old lookup domains to lookup.gcorgs.cdssandbox.xyz"
  publish = true
  code    = file("${path.module}/old_domain_redirect.js")
}

data "aws_cloudfront_cache_policy" "caching_disabled" {
  name = "Managed-CachingDisabled"
}

resource "aws_acm_certificate" "old_domain" {
  for_each = local.old_domains
  provider = aws.us-east-1

  domain_name               = each.value
  subject_alternative_names = ["*.${each.value}"]
  validation_method         = "DNS"
  tags                      = local.common_tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "old_domain_cert_validation" {
  for_each = {
    for dvo in flatten([for cert in aws_acm_certificate.old_domain : cert.domain_validation_options]) :
    dvo.domain_name => dvo
  }
  provider = aws.dns

  zone_id         = local.hosted_zone_id
  allow_overwrite = true
  name            = each.value.resource_record_name
  records         = [each.value.resource_record_value]
  type            = each.value.resource_record_type
  ttl             = 60
}

resource "aws_acm_certificate_validation" "old_domain" {
  for_each = local.old_domains
  provider = aws.us-east-1

  certificate_arn = aws_acm_certificate.old_domain[each.key].arn
  validation_record_fqdns = [
    for dvo in aws_acm_certificate.old_domain[each.key].domain_validation_options :
    aws_route53_record.old_domain_cert_validation[dvo.domain_name].fqdn
  ]
}

resource "aws_cloudfront_distribution" "old_domain" {
  for_each = local.old_domains

  enabled      = true
  comment      = "Redirects ${each.value} to lookup.gcorgs.cdssandbox.xyz"
  aliases      = [each.value]
  http_version = "http2"
  price_class  = "PriceClass_100"

  # Never reached: the viewer-request function answers every request
  origin {
    domain_name = "lookup.gcorgs.cdssandbox.xyz"
    origin_id   = "placeholder"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id       = "placeholder"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.caching_disabled.id
    viewer_protocol_policy = "redirect-to-https"

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.old_domain_redirect.arn
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.old_domain[each.key].certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  tags = local.common_tags
}

resource "aws_route53_record" "old_domain_alias" {
  for_each = local.old_domains
  provider = aws.dns

  zone_id = local.hosted_zone_id
  name    = each.value
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.old_domain[each.key].domain_name
    zone_id                = aws_cloudfront_distribution.old_domain[each.key].hosted_zone_id
    evaluate_target_health = false
  }
}

# Moved in place, not recreated: a CloudFront alias can be on only one distribution at a time

moved {
  from = module.old_domain["service"].aws_cloudfront_distribution.simple_static_website
  to   = aws_cloudfront_distribution.old_domain["service"]
}

moved {
  from = module.old_domain["program"].aws_cloudfront_distribution.simple_static_website
  to   = aws_cloudfront_distribution.old_domain["program"]
}

moved {
  from = module.old_domain["service"].aws_acm_certificate.cloudfront[0]
  to   = aws_acm_certificate.old_domain["service"]
}

moved {
  from = module.old_domain["program"].aws_acm_certificate.cloudfront[0]
  to   = aws_acm_certificate.old_domain["program"]
}

moved {
  from = module.old_domain["service"].aws_acm_certificate_validation.cloudfront[0]
  to   = aws_acm_certificate_validation.old_domain["service"]
}

moved {
  from = module.old_domain["program"].aws_acm_certificate_validation.cloudfront[0]
  to   = aws_acm_certificate_validation.old_domain["program"]
}

moved {
  from = module.old_domain["service"].aws_route53_record.cloudfront_certificate_validation["service-inventory-lookup.gcorgs.cdssandbox.xyz"]
  to   = aws_route53_record.old_domain_cert_validation["service-inventory-lookup.gcorgs.cdssandbox.xyz"]
}

moved {
  from = module.old_domain["service"].aws_route53_record.cloudfront_certificate_validation["*.service-inventory-lookup.gcorgs.cdssandbox.xyz"]
  to   = aws_route53_record.old_domain_cert_validation["*.service-inventory-lookup.gcorgs.cdssandbox.xyz"]
}

moved {
  from = module.old_domain["program"].aws_route53_record.cloudfront_certificate_validation["program-code-lookup.gcorgs.cdssandbox.xyz"]
  to   = aws_route53_record.old_domain_cert_validation["program-code-lookup.gcorgs.cdssandbox.xyz"]
}

moved {
  from = module.old_domain["program"].aws_route53_record.cloudfront_certificate_validation["*.program-code-lookup.gcorgs.cdssandbox.xyz"]
  to   = aws_route53_record.old_domain_cert_validation["*.program-code-lookup.gcorgs.cdssandbox.xyz"]
}

moved {
  from = module.old_domain["service"].aws_route53_record.cloudfront_alias
  to   = aws_route53_record.old_domain_alias["service"]
}

moved {
  from = module.old_domain["program"].aws_route53_record.cloudfront_alias
  to   = aws_route53_record.old_domain_alias["program"]
}
