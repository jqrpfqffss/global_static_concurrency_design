param(
    [string]$CacheDir = (Join-Path $PSScriptRoot '.tools-cache'),
    [string]$PythonSource, [string]$CMakeSource, [string]$NinjaSource,
    [string]$MinGWSource, [string]$MinGWMakeSource, [string]$ArmGccSource,
    [string]$VcRuntimeSource,
    [switch]$ForceArchives, [switch]$OfflineCheck
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 required.' }
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Add-Type -AssemblyName System.IO.Compression.FileSystem
$sources = Import-PowerShellDataFile -Path (Join-Path $PSScriptRoot 'config/portable_sources.psd1')
. (Join-Path $PSScriptRoot 'scripts/portable_common.ps1')
$cacheRoot = [IO.Path]::GetFullPath($CacheDir)
$downloadRoot = Join-Path $cacheRoot 'downloads'
$wheelRoot = Join-Path $cacheRoot 'wheels'
New-Item -ItemType Directory -Path $downloadRoot,$wheelRoot -Force | Out-Null

function Get-Download([string]$Name, [string]$Url, [string]$Expected = '') {
    $file = Join-Path $downloadRoot $Name
    if (Test-Path -LiteralPath $file) {
        if (-not $Expected -and -not (Test-Path -LiteralPath ($file + '.receipt.json'))) {
            if ($OfflineCheck) { throw "Missing SHA256 receipt: $file. Verify/import online first." }
            # Never create a receipt for an unverified preexisting download.
            throw "Unverified existing download: $file. Move it aside, then prepare again (or import explicitly via -...Source)."
        }
        Assert-Archive $file $Expected
        if ($Expected -and -not (Test-Path -LiteralPath ($file + '.receipt.json'))) { Write-Receipt $file $Url }
        return $file
    }
    if ($OfflineCheck) { throw "Offline asset missing: $file" }
    $partial = $file + '.part'
    Assert-ChildPath $cacheRoot $partial
    try {
        Save-RemoteFile $Url $partial
        if ((Get-Item -LiteralPath $partial).Length -eq 0) { throw "Empty download: $Url" }
        if ($Expected -and (Get-FileHash -LiteralPath $partial).Hash -ine $Expected) { throw "Publisher SHA256 mismatch: $Url" }
        Move-Item -LiteralPath $partial -Destination $file
        Write-Receipt $file $Url
        return $file
    } finally { Remove-OutputChild $cacheRoot $partial }
}

$inventory = @(Get-LocalToolInventory)
$inventory | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $cacheRoot 'local-tools.json') -Encoding UTF8
$resolved = @{}
$errors = @()
$assets = @(
    @('python',$PythonSource,$sources.PythonArchive,$sources.PythonUrl,'python.exe'),
    @('vc-runtime',$VcRuntimeSource,$sources.VcRuntimeArchive,$sources.VcRuntimeUrl,'vc-runtime'),
    @('cmake',$CMakeSource,$sources.CMakeArchive,$sources.CMakeUrl,'cmake.exe'),
    @('ninja',$NinjaSource,$sources.NinjaArchive,$sources.NinjaUrl,'ninja.exe'),
    @('mingw',$MinGWSource,$sources.MinGWArchive,$sources.MinGWUrl,'gcc.exe'),
    @('arm-gcc',$ArmGccSource,$sources.ArmGccArchive,$sources.ArmGccUrl,'arm-none-eabi-gcc.exe'))
foreach ($asset in $assets) {
    $kind,$source,$archive,$url,$command = $asset
    try {
        if (-not $source -and -not $OfflineCheck) {
            $found = @($inventory | Where-Object { $_.ContainsKey('name') -and $_.name -eq $command -and $_.complete_and_matching })
            if ($found.Count -and $kind -ne 'python') { $source = $found[0].root }
        }
        if (-not $source) {
            # Reuse only complete, version-scoped, hash-verified offline caches.
            try { $resolved[$kind] = Resolve-Asset $kind '' $archive; if (-not $ForceArchives) { continue } }
            catch { if ($OfflineCheck) { throw } }
            $expected = if ($sources.Sha256.ContainsKey($archive)) { $sources.Sha256[$archive] } else { '' }
            if ($kind -eq 'cmake' -and -not $OfflineCheck) {
                $checksums = Get-RemoteText $sources.CMakeChecksumUrl
                $line = @($checksums -split "`n" | Where-Object { $_ -match ([regex]::Escape($archive) + '$') })
                if ($line.Count -ne 1) { throw "CMake publisher checksum missing: $archive" }
                $expected = ($line[0] -split '\s+')[0]
            }
            $null = Get-Download $archive $url $expected
        }
        $resolved[$kind] = Resolve-Asset $kind $source $archive
    } catch { $errors += "$kind : $_"; Write-Warning $errors[-1] }
}
try {
    if ($MinGWMakeSource) { $resolved['make'] = Resolve-Asset 'make' $MinGWMakeSource $sources.MakeArchive }
    elseif ($resolved.ContainsKey('mingw') -and (Test-Asset 'make' $resolved['mingw'])) {
        $null = Assert-Asset 'make' $resolved['mingw']; $resolved['make'] = $resolved['mingw']
    } else {
        $found = @($inventory | Where-Object { $_.ContainsKey('name') -and $_.name -eq 'mingw32-make.exe' -and $_.complete_and_matching })
        $source = if ($found.Count) { $found[0].root } else { '' }
        $resolved['make'] = Resolve-Asset 'make' $source $sources.MakeArchive
    }
} catch { $errors += "make : $_"; Write-Warning $errors[-1] }

