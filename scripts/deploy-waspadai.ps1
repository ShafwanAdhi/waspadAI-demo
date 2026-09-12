param(
    [string]$CommitMessage = "Deploy update",
    [string]$Branch = "main",
    [string]$RemoteName = "origin",
    [string]$SshKeyPath = "$env:USERPROFILE\.ssh\bonjermgu-prod",
    [string]$SshTarget = "deploy@103.89.4.104",
    [string]$RemotePath = "/var/www/waspadai-demo",
    [string]$HealthUrl = "https://waspadai.shafwan.digital/api/health",
    [switch]$SkipCommit,
    [switch]$PruneDockerImages
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-LocalStep {
    param(
        [string]$Title,
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "==> $Title" -ForegroundColor Cyan
    & $Command
}

function Invoke-RemoteStep {
    param([string]$Script)

    $normalizedScript = $Script -replace "`r`n", "`n"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($normalizedScript)
    $encoded = [Convert]::ToBase64String($bytes)

    ssh -i $SshKeyPath -o IdentitiesOnly=yes $SshTarget "echo '$encoded' | base64 -d | bash"
}

Invoke-LocalStep "Checking Git workspace" {
    git status --short --branch
}

if (-not $SkipCommit) {
    Invoke-LocalStep "Staging local changes" {
        git add -A
    }

    $pendingChanges = git status --porcelain
    if ($pendingChanges) {
        Invoke-LocalStep "Creating commit" {
            git commit -m $CommitMessage
        }
    }
    else {
        Write-Host ""
        Write-Host "==> No local changes to commit" -ForegroundColor Yellow
    }
}

Invoke-LocalStep "Pushing to GitHub" {
    git push $RemoteName $Branch
}

$remoteScript = @"
set -euo pipefail

cd "$RemotePath"

echo ""
echo "==> Pulling latest code"
git fetch "$RemoteName" "$Branch"
git pull --ff-only "$RemoteName" "$Branch"

echo ""
echo "==> Rebuilding and restarting Docker services"
docker compose up --build -d --remove-orphans

echo ""
echo "==> Container status"
docker compose ps

echo ""
echo "==> Health check"
curl -fsS "$HealthUrl"
echo ""
"@

if ($PruneDockerImages) {
    $remoteScript += @"

echo ""
echo "==> Pruning unused Docker images"
docker image prune -f
"@
}

Invoke-LocalStep "Deploying on VPS" {
    Invoke-RemoteStep $remoteScript
}

Write-Host ""
Write-Host "Deploy finished successfully." -ForegroundColor Green
