# ---------------------------------------------------------------------------
# GitHub Actions OIDC — lets the Deploy workflow assume AWS roles without
# long-lived keys. Two roles, split by privilege:
#
#   stride-github-actions       (WRITE) — trust: push to main only.
#                                 Full apply permissions. Used by the deploy
#                                 jobs that build+push images and `terraform apply`.
#   stride-github-actions-plan  (READ)  — trust: pull_request only.
#                                 Read-only (Get/List/Describe) + ECR push +
#                                 state-backend read. Used by PR `terraform plan`.
#
# Why split: a PR can edit the workflow on its own branch, so a single role
# trusted by `pull_request` would let a malicious PR run `apply` with the
# write role's permissions. The plan role can't mutate anything, so a hostile
# PR gets nothing useful even if it rewrites the workflow.
# ---------------------------------------------------------------------------

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy roles, as owner/name"
  type        = string
  default     = "hamseabd/Stride"
}

# GitHub's OIDC thumbprint is no longer validated by AWS (it uses the JWKS
# from the OIDC discovery doc), but the provider still requires the field.
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]

  tags = {
    Project = "stride"
  }
}

# ---------------------------------------------------------------------------
# Trust policies — one per role, each pinned to a single run context.
# ---------------------------------------------------------------------------

# WRITE role: only a push to main (sub = repo:<repo>:ref:refs/heads/main).
data "aws_iam_policy_document" "github_write_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:ref:refs/heads/main"]
    }
  }
}

# READ role: only a pull_request run (sub = repo:<repo>:pull_request).
data "aws_iam_policy_document" "github_plan_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repo}:pull_request"]
    }
  }
}

# ---------------------------------------------------------------------------
# WRITE role — terraform apply on main.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_actions" {
  name               = "stride-github-actions"
  assume_role_policy = data.aws_iam_policy_document.github_write_assume.json

  tags = {
    Project = "stride"
  }
}

# ECR push (build_and_push.sh) — reuses the policy defined in iam.tf.
resource "aws_iam_role_policy_attachment" "github_ecr_push" {
  role       = aws_iam_role.github_actions.name
  policy_arn = aws_iam_policy.ecr_push.arn
}

data "aws_iam_policy_document" "github_terraform" {
  # Terraform state backend (S3 + DynamoDB lock table).
  statement {
    sid    = "TerraformStateBackend"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::stride-tf-state",
      "arn:aws:s3:::stride-tf-state/*",
    ]
  }

  statement {
    sid    = "TerraformStateLock"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
    ]
    resources = ["arn:aws:dynamodb:${var.aws_region}:*:table/stride-tf-locks"]
  }

  # Resources the stack manages. Service-wide on "*" — accepted blast radius
  # for a solo personal account. The mitigating control is the trust policy:
  # this role is assumable ONLY by a push to main. If this repo ever takes
  # external contributors, scope these to the stack's resource ARNs (Lambda
  # fns, stride-* ECR repos, stride-prod table, the two S3 buckets).
  statement {
    sid    = "ManageStack"
    effect = "Allow"
    actions = [
      "lambda:*",
      "ecr:*",
      "apigateway:*",
      "dynamodb:*",
      "events:*",
      "scheduler:*",
      "s3:*",
      "cloudwatch:*",
      "logs:*",
      "xray:*",
    ]
    resources = ["*"]
  }

  # IAM to manage the Lambda exec role + the OIDC roles/policies this stack owns.
  statement {
    sid    = "ManageIam"
    effect = "Allow"
    actions = [
      "iam:GetRole",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:CreatePolicy",
      "iam:DeletePolicy",
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:ListPolicyVersions",
      "iam:AttachRolePolicy",
      "iam:DetachRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListInstanceProfilesForRole",
      "iam:GetOpenIDConnectProvider",
    ]
    resources = ["*"]
  }

  # PassRole is the privilege-escalation risk in the IAM block above, so scope
  # it: only the Lambda exec role, and only when passed to the Lambda service.
  statement {
    sid       = "PassLambdaExecRole"
    effect    = "Allow"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.stride_lambda_exec.arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_terraform" {
  name   = "stride-github-terraform"
  role   = aws_iam_role.github_actions.id
  policy = data.aws_iam_policy_document.github_terraform.json
}

# ---------------------------------------------------------------------------
# READ role — terraform plan on PRs. No mutate, no iam:* writes, no PassRole.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "github_actions_plan" {
  name               = "stride-github-actions-plan"
  assume_role_policy = data.aws_iam_policy_document.github_plan_assume.json

  tags = {
    Project = "stride"
  }
}

# The PR docker job still builds and pushes an image (the plan references it),
# so the plan role keeps ECR push. Everything else is read-only.
resource "aws_iam_role_policy_attachment" "github_plan_ecr_push" {
  role       = aws_iam_role.github_actions_plan.name
  policy_arn = aws_iam_policy.ecr_push.arn
}

data "aws_iam_policy_document" "github_plan" {
  # State backend: read + lock (plan still acquires the lock and reads state).
  statement {
    sid       = "StateRead"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:ListBucket"]
    resources = ["arn:aws:s3:::stride-tf-state", "arn:aws:s3:::stride-tf-state/*"]
  }

  statement {
    sid    = "StateLock"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
    ]
    resources = ["arn:aws:dynamodb:${var.aws_region}:*:table/stride-tf-locks"]
  }

  # Read-only describe/get/list across the services the stack uses, so
  # `terraform plan` can refresh state. No create/update/delete.
  statement {
    sid    = "ReadOnlyRefresh"
    effect = "Allow"
    actions = [
      "lambda:Get*",
      "lambda:List*",
      "ecr:Describe*",
      "ecr:List*",
      "ecr:GetRepositoryPolicy",
      "ecr:GetLifecyclePolicy",
      "apigateway:GET",
      "dynamodb:DescribeTable",
      "dynamodb:DescribeContinuousBackups",
      "dynamodb:DescribeTimeToLive",
      "dynamodb:ListTagsOfResource",
      "events:Describe*",
      "events:List*",
      "scheduler:Get*",
      "scheduler:List*",
      # The provider refreshes a dozen bucket attributes (accelerate, replication,
      # ownership controls, ...) whose action names do not all start with GetBucket.
      "s3:Get*",
      "s3:List*",
      "cloudwatch:Describe*",
      "cloudwatch:Get*",
      "cloudwatch:List*",
      "logs:Describe*",
      "logs:List*",
      "iam:GetRole",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:GetRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListPolicyVersions",
      "iam:GetOpenIDConnectProvider",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "github_plan" {
  name   = "stride-github-plan"
  role   = aws_iam_role.github_actions_plan.id
  policy = data.aws_iam_policy_document.github_plan.json
}
