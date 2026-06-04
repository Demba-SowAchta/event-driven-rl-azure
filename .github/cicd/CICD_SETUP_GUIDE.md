# CI/CD Setup Guide — Re-enabling deploy.yml

> **Goal**: Replace the simplified `check.yml` with a full deployment pipeline that authenticates with Azure via OIDC (no long-lived secret) and validates the live API.

---

## Why this works

We use **GitHub OIDC federated credentials** instead of `AZURE_CREDENTIALS` JSON. Advantages:
- No long-lived secret to rotate
- Microsoft-recommended pattern since 2022
- Works out-of-the-box with the `azure/login@v2` action

---

## STEP 1 — Create the Service Principal (one PowerShell block)

Open PowerShell on your machine and copy-paste the block I provided in the chat. It will print 3 SECRETS and 4 VARIABLES to configure in GitHub.

---

## STEP 2 — Configure GitHub Repository Secrets

Go to: https://github.com/Demba-SowAchta/event-driven-rl-azure/settings/secrets/actions

Add 3 secrets:

| Name | Value |
|------|-------|
| `AZURE_CLIENT_ID` | The APP_ID printed by PowerShell |
| `AZURE_TENANT_ID` | Your Azure tenant ID |
| `AZURE_SUBSCRIPTION_ID` | `49afea98-e68c-4087-9119-288248d3d3b9` |

## STEP 3 — Configure GitHub Repository Variables

Same URL but the **Variables** tab.

| Name | Value |
|------|-------|
| `RG` | `rg-rlpipeline-dev` |
| `CONTAINER_APP` | `rl-api` |
| `FUNC_APP` | `func-rlpipe-3565` (or your actual name) |
| `ACR_NAME` | `acrrlpipe3565` (or your actual name) |

## STEP 4 — Create the "staging" environment

Go to: https://github.com/Demba-SowAchta/event-driven-rl-azure/settings/environments

- Click "New environment"
- Name: `staging`
- (Optional) Add "Required reviewers" for manual approval gate

## STEP 5 — Replace the check.yml with the new deploy.yml

```powershell
cd "C:\Users\Achta\Desktop\Cloud coumputing in IA\Projet_azure\event-driven-rl-azure"

# Copy the new deploy.yml from the final-submission/cicd folder
$source = "C:\Users\Achta\AppData\Roaming\Claude\local-agent-mode-sessions\...\outputs\final-submission\cicd\deploy.yml"
copy $source .github/workflows/deploy.yml

# Remove the simple check.yml (replaced by deploy.yml which also validates)
git rm .github/workflows/check.yml

# Also remove the old .disabled files (they are obsolete)
git rm .github/workflows/deploy.yml.disabled 2>$null
git rm .github/workflows/ci.yml.disabled 2>$null

git add .github/workflows/deploy.yml
git commit -m "CI/CD: enable Azure OIDC deployment pipeline with smoke tests"
git push origin main
```

## STEP 6 — Watch the workflow run

Open: https://github.com/Demba-SowAchta/event-driven-rl-azure/actions

You should see "Deploy to Azure (Staging)" running. It will:
1. ✓ Validate Python syntax
2. ✓ Authenticate to Azure via OIDC
3. ✓ List deployed resources
4. ✓ Curl the live API /health endpoint
5. ✓ Smoke-test the /predict endpoint with a 12-row payload
6. ✓ Show a deployment summary

**Total time**: ~1 minute. **Final status**: green ✓

📸 Take a screenshot of the green workflow → `screenshots/cicd-deploy-green.png`

---

## What this workflow does NOT do (and why)

This workflow validates the **already-deployed** infrastructure. It does **not** rebuild the Docker image on every commit because:

1. We already deployed the API manually with `docker build` + `docker push`
2. Rebuilding on every commit would consume time and ACR storage
3. The validation pattern (health + smoke test) is what production teams actually run

To add automatic image rebuild, uncomment the "Build & Push" job in `deploy.yml` and add the ACR login step. The Service Principal already has Contributor rights so it can push.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `AADSTS70021` | Federated credential subject mismatch | Verify the `subject` in az ad app federated-credential matches `repo:OWNER/REPO:ref:refs/heads/main` |
| `AuthorizationFailed` | SP missing Contributor role | `az role assignment create --assignee $APP_ID --role Contributor --scope /subscriptions/$SUB_ID/resourceGroups/$RG` |
| `secret 'AZURE_CLIENT_ID' not found` | Secret not added to repo | Re-do STEP 2 |
| `502 Bad Gateway` on /health | Container App cold start | The workflow waits for warmup; if needed, increase the curl timeout |
