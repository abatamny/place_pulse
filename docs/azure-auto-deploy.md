# Automatic Azure deployment

The CI workflow can update the existing course Azure VM after the backend tests, frontend build, local-AI contract tests, and fresh Compose startup all pass. It never creates a VM during CI and it never deploys pull requests.

## Deployment behavior

- Runs only for a successful `main` push or a manual workflow run on `main`.
- Remains disabled until the repository variable `AZURE_DEPLOY_ENABLED` is set to `true`.
- Uses GitHub OpenID Connect (OIDC), so no long-lived Azure client secret is stored in GitHub.
- Sends `deploy/azure/update-vm.sh` through Azure VM Run Command.
- Fetches and deploys the exact Git commit that passed CI.
- Preserves `/opt/placepulse/.env`, PostgreSQL data, and uploaded-media volumes.
- Fails the deployment job if the public web container cannot reach the backend health endpoint.

## One-time setup

1. Provision the VM once with `scripts/deploy-azure.ps1`. Wait until its public `/api/health` endpoint is ready. This creates `/opt/placepulse`, installs its private `.env`, and starts Compose.
2. In Microsoft Entra ID, create an app registration for this repository. Do not create a client secret.
3. On that app registration, add a **Federated credential** using the **GitHub Actions deploying Azure resources** scenario:
   - Organization: `abatamny`
   - Repository: `place_pulse`
   - Entity type: `Environment`
   - Environment: `azure-production`
4. On the Azure VM's **Access control (IAM)** page, give the new service principal the **Virtual Machine Contributor** role scoped to this VM only. This role supplies the VM Run Command permission.
5. In the GitHub repository, create an environment named `azure-production`. Add these environment secrets:
   - `AZURE_CLIENT_ID`: the app registration's Application (client) ID
   - `AZURE_TENANT_ID`: the Microsoft Entra Directory (tenant) ID
   - `AZURE_SUBSCRIPTION_ID`: the Azure subscription ID
6. Under **Settings → Secrets and variables → Actions → Variables**, add these repository variables:
   - `AZURE_RESOURCE_GROUP`: the VM resource group
   - `AZURE_VM_NAME`: the existing VM name
   - `AZURE_DEPLOY_ENABLED`: `true`

The federated credential must target the `azure-production` environment because the deployment job uses that environment. Required reviewers are optional; enabling them changes the deployment from fully automatic to approval-gated.

## Using and disabling deployment

Push to `main` normally. The `Deploy to Azure VM` job starts only after all four required CI jobs succeed. You may also use **Run workflow** on `main` to rerun tests and deploy the selected commit.

Set `AZURE_DEPLOY_ENABLED` to `false` before deleting or pausing the VM. A missing VM, missing OIDC configuration, or unhealthy application makes only the deployment job fail; it does not modify the local development stack.
