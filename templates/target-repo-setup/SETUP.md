# Target repo setup

Steps to point InfraAI at your Terraform repo. Nothing in this folder ever runs
inside InfraAI itself — copy these files into the target repo and follow along
there.

The CI model, two workflows:

- **`plan.yml`** — runs automatically on merge to `main`. Read-only. Publishes
  the plan (run summary + artifact).
- **`apply.yml`** — `workflow_dispatch` only. A human reads the plan, then runs
  this workflow from the Actions tab. It applies the exact plan that ran. **That
  manual run is the gate.**

> A GitHub Environment *approval* rule (required reviewers) would be the more
> native gate, but it needs a **public** repo or GitHub Enterprise. On a private
> repo on Free/Pro/Team, the manual `workflow_dispatch` is the equivalent.

## 1. Default branch must be `main`
`plan.yml` only triggers on push to `main`, and the `production` Environment's
deployment-branch rule (step 4) refuses an `apply.yml` dispatch from any other
branch — so the apply, and its OIDC token, are pinned to `main`.

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
`apply.yml`'s `environment:` key to match).
- **Deployment branches** — "Protected branches only" (or an explicit `main`
  rule). This is what keeps the apply pinned to `main`: `apply.yml` declares
  `environment: production`, so a dispatch from any other branch is rejected, and
  the OIDC `sub` claim it can produce is fixed (step 5b).
- **Required reviewers** — only offered on public repos / Enterprise. If you have
  it, add yourself: the apply job then also waits for an explicit approval click.
  If you don't, the manual `workflow_dispatch` is the gate.

## 5. GitHub OIDC provider + two IAM roles
Create (or confirm) the GitHub OIDC identity provider in IAM
(`token.actions.githubusercontent.com`, audience `sts.amazonaws.com`), then
create **two** roles. Never give the plan role any mutating permission.

### 5a. `infrai-target-plan-role` — used by the automatic `plan` job
- Permissions policy: `plan-role.json` as-is (read-only + an explicit `Deny` on
  every mutating verb).
- Trust policy — `plan.yml` is ungated, so GitHub issues a `ref:` subject:
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

### 5b. `infrai-apply-role` — used only by `apply.yml`
- Permissions policy: `apply-role.json`. **Extend the `Action` list to match your
  actual resource types** — the shipped policy only covers S3, matching InfraAI's
  own demo/fixture. Set the `<RESOURCE_NAME_PREFIX>` placeholder to the prefix
  InfraAI is allowed to create.
- Trust policy — because `apply.yml`'s job declares `environment: production`,
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
  (If you ever drop the `environment:` key from `apply.yml`, switch this `sub`
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

## 7. Copy the workflows and config, set the GitHub variables
- `plan.yml` → `.github/workflows/plan.yml`
- `apply.yml` → `.github/workflows/apply.yml`
- `infrai.config.yaml.example` → `infrai.config.yaml`, fill in your real budget
  ceiling and allowed resource types.
- Both workflows pin `terraform_version` to the same value — keep them in sync so
  a saved plan stays valid when `apply.yml` consumes it.
- Variables (Settings → Secrets and variables → Actions → Variables):

  | Variable | Scope | Value |
  |---|---|---|
  | `AWS_REGION` | **Repository** | e.g. `eu-west-3` (both workflows read it) |
  | `INFRAI_PLAN_ROLE_ARN` | **Repository** | ARN of `infrai-target-plan-role` |
  | `INFRAI_APPLY_ROLE_ARN` | **Environment → `production`** | ARN of `infrai-apply-role` |

  `AWS_REGION` and `INFRAI_PLAN_ROLE_ARN` must be repository-scoped —
  `plan.yml` has no `environment:` and can't read environment variables. Keep
  `INFRAI_APPLY_ROLE_ARN` environment-scoped so the plan job can't see it.

## 8. Verify
Merge a PR opened by InfraAI. Confirm:
1. **Terraform Plan** runs automatically; its summary shows the diff.
2. Actions tab → **Terraform Apply** → **Run workflow** (from `main`).
3. It pulls that plan, checks it's still current, runs `terraform apply`, and
   writes state to S3.
