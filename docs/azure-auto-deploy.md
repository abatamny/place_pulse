# Automatic Azure deployment over SSH

The CI workflow updates an existing course Azure VM over SSH after the backend tests, frontend build, local-AI contract tests, and fresh Compose startup all pass. Azure resource creation is manual, CI never creates infrastructure, and pull requests never deploy.

## Deployment behavior

- Runs only for a successful `main` push or a manual workflow run on `main`.
- Remains disabled until the repository variable `AZURE_DEPLOY_ENABLED` is set to `true`.
- Connects with a deployment-only SSH key and a pinned VM host key.
- Fetches and deploys the exact Git commit that passed CI.
- Runs the deployment commands directly from `.github/workflows/ci.yml`; there is no separate deployment script.
- Preserves `/opt/placepulse/.env`, PostgreSQL data, uploaded media, downloaded models, and the Overpass index.
- Fails the deployment job if the public web container cannot reach the backend health endpoint.

## Prepare the VM once

1. In the Azure portal, create an Ubuntu 24.04 VM with an SSH public key. Allow inbound TCP 22 for SSH and TCP 80 for the application. GitHub-hosted runner addresses change, so port 22 must be reachable by the runner unless a self-hosted runner or maintained IP allow-list is used.
2. Connect to the VM and install Docker, Compose, and Git:

   ```sh
   sudo apt-get update
   sudo apt-get install -y docker.io docker-compose-v2 git
   sudo systemctl enable --now docker
   sudo usermod -aG docker "$USER"
   sudo install -d -o "$USER" -g "$USER" /opt/placepulse
   git clone --depth 1 --branch main https://github.com/abatamny/place_pulse.git /opt/placepulse
   ```

3. Log out and reconnect so the Docker group membership takes effect.
4. Create `/opt/placepulse/.env`, set `APP_PORT=80`, and add strong `VERIFICATION_SECRET` and `POSTGRES_PASSWORD` values. Add external AI or Twilio values only when those providers are used. Then run:

   ```sh
   chmod 600 /opt/placepulse/.env
   cd /opt/placepulse
   docker compose up --build -d
   ```

5. Confirm `http://<vm-host>/api/health` returns a healthy response.

The SSH user must own `/opt/placepulse`, be able to read its `.env`, and run `docker compose` without `sudo`. If an existing VM was created with the removed provisioning helper, migrate it once with `sudo chown -R "$USER":"$USER" /opt/placepulse` and `sudo usermod -aG docker "$USER"`, then reconnect.

## Create the deployment SSH credentials

Generate a dedicated key locally rather than reusing a personal login key:

```sh
ssh-keygen -t ed25519 -N "" -f placepulse-actions -C github-actions-placepulse
```

Append `placepulse-actions.pub` to the deployment user's `~/.ssh/authorized_keys` on the VM. The key has no passphrase because the workflow is non-interactive, so use it only for this deployment. Keep the private `placepulse-actions` file local until it is copied into the GitHub environment secret, then protect or delete the local copy as appropriate.

In an already trusted VM session, obtain the host fingerprint with `sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`. Compare it with `ssh-keyscan -t ed25519 <vm-host> 2>/dev/null | ssh-keygen -lf -` locally. After the fingerprints match, run `ssh-keyscan -t ed25519 -H <vm-host>` and save the resulting line. Do not disable strict host-key checking or trust an unverified scan.

## Configure GitHub

1. Create a GitHub environment named `azure-production`. Required reviewers are optional; enabling them makes deployment approval-gated.
2. Add these repository variables under **Settings > Secrets and variables > Actions > Variables**:
   - `AZURE_VM_HOST`: the VM public IPv4 address or DNS name.
   - `AZURE_VM_USER`: the SSH deployment user.
   - `AZURE_DEPLOY_ENABLED`: `true`.
3. Add these secrets under **Settings > Environments > azure-production > Environment secrets**:
   - `AZURE_VM_SSH_PRIVATE_KEY`: the complete deployment-only private key, including its header and footer.
   - `AZURE_VM_KNOWN_HOSTS`: the verified `ssh-keyscan -t ed25519 -H <vm-host>` output.

No Microsoft Entra app registration, federated credential, Azure IAM role, Azure client secret, or Azure CLI login is required by the workflow.

## Using and disabling deployment

Push to `main` normally. The `Deploy to Azure VM` job starts only after all four required CI jobs succeed. A manual workflow run must target `main` to deploy its selected commit.

Set `AZURE_DEPLOY_ENABLED` to `false` before deleting or pausing the VM. A missing SSH configuration, unreachable VM, failed build, or unhealthy application fails only the deployment job; it does not modify the local development stack. Rotate the deployment key by authorizing a new public key, replacing the GitHub secret, testing it, and removing the old public key from `authorized_keys`.
