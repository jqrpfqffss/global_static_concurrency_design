param(
    [string]$OutputDir = (Join-Path $PSScriptRoot 'dist'),
    [string]$CacheDir = (Join-Path $PSScriptRoot '.tools-cache'),
    [string]$PythonSource,
    [string]$CMakeSource,
    [string]$NinjaSource,
    [string]$ArmGccSource,
    [string]$PipWheelSource,
    [switch]$SkipZip
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

# All network locations live in the optional preparation script's manifest.
# This build reads only local extracted caches, local archives or *Source paths.
$sources = Import-PowerShellDataFile -Path (Join-Path $PSScriptRoot 'config/portable_sources.psd1')
$pythonTag = (($sources.PythonVersion -split '\.')[0..1] -join '')
$pythonZip = "python$pythonTag.zip"
$pythonPth = "python$pythonTag._pth"

function Assert-ChildPath([string]$Parent, [string]$Child) {
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $childFull = [IO.Path]::GetFullPath($Child)
    if (-not $childFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝操作输出目录之外的路径: $childFull"
    }
}

function Remove-OutputChild([string]$Parent, [string]$Child) {
    Assert-ChildPath $Parent $Child
    if (Test-Path -LiteralPath $Child) {
        Remove-Item -LiteralPath $Child -Recurse -Force
    }
}

function Test-Asset([string]$Kind, [string]$Directory) {
    switch ($Kind) {
        'python' {
            return ((Test-Path (Join-Path $Directory 'python.exe')) -and
                    (Test-Path (Join-Path $Directory $pythonZip)) -and
                    (Test-Path (Join-Path $Directory $pythonPth)))
        }
        'cmake' {
            return ((Test-Path (Join-Path $Directory 'bin/cmake.exe')) -and
                    (Test-Path (Join-Path $Directory 'share')))
        }
        'ninja' { return (Test-Path (Join-Path $Directory 'ninja.exe')) }
        'arm-gcc' {
            foreach ($relative in @('bin/arm-none-eabi-gcc.exe', 'bin/arm-none-eabi-g++.exe',
                                   'bin/arm-none-eabi-ar.exe', 'lib', 'arm-none-eabi')) {
                if (-not (Test-Path (Join-Path $Directory $relative))) { return $false }
            }
            return $true
        }
    }
    throw "未知工具: $Kind"
}

function Test-PinnedArmGcc([string]$Directory) {
    $compiler = Join-Path $Directory 'bin/arm-none-eabi-gcc.exe'
    if (-not (Test-Path -LiteralPath $compiler)) { return $false }
    try {
        $firstLine = & $compiler --version 2>&1 | Select-Object -First 1
        return ($LASTEXITCODE -eq 0 -and
                $firstLine -match ('\b' + [regex]::Escape($sources.ArmGccVersion) + '\b'))
    } catch { return $false }
}

function Find-AssetRoot([string]$Kind, [string]$Directory) {
    $candidates = @($Directory)
    $firstLevel = @(Get-ChildItem -LiteralPath $Directory -Directory -Force)
    $candidates += @($firstLevel | ForEach-Object { $_.FullName })
    foreach ($child in $firstLevel) {
        $candidates += @(Get-ChildItem -LiteralPath $child.FullName -Directory -Force |
                         ForEach-Object { $_.FullName })
    }
    foreach ($candidate in $candidates) {
        if (Test-Asset $Kind $candidate) { return $candidate }
    }
    throw "$Kind 来源缺少完整目录结构: $Directory"
}

function Copy-DirectoryContents([string]$From, [string]$To) {
    New-Item -ItemType Directory -Path $To -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $From -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $To -Recurse -Force
    }
}