try {
    $null = Get-Download $sources.NinjaLicenseArchive $sources.NinjaLicenseUrl
    $pipWheel = Join-Path $downloadRoot $sources.PipWheel
    if (-not $OfflineCheck) {
        $metadata = Get-RemoteText $sources.PipMetadataUrl | ConvertFrom-Json
        $wheel = @($metadata.urls | Where-Object { $_.filename -eq $sources.PipWheel })[0]
        $pipWheel = Get-Download $sources.PipWheel $wheel.url $wheel.digests.sha256
    } else { Assert-Archive $pipWheel }
    if (-not $resolved.ContainsKey('python')) { throw 'Cannot verify Python wheels until Python 3.10.9 is available.' }
    $stage = Join-Path $cacheRoot ('.prepare-python-' + [guid]::NewGuid().ToString('N'))
    try {
        Copy-DirectoryContents $resolved['python'] $stage
        $site = Join-Path $stage 'Lib/site-packages'
        New-Item -ItemType Directory -Path $site -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $stage 'python310._pth'), "python310.zip`r`n.`r`nLib\site-packages`r`n", [Text.Encoding]::ASCII)
        [IO.Compression.ZipFile]::ExtractToDirectory($pipWheel,$site)
        $python = Join-Path $stage 'python.exe'
        $pipArgs = @('-m','pip','--disable-pip-version-check','download','--only-binary',':all:','--dest',$wheelRoot,
            "libclang==$($sources.LibClangVersion)","PyYAML==$($sources.PyYamlVersion)")
        foreach ($pattern in @('libclang-18.1.1-*-win_amd64.whl',"pyyaml-$($sources.PyYamlVersion)-cp310-cp310-win_amd64.whl")) {
            $wheels = @(Get-ChildItem -LiteralPath $wheelRoot -Filter $pattern -File)
            if (-not $OfflineCheck) {
                $package = if ($pattern.StartsWith('libclang')) { 'libclang' } else { 'PyYAML' }
                $pin = if ($package -eq 'libclang') { $sources.LibClangVersion } else { $sources.PyYamlVersion }
                $meta = Get-RemoteText "https://pypi.org/pypi/$package/$pin/json" | ConvertFrom-Json
                $entry = @($meta.urls | Where-Object { $_.filename -like $pattern })
                if ($entry.Count -ne 1) { throw "PyPI wheel missing or ambiguous: $pattern" }
                $file = Join-Path $wheelRoot $entry[0].filename
                if (-not (Test-Path -LiteralPath $file)) { Save-RemoteFile $entry[0].url $file }
                if ((Get-FileHash -LiteralPath $file).Hash -ine $entry[0].digests.sha256) { throw "PyPI wheel SHA256 mismatch: $file" }
                Write-Receipt $file $entry[0].url
            } else {
                if ($wheels.Count -ne 1) { throw "Expected one compatible wheel: $pattern" }
                Assert-Archive $wheels[0].FullName
            }
        }
        $pipArgs += @('--no-index','--find-links',$wheelRoot)
        $null = Invoke-Checked 'Python 3.10 compatible wheels' $python $pipArgs
        $studioArgs = @('-B',(Join-Path $PSScriptRoot 'scripts/prepare_studio_wheels.py'),'--cache',$cacheRoot)
        if ($OfflineCheck) { $studioArgs += '--offline' }
        $null = Invoke-Checked 'Studio Python 3.10 wheel hashes and licenses' $python $studioArgs
    } finally { if ($stage) { Remove-OutputChild $cacheRoot $stage } }
} catch { $errors += "Python dependencies : $_"; Write-Warning $errors[-1] }
$summary = @{ resolved=$resolved; errors=$errors; offline=[bool]$OfflineCheck; utc=[datetime]::UtcNow.ToString('o') }
$summary | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $cacheRoot 'preparation-result.json') -Encoding UTF8
if ($errors.Count) { throw ("Portable cache NOT ready:`n" + ($errors -join "`n")) }
Write-Host "Verified Portable cache ready: $cacheRoot"
