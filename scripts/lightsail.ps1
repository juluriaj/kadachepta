# Desktop-side helper for the Lightsail server. Runbook: docs/lightsail-pilot.md
#
#   powershell -ExecutionPolicy Bypass -File scripts\lightsail.ps1 <command>   (or: npm run server -- <command>)
#
#   status            containers, deployed build, disk and memory on the server
#   deploy [ref]      deploy origin/main (or a branch, tag or commit); rolls back by itself if the API fails
#   sync              copy media and the seed recordings to the server (resumable; safe to re-run any time)
#   cutover           move the live data: stop the desktop API, final sync, copy the database, restart the server
#   logs [service]    last 200 log lines (api, worker-media, caddy, postgres, backup)
#   ssh               open a shell on the server
#
# Needs two lines in .env: KC_SERVER_HOST (the static IP or a host name) and KC_SERVER_SSH_KEY (private key path).
param(
    [Parameter(Position = 0)][ValidateSet("status", "deploy", "sync", "cutover", "logs", "ssh")][string]$Command = "status",
    [Parameter(Position = 1)][string]$Argument = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) { throw "Missing .env. Run: python scripts/setup_local.py" }
$settings = @{}
Get-Content $envFile | Where-Object { $_ -match '^\s*[A-Z_]+=' } | ForEach-Object {
    $key, $value = $_ -split '=', 2
    $settings[$key.Trim()] = $value.Trim()
}

$server = $settings.KC_SERVER_HOST
$keyFile = $settings.KC_SERVER_SSH_KEY
if (-not $server -or -not $keyFile) {
    throw "Add KC_SERVER_HOST=<static IP> and KC_SERVER_SSH_KEY=<path to the .pem key> to $envFile (docs/lightsail-pilot.md, step 3)."
}
if (-not (Test-Path $keyFile)) { throw "SSH key not found: $keyFile (KC_SERVER_SSH_KEY in .env)" }
$keyFile = (Resolve-Path $keyFile).Path
$target = "ubuntu@$server"
$checkout = "/srv/kathachepta"
$sshOptions = @("-i", $keyFile, "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30")

function Invoke-Server([string]$remoteCommand) {
    & ssh @sshOptions $target $remoteCommand
    if ($LASTEXITCODE -ne 0) { throw "Server command failed (exit $LASTEXITCODE): $remoteCommand" }
}

function Test-Server {
    & ssh @sshOptions -o ConnectTimeout=15 $target "test -d $checkout/.git"
    if ($LASTEXITCODE -ne 0) {
        throw "Can't reach $target, or $checkout isn't there yet (first boot takes about 5 minutes; its log is " +
              "/var/log/cloud-init-output.log on the server). Check KC_SERVER_HOST and that port 22 is open."
    }
}

# rsync runs in a throwaway Linux container because Windows has none. --partial resumes interrupted copies;
# nothing on the server is ever deleted. The server's host key comes from the known_hosts that ssh just filled.
function Sync-ToServer([string]$label, [string]$localFolder, [string]$remoteFolder, [string]$owner) {
    if (-not (Test-Path $localFolder)) { Write-Warning "Skipping $label`: $localFolder doesn't exist."; return }
    $knownHosts = Join-Path $env:USERPROFILE ".ssh\known_hosts"
    Write-Host "== Copying $label to the server ($remoteFolder)"
    $ssh = "ssh -i /tmp/key -o UserKnownHostsFile=/known_hosts -o StrictHostKeyChecking=yes -o ServerAliveInterval=30"
    $copy = "apk add --no-cache rsync openssh-client >/dev/null && install -m 600 /key /tmp/key && " +
            "rsync -rtz --partial --info=stats1,progress2 --chmod=D755,F644 --chown=$owner " +
            "--rsync-path='sudo mkdir -p $remoteFolder && sudo rsync' -e '$ssh' /src/ ${target}:$remoteFolder/"
    & docker run --rm -v "${keyFile}:/key:ro" -v "${knownHosts}:/known_hosts:ro" -v "${localFolder}:/src:ro" `
        alpine:3.22 sh -c $copy
    if ($LASTEXITCODE -ne 0) { throw "Copying $label failed (exit $LASTEXITCODE). Re-run the same command: it resumes." }
}

function Sync-Media {
    Sync-ToServer "media" (Join-Path $root "data\media") "$checkout/data/media" "10001:10001"
    Sync-ToServer "seed recordings" (Join-Path $root "audio") "$checkout/audio" "1000:1000"
}

switch ($Command) {
    "status" {
        Test-Server
        Invoke-Server "cd $checkout && echo Deployed build: `$(cat data/release 2>/dev/null || echo none) && bash infra/lightsail/compose.sh ps && df -h / && free -m"
    }
    "deploy" {
        Test-Server
        $ref = if ($Argument) { $Argument } else { "origin/main" }
        Invoke-Server "cd $checkout && bash infra/lightsail/deploy.sh $ref"
    }
    "sync" {
        Test-Server
        Sync-Media
        Write-Host "Done. Re-run any time; only new and changed files are sent."
    }
    "logs" {
        Test-Server
        Invoke-Server "cd $checkout && bash infra/lightsail/compose.sh logs --no-color --tail 200 $Argument"
    }
    "ssh" {
        & ssh @sshOptions $target
    }
    "cutover" {
        Test-Server
        Invoke-Server "test -f $checkout/data/release || { echo 'Deploy the server first: scripts\lightsail.ps1 deploy' >&2; exit 1; }"
        Write-Host @"
Cutover moves the live data to $server :
  1. copies media now, while the desktop still serves (the slow part)
  2. stops the desktop API and media workers, so nothing changes after the copy
  3. copies the media added since, dumps the desktop database, and replaces the server's database with it
Stop the GPU worker window too. The server's current database is kept in data/backups first.
"@
        if ((Read-Host "Type CUTOVER to continue") -ne "CUTOVER") { throw "Cancelled." }

        Push-Location $root
        try {
            Sync-Media
            Write-Host "== Stopping the desktop API and media workers"
            docker compose stop api worker-media
            docker compose up -d postgres backup
            Sync-Media

            $dumpName = "kathachepta-cutover-$((Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')).dump"
            Write-Host "== Dumping the desktop database ($dumpName)"
            docker compose exec -T backup pg_dump -h postgres -U kathachepta -d kathachepta -Fc -f "/backups/$dumpName"
            if ($LASTEXITCODE -ne 0) { throw "pg_dump failed (exit $LASTEXITCODE). The desktop API is stopped; start it again with: docker compose start api worker-media" }
            & scp @sshOptions (Join-Path $root "data\backups\$dumpName") "${target}:/tmp/$dumpName"
            if ($LASTEXITCODE -ne 0) { throw "Copying the dump failed (exit $LASTEXITCODE). Re-run cutover; it is safe." }
            Invoke-Server "sudo install -m 644 /tmp/$dumpName $checkout/data/backups/$dumpName && rm /tmp/$dumpName && cd $checkout && bash infra/lightsail/restore.sh data/backups/$dumpName --yes"
        } finally {
            Pop-Location
        }
        $publicUrl = & ssh @sshOptions $target "grep -E '^KC_PUBLIC_BASE_URL=' $checkout/.env | cut -d= -f2-"
        Write-Host @"

Cutover done: the server at $publicUrl now holds the live data.
The desktop API stays stopped so nobody writes to the old copy. For development, start it again with
  docker compose start api worker-media   (it no longer holds live data)
Next: point the GPU worker at the server (docs/lightsail-pilot.md, step 7), then run the smoke test (step 8).
"@
    }
}