function Resolve-Asset([string]$Kind, [string]$Source, [string]$ArchiveName) {
    $cached = Join-Path $cacheRoot $Kind
    if (-not $Source -and (Test-Asset $Kind $cached)) {
        if ($Kind -ne 'arm-gcc' -or (Test-PinnedArmGcc $cached)) {
            Write-Host "复用缓存: $cached"
            return $cached
        }
        Write-Host "Arm GCC 缓存版本与固定的 $($sources.ArmGccVersion) 不符，将查找本地归档。"
    }
    $stage = Join-Path $cacheRoot ('.extract-' + $Kind + '-' + [guid]::NewGuid().ToString('N'))
    $replacement = Join-Path $cacheRoot ('.prepared-' + $Kind + '-' + [guid]::NewGuid().ToString('N'))
    $backup = Join-Path $cacheRoot ('.previous-' + $Kind + '-' + [guid]::NewGuid().ToString('N'))
    Assert-ChildPath $cacheRoot $stage
    Assert-ChildPath $cacheRoot $replacement
    Assert-ChildPath $cacheRoot $backup
    Assert-ChildPath $cacheRoot $cached
    try {
        if ($Source) {
            $sourcePath = (Resolve-Path -LiteralPath $Source).Path
            Write-Host "使用本地来源: $sourcePath"
        } else {
            $sourcePath = Join-Path $downloadRoot $ArchiveName
            if (-not (Test-Path -LiteralPath $sourcePath)) {
                throw "$Kind 缺少本地来源: $sourcePath。先运行 prepare_portable_cache.ps1，或提供对应的 -...Source 本地目录/ZIP。"
            }
            Write-Host "使用本地归档: $sourcePath"
        }
        $item = Get-Item -LiteralPath $sourcePath
        if ($item.PSIsContainer) {
            $root = Find-AssetRoot $Kind $item.FullName
        } else {
            New-Item -ItemType Directory -Path $stage | Out-Null
            if ($Kind -eq 'ninja' -and $item.Name -ieq 'ninja.exe') {
                Copy-Item -LiteralPath $item.FullName -Destination (Join-Path $stage 'ninja.exe')
            } elseif ($item.Extension -ieq '.zip') {
                Expand-Archive -LiteralPath $item.FullName -DestinationPath $stage -Force
            } else {
                throw "$Kind 来源必须为完整目录或 ZIP: $sourcePath"
            }
            $root = Find-AssetRoot $Kind $stage
        }
        if ($Kind -eq 'arm-gcc' -and -not (Test-PinnedArmGcc $root)) {
            throw "Arm GCC 来源版本不是固定的 $($sources.ArmGccVersion): $root"
        }
        Copy-DirectoryContents $root $replacement
        if (-not (Test-Asset $Kind $replacement)) { throw "$Kind 缓存结构无效: $replacement" }
        if ($Kind -eq 'arm-gcc' -and -not (Test-PinnedArmGcc $replacement)) {
            throw "Arm GCC 复制后的版本不是固定的 $($sources.ArmGccVersion): $replacement"
        }
        if (Test-Path -LiteralPath $cached) { Move-Item -LiteralPath $cached -Destination $backup }
        try {
            Move-Item -LiteralPath $replacement -Destination $cached
        } catch {
            if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $cached }
            throw
        }
        Remove-OutputChild $cacheRoot $backup
        return $cached
    } finally {
        Remove-OutputChild $cacheRoot $stage
        Remove-OutputChild $cacheRoot $replacement
    }
}

function Invoke-Checked([string]$Label, [string]$Executable, [string[]]$Arguments) {
    Write-Host "检查 $Label ..."
    $result = & $Executable @Arguments 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "$Label 失败 (exit $LASTEXITCODE): $result" }
    $result = $result.Trim()
    if ($result) { Write-Host $result }
    return $result
}

function Get-FirstLine([string]$Text) {
    return (@($Text -split "`r?`n" | Where-Object { $_.Trim() })[0]).Trim()
}

function Assert-Launcher([string]$Bundle) {
    $launcher = Join-Path $Bundle 'ecra.cmd'
    $help = Invoke-Checked 'ECRA CLI' $launcher @('--help')
    foreach ($command in @('run', 'init', 'doctor', 'review', 'report', 'status')) {
        if ($help -notmatch "\b$command\b") { throw "CLI 帮助缺少命令: $command" }
    }
}

