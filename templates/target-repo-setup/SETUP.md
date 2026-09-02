# Target repo setup

Steps to point InfraAI at your Terraform repo. Nothing in this folder ever runs
inside InfraAI itself — copy these files into the target repo and follow along
there.

## 1. Default branch must be `main`
Required so `infrai-apply-role`'s OIDC trust policy can be scoped to
`repo:<org>/<repo>:ref:refs/heads/main` (step 5).

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

## 4. Create a protected GitHub Environment
Name it `production` (or update `apply.yml`'s `environment:` key to match).
Add protection rules — required reviewers and/or restrict to the `main` branch —
so the apply job's secrets are gated at the platform level.

## 5. Set up `infrai-apply-role` in AWS
- Create (or confirm) the GitHub OIDC identity provider in IAM
  (`token.actions.githubusercontent.com`).
- Create the role using `apply-role.json` as its permissions policy. **Extend the
  `Action` list to match your actual resource types** — the shipped policy only
  covers S3, matching InfraAI's own demo/fixture.
- Trust policy, scoped to this repo's `main` branch only:
  ```json
  {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": { "Federated": "arn:aws:iam::<ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com" },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": { "token.actions.githubusercontent.com:sub": "repo:<org>/<repo>:ref:refs/heads/main" }
      }
    }]
  }
  ```
- In this repo's Settings → Environments → `production`, add variables
  `INFRAI_APPLY_ROLE_ARN` and `AWS_REGION` (used by `apply.yml`).

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
  key, and region. `use_lockfile` needs Terraform ≥ 1.10 (no DynamoDB table).
- In `apply-role.json`, set the `TerraformStateBackend` statement's `Resource` to
  `arn:aws:s3:::<STATE_BUCKET>/<STATE_KEY_PREFIX>/*` before creating/updating the
  role. (`GetObject`/`ListBucket` are already covered by `ReadOnlyForPlanning`.)

## 7. Copy the workflow and config
- `apply.yml` → `.github/workflows/apply.yml`
- `infrai.config.yaml.example` → `infrai.config.yaml`, fill in your real budget
  ceiling and allowed resource types.

## 8. Verify
Merge a PR opened by InfraAI and confirm the apply workflow runs (and waits for
approval, if the Environment requires it).
