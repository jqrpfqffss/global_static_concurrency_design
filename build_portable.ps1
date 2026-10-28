param(
    [string]$OutputDir = (Join-Path $PSScriptRoot 'dist'),
    [string]$CacheDir = (Join-Path $PSScriptRoot '.tools-cache'),
    [string]$PythonSource, [string]$CMakeSource, [string]$NinjaSource,
    [string]$MinGWSource, [string]$MinGWMakeSource, [string]$ArmGccSource,
    [string]$PipWheelSource, [string]$VcRuntimeSource, [switch]$SkipZip
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) { throw 'Windows x64 required.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
$sources = Import-PowerShellDataFile -Path (Join-Path $PSScriptRoot 'config/portable_sources.psd1')
. (Join-Path $PSScriptRoot 'scripts/portable_common.ps1')
$outputRoot = [IO.Path]::GetFullPath($OutputDir)
$cacheRoot = [IO.Path]::GetFullPath($CacheDir)
$separator = [IO.Path]::DirectorySeparatorChar
if ($outputRoot -eq $cacheRoot -or $outputRoot.StartsWith($cacheRoot.TrimEnd('\','/') + $separator, [StringComparison]::OrdinalIgnoreCase) -or
    $cacheRoot.StartsWith($outputRoot.TrimEnd('\','/') + $separator, [StringComparison]::OrdinalIgnoreCase)) { throw 'OutputDir/CacheDir must not overlap.' }
$bundle = Join-Path $outputRoot 'ECRA-Portable'
$zip = Join-Path $outputRoot 'ECRA-Portable.zip'
if ((Test-Path -LiteralPath $bundle) -or (Test-Path -LiteralPath $zip)) {
    throw "Output already exists; preserve its user configuration. Select a new -OutputDir or move the old bundle/ZIP: $outputRoot"
}
New-Item -ItemType Directory -Path $outputRoot, $cacheRoot -Force | Out-Null
$downloadRoot = Join-Path $cacheRoot 'downloads'
$wheelRoot = Join-Path $cacheRoot 'wheels'
New-Item -ItemType Directory -Path $downloadRoot, $wheelRoot -Force | Out-Null
$evidence = Join-Path $outputRoot 'portable-evidence'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$inventory = @(Get-LocalToolInventory)
$inventory | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'local-tools.json') -Encoding UTF8
function Select-LocalSource([string]$Explicit, [string]$Name) {
    if ($Explicit) { return $Explicit }
    $cacheName = switch ($Name) {
        'cmake.exe' { 'cmake-' + $sources.CMakeVersion }; 'ninja.exe' { 'ninja-' + $sources.NinjaVersion }
        'gcc.exe' { 'mingw-' + $sources.MinGWVersion + '-' + $sources.MinGWVariant }
        'arm-none-eabi-gcc.exe' { 'arm-gcc-10.3-2021.10' }; 'mingw32-make.exe' { 'make-' + $sources.MakeVersion }
    }
    if ($cacheName -and (Test-Path -LiteralPath (Join-Path $cacheRoot ($cacheName + '/.portable-receipt.json')))) { return '' }
    $match = @($inventory | Where-Object { $_.ContainsKey('name') -and $_.name -eq $Name -and $_.complete_and_matching })
    if ($match.Count) { return $match[0].root }
    return ''
}
try {
    $pythonBase = Resolve-Asset 'python' $PythonSource $sources.PythonArchive
    $vcBase = Resolve-Asset 'vc-runtime' $VcRuntimeSource $sources.VcRuntimeArchive
    $cmakeBase = Resolve-Asset 'cmake' (Select-LocalSource $CMakeSource 'cmake.exe') $sources.CMakeArchive
    $ninjaBase = Resolve-Asset 'ninja' (Select-LocalSource $NinjaSource 'ninja.exe') $sources.NinjaArchive
    $mingwBase = Resolve-Asset 'mingw' (Select-LocalSource $MinGWSource 'gcc.exe') $sources.MinGWArchive
    $armBase = Resolve-Asset 'arm-gcc' (Select-LocalSource $ArmGccSource 'arm-none-eabi-gcc.exe') $sources.ArmGccArchive
    $makeBase = $mingwBase
    if ($MinGWMakeSource) { $makeBase = Resolve-Asset 'make' $MinGWMakeSource $sources.MakeArchive }
    elseif (-not (Test-Asset 'make' $mingwBase)) {
        $makeBase = Resolve-Asset 'make' (Select-LocalSource '' 'mingw32-make.exe') $sources.MakeArchive
    }
    $null = Assert-Asset 'make' $makeBase
    New-Item -ItemType Directory -Path $bundle | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_ecra.py') -Destination $bundle
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'requirements.txt') -Destination $bundle
    $packageOut = Join-Path $bundle 'ecra'
    New-Item -ItemType Directory -Path $packageOut | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'ecra') -File -Filter '*.py') {
        Copy-Item -LiteralPath $file.FullName -Destination $packageOut
    }
    $configOut = Join-Path $bundle 'config'
    New-Item -ItemType Directory -Path $configOut | Out-Null
    foreach ($name in @('semantics.yaml', 'review_context.md', 'concurrency_cases.md')) {
        Copy-Item -LiteralPath (Join-Path (Join-Path $PSScriptRoot 'config') $name) -Destination $configOut
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'scripts/validate_portable.py') -Destination (Join-Path $bundle 'validate_portable.py')
    $runtime = Join-Path $bundle 'runtime'
    Copy-DirectoryContents $pythonBase $runtime
    $sitePackages = Join-Path $runtime 'Lib/site-packages'
    if (Test-Path -LiteralPath $sitePackages) { throw "Expected clean embeddable Python source; unexpected site-packages: $pythonBase" }
    New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $runtime 'python310._pth'), "python310.zip`r`n.`r`nLib\site-packages`r`n..`r`n", [Text.Encoding]::ASCII)
    $python = Join-Path $runtime 'python.exe'
    foreach ($name in @('msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')) {
        Copy-Item -LiteralPath (Join-Path $vcBase $name) -Destination $runtime -Force
    }
    $vcLicenceOut = Join-Path $runtime 'licenses/msvc'
    New-Item -ItemType Directory -Path $vcLicenceOut -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $vcBase 'LICENSE.rtf') -Destination $vcLicenceOut
    $pipWheel = Join-Path $downloadRoot $sources.PipWheel
    if ($PipWheelSource) {
        $pipWheel = (Resolve-Path -LiteralPath $PipWheelSource).Path
        if ([IO.Path]::GetFileName($pipWheel) -cne $sources.PipWheel) { throw "Expected $($sources.PipWheel): $pipWheel" }
    } else { Assert-Archive $pipWheel }
    [IO.Compression.ZipFile]::ExtractToDirectory($pipWheel, $sitePackages)
    foreach ($pattern in @('libclang-18.1.1-*-win_amd64.whl',"pyyaml-$($sources.PyYamlVersion)-cp310-cp310-win_amd64.whl")) {
        $wheels = @(Get-ChildItem -LiteralPath $wheelRoot -Filter $pattern -File)
        if ($wheels.Count -ne 1) { throw "Missing compatible wheel: $pattern in $wheelRoot" }
        Assert-Archive $wheels[0].FullName
    }
    $pipText = Invoke-Checked 'pip version' $python @('-m','pip','--version')
    if ($pipText -notmatch ('^pip ' + [regex]::Escape($sources.PipVersion) + ' ')) { throw "pip version mismatch: $pipText" }
    $constraints = Join-Path $bundle 'requirements-portable.lock.txt'
    [IO.File]::WriteAllText($constraints, "libclang==$($sources.LibClangVersion)`r`nPyYAML==$($sources.PyYamlVersion)`r`n", [Text.Encoding]::ASCII)
    $null = Invoke-Checked 'Install local compatible Windows wheels' $python @('-m','pip','--disable-pip-version-check','install',
        '--no-index','--find-links',$wheelRoot,'--only-binary',':all:','--no-compile','--target',$sitePackages,
        '-r',(Join-Path $bundle 'requirements.txt'),'-c',$constraints)
    $null = Invoke-Checked 'Dependency consistency' $python @('-m','pip','check')
    $toolsDir = Join-Path $bundle 'tools'
    New-Item -ItemType Directory -Path $toolsDir | Out-Null
    Copy-DirectoryContents $cmakeBase (Join-Path $toolsDir 'cmake')
    Copy-DirectoryContents $ninjaBase (Join-Path $toolsDir 'ninja')
    $ninjaLicense = Join-Path $downloadRoot $sources.NinjaLicenseArchive
    Assert-Archive $ninjaLicense
    Copy-Item -LiteralPath $ninjaLicense -Destination (Join-Path $toolsDir 'ninja/COPYING.txt')
    Copy-DirectoryContents $mingwBase (Join-Path $toolsDir 'mingw')
    Copy-DirectoryContents $armBase (Join-Path $toolsDir 'arm-gcc')
    # The upstream Python-enabled debugger requires a separately installed
    # 32-bit Python 2.7. It is not a compiler component. Keep the standard GDB
    # and the complete compiler/binutils/libraries; do not ship a broken optional
    # executable or silently depend on the developer PC's Python 2 installation.
    $omitted = @()
    foreach ($name in @('arm-none-eabi-gdb-py.exe','arm-none-eabi-gdb-add-index-py')) {
        $optional = Join-Path $toolsDir ('arm-gcc/bin/' + $name)
        if (Test-Path -LiteralPath $optional) { Remove-OutputChild $bundle $optional; $omitted += $name }
    }
    if ($makeBase -ne $mingwBase) {
        Copy-DirectoryContents $makeBase (Join-Path $toolsDir 'make-source')
        foreach ($f in Get-ChildItem -LiteralPath (Join-Path $makeBase 'bin') -File) {
            $dest = Join-Path $toolsDir ('mingw/bin/' + $f.Name)
            if ((Test-Path -LiteralPath $dest) -and (Get-FileHash -LiteralPath $dest).Hash -ne (Get-FileHash -LiteralPath $f.FullName).Hash) {
                throw "Make runtime conflicts with MinGW: $dest vs $($f.FullName)"
            }
            Copy-Item -LiteralPath $f.FullName -Destination $dest -Force
        }
    }
    $makeSourceSha = (Get-FileHash -LiteralPath (Join-Path $makeBase 'bin/mingw32-make.exe')).Hash
    $makeReport = Join-Path $toolsDir 'mingw/make-utf8.json'
    $makeRecipe = Join-Path $toolsDir 'mingw/portable-make-utf8.py'
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'scripts/enable_make_utf8.py') -Destination $makeRecipe
    $null = Invoke-Checked 'Enable Make per-process UTF-8 manifest; preserve all code sections' $python @('-B',$makeRecipe,
        '--make',(Join-Path $toolsDir 'mingw/bin/mingw32-make.exe'),'--report',$makeReport,'--expected-source-sha256',$makeSourceSha)
    $makeAdapter = Get-Content -LiteralPath $makeReport -Raw | ConvertFrom-Json
    $patterns = @{
        cmake=('(?m)^cmake version ' + [regex]::Escape($sources.CMakeVersion) + '(\s|$)')
        ninja=('\A' + [regex]::Escape($sources.NinjaVersion) + '\Z')
        gcc=('(?i)^gcc\.exe \(' + [regex]::Escape($sources.MinGWVariant) + ', Built by MinGW-Builds project\) ' + [regex]::Escape($sources.MinGWVersion) + '(\s|$)')
        'g++'= ('(?i)^g\+\+\.exe \(' + [regex]::Escape($sources.MinGWVariant) + ', Built by MinGW-Builds project\) ' + [regex]::Escape($sources.MinGWVersion) + '(\s|$)')
        'mingw32-make'=('(?m)^GNU Make ' + [regex]::Escape($sources.MakeVersion) + '\nBuilt for ' + $sources.MakePlatform)
        'arm-none-eabi-gcc'=([regex]::Escape($sources.ArmGccRelease) + '\) ' + [regex]::Escape($sources.ArmGccVersion) + ' 20210824 \(release\)')
    }
    $actualVersions = @{}
    foreach ($entry in @(@('python',$runtime),@('cmake',(Join-Path $toolsDir 'cmake')),@('ninja',(Join-Path $toolsDir 'ninja')),
            @('mingw',(Join-Path $toolsDir 'mingw')),@('make',(Join-Path $toolsDir 'mingw')),@('arm-gcc',(Join-Path $toolsDir 'arm-gcc')))) {
        $actualVersions[$entry[0]] = ((Assert-Asset $entry[0] $entry[1]) -split "`n")[0]
    }
    $lock = @{ versions=@{python=$sources.PythonVersion;cmake=$sources.CMakeVersion;ninja=$sources.NinjaVersion;
            mingw=$sources.MinGWVersion;make=$sources.MakeVersion;arm=$sources.ArmGccVersion};
        version_patterns=$patterns; dependencies=@{libclang=$sources.LibClangVersion;PyYAML=$sources.PyYamlVersion};
        sources=@{python=$pythonBase;cmake=$cmakeBase;ninja=$ninjaBase;mingw=$mingwBase;make=$makeBase;arm=$armBase;vc_runtime=$vcBase}; actual_versions=$actualVersions;
        vc_runtime_version=$sources.VcRuntimeVersion;
        make_adapter=$makeAdapter;
        omitted_optional_components=$omitted;
        cmake_distribution_note='Official Kitware 3.29.6 differs from JetBrains IDE bundle build 1; check actual version below.' }
    $lock | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $bundle 'portable-lock.json') -Encoding UTF8
    $launcher = @'
