data "aws_iam_policy_document" "plan_state" {
  statement {
    sid       = "ListStateBucket"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::sdr-tfstate-154541629452"]
  }

  statement {
    sid = "ReadWriteStateObjects"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["arn:aws:s3:::sdr-tfstate-154541629452/service-inventory-lookup/*"]
  }
}

resource "aws_iam_policy" "plan_state" {
  name        = "service-inventory-lookup-plan-state"
  description = "State bucket access for the service-inventory-lookup plan role."
  policy      = data.aws_iam_policy_document.plan_state.json
}

locals {
  oidc_roles = [
    {
      name      = "service-inventory-lookup-plan"
      repo_name = "service-inventory-lookup"
      claim     = "pull_request"
      policy_arns = [
        "arn:aws:iam::aws:policy/ReadOnlyAccess",
        aws_iam_policy.plan_state.arn,
      ]
    },
    {
      name        = "service-inventory-lookup-apply"
      repo_name   = "service-inventory-lookup"
      claim       = "ref:refs/heads/main"
      policy_arns = ["arn:aws:iam::aws:policy/AdministratorAccess"]
    },
  ]
}

module "gh_oidc_role" {
  source = "github.com/cds-snc/terraform-modules//gh_oidc_role?ref=v11.3.2"

  billing_tag_value = "service-inventory-lookup"
  org_name          = "cds-snc"
  oidc_exists       = true

  roles = [
    for r in local.oidc_roles : {
      name      = r.name
      repo_name = r.repo_name
      claim     = r.claim
    }
  ]
}

resource "aws_iam_role_policy_attachment" "oidc" {
  for_each = {
    for pair in flatten([
      for r in local.oidc_roles : [
        for idx, arn in r.policy_arns : {
          key        = "${r.name}::${idx}"
          role_name  = r.name
          policy_arn = arn
        }
      ]
    ]) : pair.key => pair
  }

  role       = module.gh_oidc_role.roles[each.value.role_name].name
  policy_arn = each.value.policy_arn
}

output "oidc_role_arns" {
  description = "Map of role name to ARN, for use as role-to-assume in the GitHub Actions workflows."
  value       = { for name, role in module.gh_oidc_role.roles : name => role.arn }
}
