#requires -Version 5.1
[CmdletBinding()]
param(
    [switch]$Redeploy,
    [switch]$BuildOnly,
    # Build a new version without changing the running image or stack.
    [string]$BuildImage,
    # Optional override; otherwise read the discovered existing Portainer stack.
    [string]$RemoteComposeFile,
    [switch]$CheckOnly,
    [switch]$PreflightOnly,
    [string]$ConfigFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
if (!$ConfigFile) { $ConfigFile = Join-Path $projectRoot 'deploy-nas.local.json' }
$files = @('app/main.py', 'app/static/index.html', 'app/storage.py',
    'app/upstream/__init__.py', 'app/upstream/tags.py', 'app/upstream/match.py',
    'app/upstream/net.py', 'app/upstream/search_lyrics.py', 'app/upstream/LICENSE', 'app/upstream/NOTICE.md',
    'app/search_service.py', 'app/upstream/search_itunes.py', 'app/upstream/search_mb.py',
    'app/upstream/search_acoustid.py', 'app/upstream/pipeline.py', 'app/job_service.py', 'app/preferences.py',
    'Dockerfile', 'requirements.txt', 'requirements.lock.txt', '.dockerignore')
$doRedeploy = !$BuildOnly
if ($Redeploy -and $BuildOnly) { throw 'Choose either -Redeploy or -BuildOnly.' }

function Read-DeployConfig {
    param([string]$Path)
    if (!(Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw 'Deployment config missing. Copy deploy-nas.example.json to deploy-nas.local.json and fill in your environment.'
    }
    try { $config = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { throw 'Deployment config is not valid JSON.' }
    if ($config -isnot [pscustomobject]) { throw 'Deployment config must be a JSON object.' }
    $required = @('NasTarget','SshKey','RemoteRoot','Image','Container','PortainerStackFile','WebBaseUrl')
    foreach ($name in $required) {
        if ($null -eq $config.PSObject.Properties[$name] -or $config.$name -isnot [string] -or [string]::IsNullOrWhiteSpace($config.$name)) {
            throw "Missing or invalid deployment config field: $name"
        }
        if ($config.$name -cne $config.$name.Trim()) { throw "Unexpected surrounding whitespace in config field: $name" }
    }
    foreach ($name in $config.PSObject.Properties.Name) {
        if ($name -notin ($required + @('MusicReadOnly'))) { throw "Unknown deployment config field: $name" }
    }
    if ($null -eq $config.PSObject.Properties['MusicReadOnly']) {
        $config | Add-Member -NotePropertyName MusicReadOnly -NotePropertyValue $true
    }
    if ($config.MusicReadOnly -isnot [bool]) { throw 'MusicReadOnly must be a JSON boolean.' }
    if ($config.NasTarget -notmatch '^[A-Za-z_][A-Za-z0-9_.-]*@[A-Za-z0-9][A-Za-z0-9.-]*$') {
        throw 'NasTarget must be a shell-safe user@host.'
    }
    foreach ($name in @('RemoteRoot','PortainerStackFile')) {
        if ($config.$name -notmatch '^/[A-Za-z0-9_./-]+$' -or $config.$name.Contains('..') -or $config.$name -match '(^|/)\.(/|$)') {
            throw "Deployment path must be absolute and shell-safe: $name"
        }
    }
    if ($config.Image -notmatch '^[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]*)?$' -or
        $config.Container -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') {
        throw 'Image/container must be shell-safe Docker names.'
    }
    $config.SshKey = [Environment]::ExpandEnvironmentVariables($config.SshKey)
    if (![IO.Path]::IsPathRooted($config.SshKey)) { throw 'SshKey must be an absolute local path.' }
    $uri = $null
    if (![Uri]::TryCreate($config.WebBaseUrl, [UriKind]::Absolute, [ref]$uri) -or
        $uri.Scheme -notin @('http','https') -or $uri.UserInfo -or $uri.Query -or $uri.Fragment) {
        throw 'WebBaseUrl must be an absolute HTTP(S) URL without credentials, query, or fragment.'
    }
    $config.WebBaseUrl = $config.WebBaseUrl.TrimEnd('/')
    return $config
}

function Invoke-NativeChecked {
    param([string]$Program, [string[]]$Arguments)
    $output = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed (exit $LASTEXITCODE). Stopped; no sudo or permission changes attempted."
    }
    return $output
}

function Invoke-Nas {
    param([string]$Command)
    Invoke-NativeChecked 'ssh' @('-i', $sshKey, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10', $nasTarget, $Command)
}

function Get-LocalHash {
    param([string]$Path)
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($Path)
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '').ToLowerInvariant() }
    finally { $stream.Dispose(); $sha.Dispose() }
}

function Get-Value {
    param($Object, [string]$Name, $Default = $null)
    if ($null -ne $Object -and $null -ne $Object.PSObject.Properties[$Name]) { return $Object.$Name }
    return $Default
}

function Assert-Same {
    param($Expected, $Actual, [string]$Name)
    if (($Expected | ConvertTo-Json -Depth 30 -Compress) -cne ($Actual | ConvertTo-Json -Depth 30 -Compress)) {
        throw "Configuration mismatch: $Name. Refusing deployment."
    }
}

function Assert-StackMatches {
    param($Definition, $Running, $ImageConfig)
    $service = Get-Value $Definition.services $container
    if ($null -eq $service) { throw 'Existing service is absent from the stack definition.' }
    # Fail closed when a new setting needs explicit preservation support.
    $supported = @('command','container_name','entrypoint','environment','image','networks','ports','restart','volumes')
    foreach ($name in $service.PSObject.Properties.Name) {
        if ($name -notin $supported) { throw "Unsupported Compose setting: $name. Review preservation before deployment." }
    }
    Assert-Same $image $service.image 'image tag'
    Assert-Same $container $service.container_name 'container name'
    foreach ($name in @('command','entrypoint')) {
        if ($null -ne (Get-Value $service $name)) { throw "Custom $name requires explicit preservation support." }
    }
    Assert-Same @($ImageConfig.Cmd) @($Running.Config.Cmd) 'image command'
    Assert-Same @(Get-Value $ImageConfig 'Entrypoint') @(Get-Value $Running.Config 'Entrypoint') 'image entrypoint'
    Assert-Same (Get-Value $ImageConfig 'User' '') (Get-Value $Running.Config 'User' '') 'image user'
    Assert-Same (Get-Value $ImageConfig 'WorkingDir' '') (Get-Value $Running.Config 'WorkingDir' '') 'image working directory'
    $environment = @{}
    foreach ($pair in $ImageConfig.Env) { $key, $value = $pair -split '=', 2; $environment[$key] = $value }
    foreach ($property in $service.environment.PSObject.Properties) { $environment[$property.Name] = [string]$property.Value }
    $expectedEnv = @($environment.Keys | Sort-Object | ForEach-Object { "$_=$($environment[$_])" })
    Assert-Same $expectedEnv @($Running.Config.Env | Sort-Object) 'environment'
    $mounts = @($service.volumes | ForEach-Object {
        if ($_.type -ne 'bind' -or $_.source -notmatch '^/') { throw 'Only existing absolute bind mounts are supported.' }
        if ((Get-Value $_ 'bind') -and @($_.bind.PSObject.Properties).Count) { throw 'Custom bind settings require review.' }
        "$($_.source)|$($_.target)|$(![bool](Get-Value $_ 'read_only' $false))"
    } | Sort-Object)
    $actualMounts = @($Running.Mounts | ForEach-Object {
        if ($_.Type -ne 'bind' -or $_.Propagation -ne 'rprivate') { throw 'Unexpected mount type or propagation.' }
        "$($_.Source)|$($_.Destination)|$($_.RW)"
    } | Sort-Object)
    Assert-Same $mounts $actualMounts 'volumes and read-only flags'
    $ports = @($service.ports | ForEach-Object {
        $hostIp = Get-Value $_ 'host_ip' ''
        "$($_.target)/$($_.protocol)|${hostIp}|$($_.published)"
    } | Sort-Object)
    $actualPorts = @($Running.HostConfig.PortBindings.PSObject.Properties | ForEach-Object {
        $port = $_.Name
        foreach ($binding in $_.Value) { "$port|$($binding.HostIp)|$($binding.HostPort)" }
    } | Sort-Object)
    Assert-Same $ports $actualPorts 'published ports'
    Assert-Same $service.restart $Running.HostConfig.RestartPolicy.Name 'restart policy'
    Assert-Same 0 $Running.HostConfig.RestartPolicy.MaximumRetryCount 'restart retries'
    Assert-Same @('default') @($service.networks.PSObject.Properties.Name) 'Compose networks'
    $networkName = $Definition.networks.default.name
    Assert-Same @($networkName) @($Running.NetworkSettings.Networks.PSObject.Properties.Name) 'attached networks'
    Assert-Same $networkName $Running.HostConfig.NetworkMode 'network mode'
    foreach ($name in @('Memory','NanoCpus','CpuShares','CpuQuota','MemoryReservation','MemorySwap')) {
        Assert-Same 0 $Running.HostConfig.$name $name
    }
    foreach ($name in @('Privileged','ReadonlyRootfs','AutoRemove','PublishAllPorts')) {
        Assert-Same $false $Running.HostConfig.$name $name
    }
    foreach ($name in @('CapAdd','CapDrop','Devices','DeviceRequests','SecurityOpt','Dns','DnsOptions','DnsSearch','ExtraHosts','GroupAdd','Ulimits')) {
        if (@(Get-Value $Running.HostConfig $name | Where-Object { $null -ne $_ }).Count) { throw "Custom host setting requires review: $name" }
    }
}

$deployConfig = Read-DeployConfig $ConfigFile
$nasTarget = $deployConfig.NasTarget
$sshKey = $deployConfig.SshKey
$remoteRoot = $deployConfig.RemoteRoot
$image = $deployConfig.Image
$buildImageTag = $image
if ($BuildImage) {
    if (!$BuildOnly -or $BuildImage -notmatch '^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9_][A-Za-z0-9_.-]*$' -or ($BuildImage -split ':')[0] -ne ($image -split ':')[0]) {
        throw 'BuildImage requires BuildOnly and a version tag in the same image repository.'
    }
    $buildImageTag = $BuildImage
}
$container = $deployConfig.Container
$portainerStackFile = $deployConfig.PortainerStackFile
$webBaseUrl = $deployConfig.WebBaseUrl
foreach ($program in @('git', 'ssh', 'scp')) { $null = Get-Command $program -ErrorAction Stop }
if (!(Test-Path -LiteralPath $sshKey -PathType Leaf)) { throw 'SSH key not found.' }
foreach ($file in $files) {
    if (!(Test-Path -LiteralPath (Join-Path $projectRoot $file) -PathType Leaf)) { throw "Missing source: $file" }
}
if ($RemoteComposeFile -and ($RemoteComposeFile -notmatch '^/[A-Za-z0-9_./-]+$' -or $RemoteComposeFile.Contains('..'))) {
    throw 'Compose override must be an absolute, shell-safe NAS path.'
}
Invoke-NativeChecked 'git' @('-C', $projectRoot, 'diff', '--check')
Invoke-NativeChecked 'git' (@('-C', $projectRoot, 'diff', '--stat', '--') + $files)
if ($CheckOnly) {
    Write-Host 'Local checks passed. No SSH connection, copy, build, or redeploy performed.'
    return
}

try {
    $before = (Invoke-Nas "docker inspect $container" | Out-String | ConvertFrom-Json)[0]
    $music = @($before.Mounts | Where-Object { $_.Destination -eq '/music' })
    if ($music.Count -ne 1 -or [bool]$music[0].RW -ne !$deployConfig.MusicReadOnly) {
        throw '/music mount mode differs from configured MusicReadOnly. Refusing deployment.'
    }
    if ($before.Config.Image -ne $image) { throw 'Unexpected existing image tag.' }
    if ($doRedeploy -or $PreflightOnly) {
        $labels = $before.Config.Labels
        if ($labels.'com.docker.compose.project' -ne $container -or $labels.'com.docker.compose.service' -ne $container) {
            throw 'Unexpected Compose project or service; refusing to recreate.'
        }
        if ($RemoteComposeFile) { $stackText = Invoke-Nas "cat '$RemoteComposeFile'" | Out-String }
        else { $stackText = Invoke-Nas "docker cp portainer:$portainerStackFile - | tar -xO" | Out-String }
        if ([string]::IsNullOrWhiteSpace($stackText)) { throw 'Unable to read the existing stack definition.' }
        $stackBase64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($stackText))
        $definition = Invoke-Nas "printf '%s' '$stackBase64' | base64 -d | docker compose -p $container -f - config --format json" | Out-String | ConvertFrom-Json
        $oldImageConfig = (Invoke-Nas "docker image inspect $($before.Image)" | Out-String | ConvertFrom-Json)[0].Config
        Assert-StackMatches $definition $before $oldImageConfig
        if ($PreflightOnly) { Write-Host 'NAS preflight passed. No files copied, image built, or container recreated.'; return }
        $snapshotPath = "$remoteRoot/deploy-backups/compose-$([Guid]::NewGuid().ToString('N')).yml"
        $compose = "docker compose -p $container -f '$snapshotPath'"
    }

    $changed = @()
    foreach ($file in $files) {
        $localHash = Get-LocalHash (Join-Path $projectRoot $file)
        $remoteHash = ((Invoke-Nas "if test -f '$remoteRoot/$file'; then sha256sum '$remoteRoot/$file'; elif test -e '$remoteRoot/$file'; then exit 1; else printf MISSING; fi" | Out-String).Trim() -split '\s+')[0]
        if ($localHash -ne $remoteHash) { $changed += $file }
    }
    if ($changed.Count) {
        $backup = "$remoteRoot/deploy-backups/$([DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss'))-$([Guid]::NewGuid().ToString('N').Substring(0,8))"
        Invoke-Nas "mkdir -p '$backup/app/static' '$backup/app/upstream' '$remoteRoot/app/upstream'"
        foreach ($file in $changed) { Invoke-Nas "if test -f '$remoteRoot/$file'; then cp -p '$remoteRoot/$file' '$backup/$file'; fi" }
        Write-Host "Original files backed up at $backup"
        foreach ($file in $changed) {
            Invoke-NativeChecked 'scp' @('-O', '-i', $sshKey, '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', (Join-Path $projectRoot $file), "${nasTarget}:$remoteRoot/$file")
            $remoteHash = ((Invoke-Nas "sha256sum '$remoteRoot/$file'" | Out-String).Trim() -split '\s+')[0]
            if ($remoteHash -ne (Get-LocalHash (Join-Path $projectRoot $file))) { throw "Upload hash mismatch: $file" }
        }
    }
    Invoke-Nas "cd '$remoteRoot' && docker build -t $buildImageTag ."
    if (!$doRedeploy) { Write-Host 'Image built. Container and stack unchanged.'; return }

    # Check new image defaults too: dependency/base-image updates must not alter settings silently.
    $newImageConfig = (Invoke-Nas "docker image inspect $image" | Out-String | ConvertFrom-Json)[0].Config
    Assert-StackMatches $definition $before $newImageConfig
    $latest = (Invoke-Nas "docker inspect $container" | Out-String | ConvertFrom-Json)[0]
    if ($latest.Id -ne $before.Id) { throw 'Container changed concurrently. Retry after reviewing the new state.' }
    Assert-StackMatches $definition $latest $newImageConfig
    # Snapshot only; the original Portainer stack is never edited.
    Invoke-Nas "umask 077; mkdir -p '$remoteRoot/deploy-backups' && printf '%s' '$stackBase64' | base64 -d > '$snapshotPath'"

    # No down, volume removal, orphan removal, dependency restart, sudo, or stack edits.
    Invoke-Nas "$compose up -d --no-deps --no-build --pull never --force-recreate $container"
    $after = (Invoke-Nas "docker inspect $container" | Out-String | ConvertFrom-Json)[0]
    Assert-Same @($before.Config.Env | Sort-Object) @($after.Config.Env | Sort-Object) 'post-deploy environment'
    foreach ($property in @('Cmd', 'Entrypoint', 'WorkingDir', 'User')) {
        if (((Get-Value $before.Config $property) | ConvertTo-Json -Compress -Depth 20) -ne ((Get-Value $after.Config $property) | ConvertTo-Json -Compress -Depth 20)) {
            throw "Post-deploy configuration mismatch: $property. Manual inspection required."
        }
    }
    foreach ($property in @('PortBindings', 'RestartPolicy', 'NetworkMode', 'Memory', 'NanoCpus', 'Privileged', 'ReadonlyRootfs')) {
        if (($before.HostConfig.$property | ConvertTo-Json -Compress -Depth 20) -ne ($after.HostConfig.$property | ConvertTo-Json -Compress -Depth 20)) {
            throw "Post-deploy host setting mismatch: $property. Manual inspection required."
        }
    }
    if (($before.Mounts | Sort-Object Destination | ConvertTo-Json -Compress -Depth 20) -ne ($after.Mounts | Sort-Object Destination | ConvertTo-Json -Compress -Depth 20)) {
        throw 'Post-deploy mount mismatch. Manual inspection required.'
    }
    if (!$after.State.Running) { throw 'Container is not running.' }
    $expectedImage = (Invoke-Nas "docker image inspect $image --format '{{.Id}}'" | Out-String).Trim()
    if ($after.Image -ne $expectedImage) { throw 'Container is not using the newly built image.' }
    $healthy = $false
    for ($attempt = 0; $attempt -lt 10; $attempt++) {
        try {
            $page = Invoke-WebRequest "$webBaseUrl/" -UseBasicParsing -TimeoutSec 10
            $folders = Invoke-RestMethod "$webBaseUrl/api/folders" -TimeoutSec 15
            if ($page.StatusCode -eq 200 -and $page.Content.Contains('<html') -and $null -ne $folders.folders) { $healthy = $true; break }
        } catch { Write-Verbose $_.Exception.Message }
        Start-Sleep -Seconds 2
    }
    if (!$healthy) { throw 'Web verification failed. Inspect the service container; no automatic rollback attempted.' }
    Write-Host 'Deployment complete: expected image, unchanged mounts/settings, HTTP and folder API verified.'
} catch {
    Write-Error "Deployment stopped: $($_.Exception.Message) Earlier completed steps are not automatically undone."
    exit 1
}