@echo off
setlocal DisableDelayedExpansion
set "ECRA_ROOT=%~dp0"
set "ECRA_PORTABLE_ROOT=%~dp0"
set "ECRA_CONFIG_HOME=%ECRA_ROOT%config"
set "PATH=%ECRA_ROOT%runtime;%ECRA_ROOT%tools\cmake\bin;%ECRA_ROOT%tools\ninja;%ECRA_ROOT%tools\mingw\bin;%ECRA_ROOT%tools\mingw\opt\bin;%ECRA_ROOT%tools\arm-gcc\bin;%PATH%"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONDONTWRITEBYTECODE=1"
"%ECRA_ROOT%runtime\python.exe" -B "%ECRA_ROOT%run_ecra.py" %*
exit /b %ERRORLEVEL%
'@
    [IO.File]::WriteAllText((Join-Path $bundle 'ecra.cmd'), $launcher.Replace("`r`n","`n").Replace("`n","`r`n") + "`r`n", [Text.Encoding]::ASCII)
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'docs/portable-usage.txt') -Destination (Join-Path $bundle 'README.txt')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'docs/manual-review.md') -Destination (Join-Path $bundle 'manual-review.md')
    $commit = 'unknown (source archive or Git unavailable)'
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($git -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.git'))) {
        try { $commit = Invoke-Checked 'Git source revision' $git.Source @('-C',$PSScriptRoot,'rev-parse','HEAD') }
        catch { $commit = 'unknown (Git could not resolve revision)' }
    }
    $pyproject = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'pyproject.toml') -Raw
    $version = [regex]::Match($pyproject, '(?m)^version\s*=\s*"([^"]+)"').Groups[1].Value
    [IO.File]::WriteAllText((Join-Path $bundle 'VERSION.txt'), "ECRA: $version`r`nGit: $commit`r`nUTC: $([datetime]::UtcNow.ToString('o'))`r`n" +
        ($lock | ConvertTo-Json -Depth 8), [Text.Encoding]::UTF8)
    foreach ($dir in @(Get-ChildItem -LiteralPath $bundle -Recurse -Directory -Filter '__pycache__' | Sort-Object { $_.FullName.Length } -Descending)) {
        Remove-OutputChild $bundle $dir.FullName
    }
    $null = Invoke-Checked 'Inventory all deliverable files' $python @('-B',(Join-Path $bundle 'validate_portable.py'),'--bundle',$bundle,'--write-hashes')
    $null = Invoke-Checked 'Uncompressed isolated acceptance' $python @('-B',(Join-Path $bundle 'validate_portable.py'),
        '--bundle',$bundle,'--work',(Join-Path $evidence 'uncompressed'))
    if (-not $SkipZip) {
        $candidate = Join-Path $outputRoot 'ECRA-Portable.candidate.zip'
        if (Test-Path -LiteralPath $candidate) { throw "Previous failed candidate exists: $candidate" }
        [IO.Compression.ZipFile]::CreateFromDirectory($bundle,$candidate,[IO.Compression.CompressionLevel]::Optimal,$true)
        $zipCheck = Join-Path $outputRoot ('.zip-check 空格 中文-' + [guid]::NewGuid().ToString('N'))
        try {
            [IO.Compression.ZipFile]::ExtractToDirectory($candidate,$zipCheck)
            $top = @(Get-ChildItem -LiteralPath $zipCheck -Force)
            if ($top.Count -ne 1 -or $top[0].Name -cne 'ECRA-Portable' -or -not $top[0].PSIsContainer) {
                throw "Invalid ZIP root structure: $candidate"
            }
            $extracted = Join-Path $zipCheck 'ECRA-Portable'
            # 'config/concurrency_cases.md' is verified by the full file manifest.
            $null = Invoke-Checked 'ZIP extracted isolated acceptance' (Join-Path $extracted 'runtime/python.exe') @('-B',
                (Join-Path $extracted 'validate_portable.py'),'--bundle',$extracted,'--work',(Join-Path $evidence 'zip-extracted'))
            Move-Item -LiteralPath $candidate -Destination $zip
            Write-Receipt $zip 'ECRA build; full extracted isolated acceptance passed'
        } finally { Remove-OutputChild $outputRoot $zipCheck }
    }
    Write-Host "Portable acceptance passed: $bundle"
    if (-not $SkipZip) { Write-Host "ZIP: $zip"; Get-FileHash -LiteralPath $zip -Algorithm SHA256 | Format-List }
} catch {
    $message = "Portable build FAILED: $_"
    $message | Set-Content -LiteralPath (Join-Path $evidence 'failure.txt') -Encoding UTF8
    Write-Host $message -ForegroundColor Red
    throw
}
