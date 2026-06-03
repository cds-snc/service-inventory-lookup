# Generic remote state bucket for account - shared with other SDR projects

terraform {
  backend "s3" {
    bucket       = "sdr-tfstate-154541629452"
    key          = "service-inventory-lookup/terraform.tfstate"
    region       = "ca-central-1"
    encrypt      = true
    use_lockfile = true 
  }
}
