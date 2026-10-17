param(
    [string]$CacheDir = (Join-Path $PSScriptRoot '.tools-cache'),
    [switch]$ForceArchives,
    [switch]$OfflineCheck
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw '此脚本需要 64 位 Windows。'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$sources = Import-PowerShellDataFile -Path (Join-Path $PSScriptRoot 'config/portable_sources.psd1')
$cacheRoot = [IO.Path]::GetFullPath($CacheDir)
$downloadRoot = Join-Path $cacheRoot 'downloads'
$wheelRoot = Join-Path $cacheRoot 'wheels'
New-Item -ItemType Directory -Path $downloadRoot, $wheelRoot -Force | Out-Null
$pythonTag = (($sources.PythonVersion -split '\.')[0..1] -join '')
$pythonZip = "python$pythonTag.zip"
$pythonPth = "python$pythonTag._pth"

function Assert-CacheChild([string]$Path) {
    $parent = $cacheRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not [IO.Path]::GetFullPath($Path).StartsWith($parent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝清理缓存之外的路径: $Path"
    }
}

function Test-PinnedArmGcc([string]$Root) {
    $compiler = Join-Path $Root 'bin/arm-none-eabi-gcc.exe'
    if (-not (Test-Path -LiteralPath $compiler)) { return $false }
    try {
        $firstLine = & $compiler --version 2>&1 | Select-Object -First 1
        return ($LASTEXITCODE -eq 0 -and
                $firstLine -match ('\b' + [regex]::Escape($sources.ArmGccVersion) + '\b'))
    } catch { return $false }
}

function Test-ExtractedAsset([string]$Kind) {
    $root = Join-Path $cacheRoot $Kind
    switch ($Kind) {
        'python' { return ((Test-Path (Join-Path $root 'python.exe')) -and
                           (Test-Path (Join-Path $root $pythonZip)) -and
                           (Test-Path (Join-Path $root $pythonPth))) }
        'cmake' { return ((Test-Path (Join-Path $root 'bin/cmake.exe')) -and
                          (Test-Path (Join-Path $root 'share'))) }
        'ninja' { return (Test-Path (Join-Path $root 'ninja.exe')) }
        'arm-gcc' { return ((Test-Path (Join-Path $root 'bin/arm-none-eabi-gcc.exe')) -and
                            (Test-Path (Join-Path $root 'bin/arm-none-eabi-g++.exe')) -and
                            (Test-Path (Join-Path $root 'bin/arm-none-eabi-ar.exe')) -and
                            (Test-Path (Join-Path $root 'lib')) -and
                            (Test-Path (Join-Path $root 'arm-none-eabi')) -and
                            (Test-PinnedArmGcc $root)) }
    }
    throw "未知工具: $Kind"
}

function Get-Archive([string]$Kind, [string]$Name, [string]$Url) {
    $path = Join-Path $downloadRoot $Name
    if (Test-Path -LiteralPath $path) {
        Write-Host "已有本地归档: $path"
        return $path
    }
    if (-not $ForceArchives -and (Test-ExtractedAsset $Kind)) {
        Write-Host "已有完整解压缓存: $(Join-Path $cacheRoot $Kind)"
        return $null
    }
    if ($OfflineCheck) { throw "缺少 $Kind 本地归档或完整解压缓存: $path" }
    $partial = "$path.part"
    Assert-CacheChild $partial
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
    Write-Host "下载 $Kind : $Url"
    try {
        Invoke-WebRequest -Uri $Url -OutFile $partial -UseBasicParsing -TimeoutSec 1800
        if ((Get-Item -LiteralPath $partial).Length -eq 0) { throw '下载文件为空' }
        Move-Item -LiteralPath $partial -Destination $path
    } catch {
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
        throw "$Kind 下载失败: $_"
    }
    return $path
}

$null = Get-Archive 'python' $sources.PythonArchive $sources.PythonUrl
$null = Get-Archive 'cmake' $sources.CMakeArchive $sources.CMakeUrl
$null = Get-Archive 'ninja' $sources.NinjaArchive $sources.NinjaUrl
$null = Get-Archive 'arm-gcc' $sources.ArmGccArchive $sources.ArmGccUrl

$pipWheel = Join-Path $downloadRoot $sources.PipWheel
if (-not (Test-Path -LiteralPath $pipWheel)) {
    if ($OfflineCheck) { throw "缺少本地 pip wheel: $pipWheel" }
    Write-Host "获取 pip $($sources.PipVersion) wheel"
    $metadata = Invoke-RestMethod -Uri $sources.PipMetadataUrl -TimeoutSec 120
    $matches = @($metadata.urls | Where-Object { $_.filename -eq $sources.PipWheel })
    if ($matches.Count -ne 1) { throw "找不到 pip wheel: $($sources.PipWheel)" }
    $partial = "$pipWheel.part"
    Assert-CacheChild $partial
    try {
        Invoke-WebRequest -Uri $matches[0].url -OutFile $partial -UseBasicParsing -TimeoutSec 300
        if ((Get-FileHash -LiteralPath $partial -Algorithm SHA256).Hash -ine $matches[0].digests.sha256) {
            throw 'pip wheel SHA256 校验失败'
        }
        Move-Item -LiteralPath $partial -Destination $pipWheel
    } finally {
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force }
    }
}

$stage = Join-Path $cacheRoot ('.prepare-python-' + [guid]::NewGuid().ToString('N'))
Assert-CacheChild $stage
try {
    New-Item -ItemType Directory -Path $stage | Out-Null
    $pythonArchive = Join-Path $downloadRoot $sources.PythonArchive
    if (Test-Path -LiteralPath $pythonArchive) {
        Expand-Archive -LiteralPath $pythonArchive -DestinationPath $stage
    } else {
        foreach ($item in Get-ChildItem -LiteralPath (Join-Path $cacheRoot 'python') -Force) {
            Copy-Item -LiteralPath $item.FullName -Destination $stage -Recurse -Force
        }
    }
    $python = Join-Path $stage 'python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw "本地 Python 归档缺少 python.exe: $pythonArchive" }
    $sitePackages = Join-Path $stage 'Lib/site-packages'
    New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
    $pth = "$pythonZip`r`n.`r`nLib\site-packages`r`n"
    [IO.File]::WriteAllText((Join-Path $stage $pythonPth), $pth, [Text.Encoding]::ASCII)
    [IO.Compression.ZipFile]::ExtractToDirectory($pipWheel, $sitePackages)
    $requirements = Join-Path $PSScriptRoot 'requirements.txt'
    $offlineArgs = @('-m', 'pip', '--disable-pip-version-check', 'download', '--no-index',
                     '--find-links', $wheelRoot, '--only-binary', ':all:', '--dest', $wheelRoot,
                     '-r', $requirements)
    Write-Host '检查本地 requirements.txt wheel 缓存...'
    & $python @offlineArgs
    if ($LASTEXITCODE -ne 0) {
        if ($OfflineCheck) { throw "缺少 requirements.txt 的本地 wheel: $wheelRoot" }
        Write-Host '下载 requirements.txt 的全部 wheel...'
        & $python -m pip --disable-pip-version-check download --only-binary ':all:' --dest $wheelRoot -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Python 依赖 wheel 下载失败' }
        & $python @offlineArgs
        if ($LASTEXITCODE -ne 0) { throw '下载后仍无法从本地 wheel 缓存满足 requirements.txt' }
    }
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
Write-Host "本地 Portable 缓存已备齐: $cacheRoot"
