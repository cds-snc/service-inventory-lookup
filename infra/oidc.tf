locals {
  oidc_roles = [
    {
      name        = "service-inventory-lookup-plan"
      repo_name   = "service-inventory-lookup"
      claim       = "*"
      policy_arns = ["arn:aws:iam::aws:policy/ReadOnlyAccess"]
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