if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
    throw '此脚本需要 64 位 Windows 构建机。'
}
Add-Type -AssemblyName System.IO.Compression.FileSystem
$outputRoot = [IO.Path]::GetFullPath($OutputDir)
$cacheRoot = [IO.Path]::GetFullPath($CacheDir)
$separator = [IO.Path]::DirectorySeparatorChar
if ($outputRoot -eq $cacheRoot -or $outputRoot.StartsWith($cacheRoot.TrimEnd('\', '/') + $separator, [StringComparison]::OrdinalIgnoreCase) -or
    $cacheRoot.StartsWith($outputRoot.TrimEnd('\', '/') + $separator, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDir 与 CacheDir 不得相同或互相包含。'
}
New-Item -ItemType Directory -Path $outputRoot, $cacheRoot -Force | Out-Null
$downloadRoot = Join-Path $cacheRoot 'downloads'
$wheelRoot = Join-Path $cacheRoot 'wheels'
New-Item -ItemType Directory -Path $downloadRoot, $wheelRoot -Force | Out-Null
$bundle = Join-Path $outputRoot 'ECRA-Portable'
$zip = Join-Path $outputRoot 'ECRA-Portable.zip'
Remove-OutputChild $outputRoot $bundle
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }

try {
    $pythonBase = Resolve-Asset 'python' $PythonSource $sources.PythonArchive
    $cmakeBase = Resolve-Asset 'cmake' $CMakeSource $sources.CMakeArchive
    $ninjaBase = Resolve-Asset 'ninja' $NinjaSource $sources.NinjaArchive
    $armBase = Resolve-Asset 'arm-gcc' $ArmGccSource $sources.ArmGccArchive

    New-Item -ItemType Directory -Path $bundle -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run_ecra.py') -Destination $bundle
    $packageOut = Join-Path $bundle 'ecra'
    New-Item -ItemType Directory -Path $packageOut | Out-Null
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'ecra') -File -Filter '*.py') {
        Copy-Item -LiteralPath $file.FullName -Destination $packageOut
    }
    if (-not (Test-Path (Join-Path $packageOut '__init__.py'))) { throw 'ecra 包不完整' }
    $configOut = Join-Path $bundle 'config'
    New-Item -ItemType Directory -Path $configOut | Out-Null
    foreach ($name in @('semantics.yaml', 'review_context.md', 'concurrency_cases.md')) {
        Copy-Item -LiteralPath (Join-Path (Join-Path $PSScriptRoot 'config') $name) -Destination $configOut
    }

    $runtime = Join-Path $bundle 'runtime'
    Copy-DirectoryContents $pythonBase $runtime
    $sitePackages = Join-Path $runtime 'Lib/site-packages'
    New-Item -ItemType Directory -Path $sitePackages -Force | Out-Null
    # _pth keeps the runtime independent of registry, user site and host PYTHONPATH.
    # The last line makes `python.exe -m ecra.extract` work from any cwd.
    $pth = "$pythonZip`r`n.`r`nLib\site-packages`r`n..`r`n"
    [IO.File]::WriteAllText((Join-Path $runtime $pythonPth), $pth, [Text.Encoding]::ASCII)
    $python = Join-Path $runtime 'python.exe'

    $pipWheel = Join-Path $downloadRoot $sources.PipWheel
    if (-not (Test-Path -LiteralPath $pipWheel)) {
        if ($PipWheelSource) {
            Copy-Item -LiteralPath (Resolve-Path -LiteralPath $PipWheelSource).Path -Destination $pipWheel
        } else {
            throw "缺少本地 pip wheel: $pipWheel。先运行 prepare_portable_cache.ps1，或提供 -PipWheelSource。"
        }
    }
    [IO.Compression.ZipFile]::ExtractToDirectory($pipWheel, $sitePackages)
    $null = Invoke-Checked 'Python' $python @('--version')
    $null = Invoke-Checked 'pip' $python @('-m', 'pip', '--version')
    $requirements = Join-Path $PSScriptRoot 'requirements.txt'
    if (-not (Test-Path -LiteralPath $requirements)) { throw '缺少 requirements.txt' }
    $pipArgs = @('-m', 'pip', '--disable-pip-version-check', 'install', '--no-index', '--find-links', $wheelRoot,
                 '--only-binary', ':all:', '--no-compile', '--target', $sitePackages, '-r', $requirements)
    Write-Host '从本地 wheel 缓存安装 requirements.txt ...'
    & $python @pipArgs
    if ($LASTEXITCODE -ne 0) {
        throw "本地 wheel 缓存不足以安装 requirements.txt: $wheelRoot。先运行 prepare_portable_cache.ps1。"
    }

    $toolsDir = Join-Path $bundle 'tools'
    New-Item -ItemType Directory -Path $toolsDir | Out-Null
    Copy-DirectoryContents $cmakeBase (Join-Path $toolsDir 'cmake')
    Copy-DirectoryContents $ninjaBase (Join-Path $toolsDir 'ninja')
    Copy-DirectoryContents $armBase (Join-Path $toolsDir 'arm-gcc')

    $launcher = '@echo off' + "`r`n" +
        'setlocal DisableDelayedExpansion' + "`r`n" +
        'set "ECRA_ROOT=%~dp0"' + "`r`n" +
        'set "ECRA_CONFIG_HOME=%ECRA_ROOT%config"' + "`r`n" +
        'set "PATH=%ECRA_ROOT%tools\cmake\bin;%ECRA_ROOT%tools\ninja;%ECRA_ROOT%tools\arm-gcc\bin;%PATH%"' + "`r`n" +
        '"%ECRA_ROOT%runtime\python.exe" "%ECRA_ROOT%run_ecra.py" %*' + "`r`n" +
        'exit /b %ERRORLEVEL%' + "`r`n"
    [IO.File]::WriteAllText((Join-Path $bundle 'ecra.cmd'), $launcher, [Text.Encoding]::ASCII)
    $readme = @'
ECRA Windows Full Portable

1. 编辑 config/semantics.yaml，特别是 project.root 和工程的 CMake 设置。
2. 如需补充工程背景，编辑 config/review_context.md。
3. 从任意目录运行 ecra.cmd doctor 检查所配置工程。
4. 运行 ecra.cmd 执行静态排查。
5. 运行 ecra.cmd review 继续 AI 复核。
6. 运行 ecra.cmd report 刷新报告。
7. 运行 ecra.cmd status 查看进度。

入口也支持 run、init、--project、--no-review 等原有参数；可用 ecra.cmd --help 查看。
config 目录是可编辑的用户配置，更新工具前请自行备份修改。
OpenCode 未包含在 Portable 包中。需要 AI review 时，目标电脑需自行配置可用的 opencode 命令；静态扫描可通过 review.enabled: false 或 --no-review 独立运行。
本包自带 Python、PyYAML、libclang、CMake、Ninja 和 ARM GNU Toolchain。
'@
    [IO.File]::WriteAllText((Join-Path $bundle 'README.txt'), $readme, (New-Object Text.UTF8Encoding($true)))

    # Run acceptance commands from outside the bundle with only bundled tools
    # and Windows system directories on PATH.
    $oldPath = $env:PATH
    $oldPythonPath = $env:PYTHONPATH
    $oldPythonHome = $env:PYTHONHOME
    try {
        $systemPath = @((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot,
                        (Join-Path $env:SystemRoot 'System32/Wbem')) -join ';'
        $env:PATH = (Join-Path $toolsDir 'cmake/bin') + ';' + (Join-Path $toolsDir 'ninja') + ';' +
                    (Join-Path $toolsDir 'arm-gcc/bin') + ';' + $systemPath
        $env:PYTHONPATH = ''
        $env:PYTHONHOME = ''
        $pythonVersionText = Invoke-Checked 'Python 版本' $python @('--version')
        $probe = "import sys, ecra, yaml; from clang import cindex; from importlib.metadata import version; cindex.Index.create(); print('libclang OK'); print('libclang package ' + version('libclang')); print('python executable ' + sys.executable)"
        $pythonProbe = Invoke-Checked 'ECRA / PyYAML / libclang' $python @('-c', $probe)
        if ($pythonProbe -notmatch 'libclang OK' -or $pythonProbe -notmatch 'python executable ') {
            throw 'Python 依赖自检输出异常'
        }
        $actualPython = ($pythonProbe -split "`r?`n" | Where-Object { $_ -like 'python executable *' } | Select-Object -First 1).Substring(18)
        if ([IO.Path]::GetFullPath($actualPython) -ine [IO.Path]::GetFullPath($python)) {
            throw "sys.executable 未指向便携解释器: $actualPython"
        }
        $cmakeText = Invoke-Checked 'CMake' (Join-Path $toolsDir 'cmake/bin/cmake.exe') @('--version')
        $ninjaText = Invoke-Checked 'Ninja' (Join-Path $toolsDir 'ninja/ninja.exe') @('--version')
        $gccText = Invoke-Checked 'ARM GCC' (Join-Path $toolsDir 'arm-gcc/bin/arm-none-eabi-gcc.exe') @('--version')
        $null = Invoke-Checked 'ARM G++' (Join-Path $toolsDir 'arm-gcc/bin/arm-none-eabi-g++.exe') @('--version')
        $null = Invoke-Checked 'ARM ar' (Join-Path $toolsDir 'arm-gcc/bin/arm-none-eabi-ar.exe') @('--version')
        foreach ($name in @('cmake', 'ninja', 'arm-none-eabi-gcc')) {
            $found = (Get-Command $name -CommandType Application -ErrorAction Stop).Source
            if (-not $found.StartsWith($toolsDir + [IO.Path]::DirectorySeparatorChar,
                                       [StringComparison]::OrdinalIgnoreCase)) {
                throw "$name 被外部 PATH 提供: $found"
            }
        }
        $previousLocation = Get-Location
        try {
            Set-Location -LiteralPath $outputRoot
            Assert-Launcher $bundle
            $request = Join-Path $cacheRoot 'portable-probe.request.json'
            $response = Join-Path $cacheRoot 'portable-probe.response.json'
            [IO.File]::WriteAllText($request, '{}', [Text.Encoding]::ASCII)
            if (Test-Path -LiteralPath $response) { Remove-Item -LiteralPath $response -Force }
            $null = Invoke-Checked '提取子进程导入' $python @('-m', 'ecra.extract', $request, $response)
            if (-not (Test-Path -LiteralPath $response)) { throw 'ecra.extract 未生成子进程输出' }
            Remove-Item -LiteralPath $request, $response -Force
        } finally {
            Set-Location $previousLocation
        }
    } finally {
        $env:PATH = $oldPath
        $env:PYTHONPATH = $oldPythonPath
        $env:PYTHONHOME = $oldPythonHome
    }

    $version = (Select-String -LiteralPath (Join-Path $PSScriptRoot 'pyproject.toml') -Pattern '^version\s*=\s*"([^"]+)"' |
                Select-Object -First 1).Matches.Groups[1].Value
    $commit = 'unknown'
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $value = & git -C $PSScriptRoot rev-parse HEAD 2>$null
        if ($LASTEXITCODE -eq 0 -and $value) { $commit = ($value | Select-Object -First 1).Trim() }
    }
    $manifest = @(
        "ECRA version: $version",
        "Python version: $(Get-FirstLine $pythonVersionText)",
        "libclang version: $(($pythonProbe -split "`r?`n" | Where-Object { $_ -like 'libclang package *' } | Select-Object -First 1).Trim())",
        "CMake version: $(Get-FirstLine $cmakeText)",
        "Ninja version: $(Get-FirstLine $ninjaText)",
        "ARM GCC version: $(Get-FirstLine $gccText)",
        "Built at (UTC): $([datetime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))",
        "Git commit: $commit"
    ) -join "`r`n"
    [IO.File]::WriteAllText((Join-Path $bundle 'VERSION.txt'), $manifest + "`r`n", [Text.Encoding]::UTF8)

    # Import and pip checks can create bytecode even with pip --no-compile.
    # Keep generated build-machine artifacts out of the deliverable.
    $bytecodeDirs = @(Get-ChildItem -LiteralPath $bundle -Recurse -Directory -Filter '__pycache__' |
                     Sort-Object { $_.FullName.Length } -Descending)
    foreach ($dir in $bytecodeDirs) { Remove-OutputChild $bundle $dir.FullName }
    foreach ($file in Get-ChildItem -LiteralPath $bundle -Recurse -File -Filter '*.pyc') {
        Remove-OutputChild $bundle $file.FullName
    }

    if (-not $SkipZip) {
        Write-Host '压缩 ECRA-Portable.zip ...'
        [IO.Compression.ZipFile]::CreateFromDirectory($bundle, $zip,
            [IO.Compression.CompressionLevel]::Optimal, $true)
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            $names = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
            foreach ($name in @('ecra.cmd', 'run_ecra.py', 'README.txt', 'VERSION.txt',
                                'config/semantics.yaml', 'config/review_context.md', 'config/concurrency_cases.md',
                                'runtime/python.exe', 'tools/cmake/bin/cmake.exe',
                                'tools/ninja/ninja.exe', 'tools/arm-gcc/bin/arm-none-eabi-gcc.exe')) {
                if ($names -cnotcontains "ECRA-Portable/$name") { throw "ZIP 缺少: $name" }
            }
            if (@($names | Where-Object { -not $_.StartsWith('ECRA-Portable/') }).Count -gt 0) {
                throw 'ZIP 根目录层级错误'
            }
            if (@($names | Where-Object { $_ -match '(^|/)(opencode|node|npm)(\.exe|\.cmd)?(/|$)' }).Count -gt 0) {
                throw 'ZIP 意外包含 OpenCode/Node/npm'
            }
        } finally {
            $archive.Dispose()
        }
        $zipCheck = Join-Path $outputRoot ('.zip-check-' + [guid]::NewGuid().ToString('N'))
        try {
            [IO.Compression.ZipFile]::ExtractToDirectory($zip, $zipCheck)
            $extracted = Join-Path $zipCheck 'ECRA-Portable'
            if (-not (Test-Asset 'python' (Join-Path $extracted 'runtime')) -or
                -not (Test-Asset 'arm-gcc' (Join-Path $extracted 'tools/arm-gcc'))) {
                throw 'ZIP 解压后缺少完整运行时或工具链'
            }
            $unpackedPython = Join-Path $extracted 'runtime/python.exe'
            $null = Invoke-Checked 'ZIP Python / ECRA / PyYAML / libclang' $unpackedPython @('-c', $probe)
            $null = Invoke-Checked 'ZIP CMake' (Join-Path $extracted 'tools/cmake/bin/cmake.exe') @('--version')
            $null = Invoke-Checked 'ZIP Ninja' (Join-Path $extracted 'tools/ninja/ninja.exe') @('--version')
            $null = Invoke-Checked 'ZIP ARM GCC' (Join-Path $extracted 'tools/arm-gcc/bin/arm-none-eabi-gcc.exe') @('--version')
            Assert-Launcher $extracted
        } finally {
            Remove-OutputChild $outputRoot $zipCheck
        }
    }
    Write-Host "构建成功: $bundle"
    if (-not $SkipZip) { Write-Host "ZIP 自检通过: $zip" }
} catch {
    Write-Host "Portable 构建失败: $_" -ForegroundColor Red
    throw
}
