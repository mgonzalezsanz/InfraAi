# Target repo setup

Steps to point InfraAI at your Terraform repo. Nothing in this folder ever runs
inside InfraAI itself — copy these files into the target repo and follow along
there.

The CI model: **merge to `main` → `plan` job (read-only, automatic) → `apply`
job (blocked on a human reviewer, applies the exact plan that was shown).**

## 1. Default branch must be `main`
`terraform.yml` only ever triggers on push to `main`, and the `production`
Environment (step 4) is what pins the `apply` — and therefore its OIDC token — to
that branch.

## 2. Grant InfraAI push/PR access
The current PR agent shells out to the `gh` CLI rather than a GitHub App install
(the spec's original plan — noted here since it's a real divergence). Whoever
runs InfraAI needs:
```
gh auth login   # needs the `repo` scope
```
and push access to this repo. A GitHub App install would tighten this later
(scoped, revocable, no dependency on a personal account) but isn't built yet.

## 3. Branch protection on `main`
Require a PR + review before merging, so "PR-gated" is enforced by GitHub itself,
not just by InfraAI's own behavior.

## 4. Create the `production` Environment
Settings → Environments → New environment → `production` (or change
`terraform.yml`'s `environment:` key to match).
- **Required reviewers** — add yourself and/or a maintainers team. This is the
  gate: the `apply` job waits here until someone approves, after reading the
  plan the `plan` job posted to the run summary.
- **Deployment branches** — "Protected branches only" (or an explicit `main`
  rule). This is what keeps the apply scoped to one branch now that the job runs
  under an Environment (see step 5).

## 5. GitHub OIDC provider + two IAM roles
Create (or confirm) the GitHub OIDC identity provider in IAM
(`token.actions.githubusercontent.com`, audience `sts.amazonaws.com`), then
create **two** roles. Never give the plan role any mutating permission.

### 5a. `infrai-target-plan-role` — used by the automatic `plan` job
- Permissions policy: `plan-role.json` as-is (read-only + an explicit `Deny` on
  every mutating verb).
- Trust policy — the `plan` job is ungated, so GitHub issues a `ref:` subject:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:<org>/<repo>:ref:refs/heads/main"
        }
      }
    }]
  }
  ```

### 5b. `infrai-apply-role` — used only by the gated `apply` job
- Permissions policy: `apply-role.json`. **Extend the `Action` list to match your
  actual resource types** — the shipped policy only covers S3, matching InfraAI's
  own demo/fixture. Set the `<RESOURCE_NAME_PREFIX>` placeholder to the prefix
  InfraAI is allowed to create.
- Trust policy — because the `apply` job declares `environment: production`,
  GitHub sets the `sub` claim to `repo:<org>/<repo>:environment:production`, **not**
  `...:ref:refs/heads/main`. Scope the trust to that; the branch guarantee comes
  from the Environment's deployment-branch rule (step 4):
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
          "token.actions.githubusercontent.com:sub": "repo:<org>/<repo>:environment:production"
        }
      }
    }]
  }
  ```
  (If you ever drop the `environment:` key from the `apply` job, switch this `sub`
  back to `repo:<org>/<repo>:ref:refs/heads/main`.)

## 6. Bootstrap Terraform remote state
The apply job runs on an ephemeral runner. You need a remote backend.
- Create an S3 state bucket **out of band** (it can't be managed by the Terraform
  it stores). Enable versioning; block public access:
  ```
  aws s3api create-bucket --bucket <STATE_BUCKET> --region <REGION> \
    --create-bucket-configuration LocationConstraint=<REGION>
  aws s3api put-bucket-versioning --bucket <STATE_BUCKET> \
    --versioning-configuration Status=Enabled
  aws s3api put-public-access-block --bucket <STATE_BUCKET> \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
  ```
- Copy `backend.tf.example` → `backend.tf` in this repo and fill in the bucket,
  key, and region. `use_lockfile` needs Terraform ≥ 1.10 (no DynamoDB table) —
  pin it with `required_version = ">= 1.10"` in `versions.tf`.
- In `apply-role.json`, set the `TerraformStateBackend` statement's `Resource` to
  `arn:aws:s3:::<STATE_BUCKET>/<STATE_KEY_PREFIX>/*` before creating the role.
  The plan job reads state but never writes it (`terraform plan -lock=false`), so
  `plan-role.json` needs no change — its `s3:Get*`/`s3:List*` already cover it.

## 7. Copy the workflow and config, set the GitHub variables
- `terraform.yml` → `.github/workflows/terraform.yml`
- `infrai.config.yaml.example` → `infrai.config.yaml`, fill in your real budget
  ceiling and allowed resource types.
- Variables (Settings → Secrets and variables → Actions → Variables):

  | Variable | Scope | Value |
  |---|---|---|
  | `AWS_REGION` | **Repository** | e.g. `eu-west-3` (both jobs read it) |
  | `INFRAI_PLAN_ROLE_ARN` | **Repository** | ARN of `infrai-target-plan-role` |
  | `INFRAI_APPLY_ROLE_ARN` | **Environment → `production`** | ARN of `infrai-apply-role` |

  Keep `INFRAI_APPLY_ROLE_ARN` environment-scoped so the plan job can't see it.

## 8. Verify
Merge a PR opened by InfraAI. Confirm: `plan` runs and its summary shows the
diff; `apply` moves to "Waiting"; approving it runs `terraform apply` against the
saved plan and writes state to S3.
