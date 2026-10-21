# Local safety tests. No SSH, Docker, or deployment commands are executed.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$scriptPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'deploy-nas.ps1'
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($scriptPath, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw 'Deployment script syntax errors.' }
foreach ($name in @('Read-DeployConfig', 'Get-Value', 'Assert-Same', 'Assert-StackMatches')) {
    $functionAst = $ast.Find({ param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    . ([scriptblock]::Create($functionAst.Extent.Text))
}
$image = 'music-tag-filler-nas:v6'
$container = 'music-tag-filler-v6'
function New-Fixture {
    $definition = @'
{"networks":{"default":{"name":"music-tag-filler-v6_default"}},"services":{"music-tag-filler-v6":{"image":"music-tag-filler-nas:v6","container_name":"music-tag-filler-v6","command":null,"entrypoint":null,"environment":{"MUSIC_ROOT":"/music"},"networks":{"default":null},"ports":[{"target":8000,"published":"8000","protocol":"tcp"}],"restart":"unless-stopped","volumes":[{"type":"bind","source":"/library","target":"/music","read_only":true,"bind":{}},{"type":"bind","source":"/state","target":"/data","bind":{}}]}}}
'@ | ConvertFrom-Json
    $running = @'
{"Config":{"Cmd":["uvicorn"],"Entrypoint":null,"User":"","WorkingDir":"/app","Env":["PATH=/usr/bin","MUSIC_ROOT=/music"]},"Mounts":[{"Type":"bind","Source":"/library","Destination":"/music","RW":false,"Propagation":"rprivate"},{"Type":"bind","Source":"/state","Destination":"/data","RW":true,"Propagation":"rprivate"}],"HostConfig":{"PortBindings":{"8000/tcp":[{"HostIp":"","HostPort":"8000"}]},"RestartPolicy":{"Name":"unless-stopped","MaximumRetryCount":0},"NetworkMode":"music-tag-filler-v6_default","Memory":0,"NanoCpus":0,"CpuShares":0,"CpuQuota":0,"MemoryReservation":0,"MemorySwap":0,"Privileged":false,"ReadonlyRootfs":false,"AutoRemove":false,"PublishAllPorts":false},"NetworkSettings":{"Networks":{"music-tag-filler-v6_default":{}}}}
'@ | ConvertFrom-Json
    # Optional fields omitted by Docker image inspect must be supported.
    $imageConfig = '{"Cmd":["uvicorn"],"WorkingDir":"/app","Env":["PATH=/usr/bin"]}' | ConvertFrom-Json
    return @{ Definition = $definition; Running = $running; ImageConfig = $imageConfig }
}
function Check-Fixture {
    param($Fixture)
    Assert-StackMatches $Fixture.Definition $Fixture.Running $Fixture.ImageConfig
}
Check-Fixture (New-Fixture)
$writable = New-Fixture
$writable.Definition.services.'music-tag-filler-v6'.volumes[0].read_only = $false
$writable.Running.Mounts[0].RW = $true
Check-Fixture $writable
$cases = @(
    @{ Name = 'writable music'; Mutate = { param($f) $f.Definition.services.'music-tag-filler-v6'.volumes[0].read_only = $false } },
    @{ Name = 'changed environment'; Mutate = { param($f) $f.Definition.services.'music-tag-filler-v6'.environment.MUSIC_ROOT = '/other' } },
    @{ Name = 'changed port'; Mutate = { param($f) $f.Definition.services.'music-tag-filler-v6'.ports[0].published = '9000' } },
    @{ Name = 'changed volume'; Mutate = { param($f) $f.Definition.services.'music-tag-filler-v6'.volumes[1].source = '/other' } },
    @{ Name = 'privileged container'; Mutate = { param($f) $f.Running.HostConfig.Privileged = $true } },
    @{ Name = 'new image default'; Mutate = { param($f) $f.ImageConfig.Env = @('PATH=/changed') } },
    @{ Name = 'unknown Compose option'; Mutate = { param($f) $f.Definition.services.'music-tag-filler-v6' | Add-Member -NotePropertyName 'privileged' -NotePropertyValue $true } }
)
foreach ($case in $cases) {
    $fixture = New-Fixture
    & $case.Mutate $fixture
    $rejected = $false
    try { Check-Fixture $fixture } catch { $rejected = $true }
    if (!$rejected) { throw "Unsafe configuration accepted: $($case.Name)" }
}
Write-Host 'PASS: valid configuration and omitted optional fields; seven unsafe configuration changes rejected.'

# JSON config is data, not executable code; never use real NAS credentials here.
$fixturePath = Join-Path ([IO.Path]::GetTempPath()) ('deploy-config-test-' + [Guid]::NewGuid().ToString('N') + '.json')
function New-ConfigFixture {
    $value = Get-Content -LiteralPath (Join-Path (Split-Path $PSScriptRoot -Parent) 'deploy-nas.example.json') -Raw | ConvertFrom-Json
    $value.SshKey = Join-Path ([IO.Path]::GetTempPath()) 'fixture-nas-key'
    return $value
}
try {
    New-ConfigFixture | ConvertTo-Json | Set-Content -LiteralPath $fixturePath -Encoding UTF8
    $actual = Read-DeployConfig $fixturePath
    if ($actual.NasTarget -ne 'nas_user@nas.example.invalid') { throw 'Valid config not preserved.' }
    if ($actual.MusicReadOnly -ne $false) { throw 'Explicit writable mode not preserved.' }
    $legacy = New-ConfigFixture
    $legacy.PSObject.Properties.Remove('MusicReadOnly')
    $legacy | ConvertTo-Json | Set-Content -LiteralPath $fixturePath -Encoding UTF8
    if ((Read-DeployConfig $fixturePath).MusicReadOnly -ne $true) { throw 'Legacy config must default to read-only.' }
    $mutations = @(
        { param($c) $c.NasTarget = 'user@host; touch /tmp/unsafe' },
        { param($c) $c.RemoteRoot = "/srv/path'; touch /tmp/unsafe; '" },
        { param($c) $c.RemoteRoot = '/srv/../other' },
        { param($c) $c.RemoteRoot = '/./' },
        { param($c) $c.PortainerStackFile = '/data/compose/$(id).yml' },
        { param($c) $c.Image = 'image;id' },
        { param($c) $c.Container = '-unexpected-option' },
        { param($c) $c.WebBaseUrl = 'https://user:password@example.invalid' },
        { param($c) $c.WebBaseUrl = 'http://example.invalid/?token=fixture' },
        { param($c) $c.SshKey = 'relative-key' },
        { param($c) $c.NasTarget = "nas_user@host`n" },
        { param($c) $c.PSObject.Properties.Remove('RemoteRoot') },
        { param($c) $c | Add-Member -NotePropertyName 'Password' -NotePropertyValue 'fixture' }
    )
    foreach ($mutate in $mutations) {
        $value = New-ConfigFixture
        & $mutate $value
        $value | ConvertTo-Json | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        $rejected = $false
        try { $null = Read-DeployConfig $fixturePath } catch { $rejected = $true }
        if (!$rejected) { throw 'Unsafe/invalid deployment JSON accepted.' }
    }
    foreach ($raw in @('not json', '[]', 'null')) {
        [IO.File]::WriteAllText($fixturePath, $raw)
        $rejected = $false
        try { $null = Read-DeployConfig $fixturePath } catch { $rejected = $true }
        if (!$rejected) { throw 'Malformed config accepted.' }
    }
    foreach ($badMode in @('false', 0, $null)) {
        $value = New-ConfigFixture
        $value.MusicReadOnly = $badMode
        $value | ConvertTo-Json | Set-Content -LiteralPath $fixturePath -Encoding UTF8
        $rejected = $false
        try { $null = Read-DeployConfig $fixturePath } catch { $rejected = $true }
        if (!$rejected) { throw 'Non-boolean music mount mode accepted.' }
    }
    Write-Host 'PASS: matched writable mounts accepted; legacy mode defaults to read-only; three invalid mount modes rejected.'
    Write-Host 'PASS: example JSON accepted; 16 unsafe/malformed configuration cases rejected.'
} finally {
    Remove-Item -LiteralPath $fixturePath -ErrorAction SilentlyContinue
}
