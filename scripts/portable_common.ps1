# Shared by online preparation and the strictly offline packager. Windows PS 5.1.
function Get-FrozenSourceRevision([string]$SourceRoot) {
    $manifest = $SourceRoot.TrimEnd('\','/') + '.sha256.json'
    if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) { return $null }
    $snapshot = Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($snapshot.passed -ne $true -or $snapshot.head -notmatch '^[a-f0-9]{40}$' -or -not $snapshot.files.Count) {
        throw 'Frozen source manifest is incomplete or invalid; preserve the snapshot.'
    }
    $seen = @{}
    foreach ($entry in $snapshot.files) {
        if ([IO.Path]::IsPathRooted($entry.file) -or $entry.file -match '(^|[/\\])\.\.([/\\]|$)' -or $seen.ContainsKey($entry.file)) {
            throw 'Frozen source manifest contains unsafe or duplicate paths.'
        }
        $seen[$entry.file] = $true
        $file = Join-Path $SourceRoot $entry.file
        Assert-ChildPath $SourceRoot $file
        if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or
            (Get-Item -LiteralPath $file).Length -ne $entry.size -or
            (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash -ine $entry.sha256) {
            throw "Frozen source changed: $($entry.file); preserve and rebuild a fresh snapshot."
        }
    }
    return @{ head=$snapshot.head; manifest=$manifest; files=$snapshot.files.Count;
        sha256=(Get-FileHash -LiteralPath $manifest -Algorithm SHA256).Hash }
}

function Assert-ChildPath([string]$Parent, [string]$Child) {
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $childFull = [IO.Path]::GetFullPath($Child)
    if (-not $childFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing path outside $Parent : $childFull"
    }
    # Do not follow junctions/symlinks during recursive cleanup or source copying.
    $cursor = $childFull
    while ($cursor -and $cursor.Length -ge $parentFull.TrimEnd('\').Length) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Reparse point is not allowed: $cursor"
            }
        }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
}

function Remove-OutputChild([string]$Parent, [string]$Child) {
    Assert-ChildPath $Parent $Child
    if (Test-Path -LiteralPath $Child) {
        $links = @(Get-ChildItem -LiteralPath $Child -Recurse -Force -ErrorAction Stop |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
        if ($links.Count) { throw "Refusing recursive cleanup containing a reparse point: $Child" }
        for ($attempt = 0; $attempt -lt 5; $attempt++) {
            try { Remove-Item -LiteralPath $Child -Recurse -Force; return }
            catch {
                if ($attempt -eq 4) { throw "Cannot clean $Child after 5 attempts. Close processes using it. $_" }
                Start-Sleep -Milliseconds (100 * [math]::Pow(2, $attempt))
            }
        }
    }
}

function Invoke-Checked([string]$Label, [string]$Executable, [string[]]$Arguments) {
    Write-Host "Check $Label : $Executable $($Arguments -join ' ')"
    # Windows PS treats native stderr as ErrorRecord. Keep stderr in the log;
    # the native exit code, never the presence of stderr, determines success.
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $result = & $Executable @Arguments 2>&1 | Out-String
        $code = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($code -ne 0) { throw "$Label failed (exit $code): $Executable`n$result" }
    return $result.Trim().Replace("`r`n", "`n")
}

function Get-SystemPath {
    return (@((Join-Path $env:SystemRoot 'System32'), $env:SystemRoot,
        (Join-Path $env:SystemRoot 'System32/Wbem'),
        (Join-Path $env:SystemRoot 'System32/WindowsPowerShell/v1.0')) -join ';')
}

function Test-Asset([string]$Kind, [string]$Directory) {
    $required = switch ($Kind) {
        'python' { @('python.exe', 'python310.dll', 'python310.zip', 'python310._pth', 'LICENSE.txt') }
        'cmake' { @('bin/cmake.exe', 'bin/ctest.exe', 'share/cmake-3.29/Modules/CMake.cmake', 'doc') }
        'ninja' { @('ninja.exe') }
        'mingw' { @('bin/gcc.exe', 'bin/g++.exe', 'bin/ar.exe', 'bin/ld.exe', 'bin/as.exe',
            'lib/gcc/x86_64-w64-mingw32/14.2.0', 'x86_64-w64-mingw32/include/windows.h',
            'x86_64-w64-mingw32/lib/libkernel32.a') }
        'make' { @('bin/mingw32-make.exe') }
        'vc-runtime' { @('msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll','LICENSE.rtf') }
        'arm-gcc' { @('bin/arm-none-eabi-gcc.exe', 'bin/arm-none-eabi-g++.exe', 'bin/arm-none-eabi-ar.exe',
            'bin/arm-none-eabi-ld.exe', 'bin/arm-none-eabi-as.exe', 'bin/arm-none-eabi-objcopy.exe',
            'lib/gcc/arm-none-eabi/10.3.1', 'arm-none-eabi/include/stdint.h', 'arm-none-eabi/lib/libc.a') }
        default { throw "Unknown asset: $Kind" }
    }
    foreach ($relative in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $Directory $relative))) { return $false }
    }
    return $true
}

function Assert-Asset([string]$Kind, [string]$Directory) {
    if (-not (Test-Asset $Kind $Directory)) { throw "$Kind incomplete directory: $Directory" }
    if ($Kind -eq 'vc-runtime') {
        foreach ($name in @('msvcp140.dll','vcruntime140.dll','vcruntime140_1.dll')) {
            $file = Join-Path $Directory $name
            $actual = (Get-Item -LiteralPath $file).VersionInfo.FileVersion
            if ($actual -ne $sources.VcRuntimeVersion) { throw "VC runtime version mismatch: $file : $actual" }
        }
        return "Microsoft VC++ x64 Runtime $($sources.VcRuntimeVersion)"
    }
    $exe = switch ($Kind) {
        'python' { 'python.exe' }; 'cmake' { 'bin/cmake.exe' }; 'ninja' { 'ninja.exe' }
        'mingw' { 'bin/gcc.exe' }; 'make' { 'bin/mingw32-make.exe' }; 'arm-gcc' { 'bin/arm-none-eabi-gcc.exe' }
    }
    $oldPath = $env:PATH
    try {
        $env:PATH = (Join-Path $Directory 'bin') + ';' + $Directory + ';' + (Get-SystemPath)
        $version = Invoke-Checked $Kind (Join-Path $Directory $exe) @('--version')
        $ok = switch ($Kind) {
            'python' { $version -match ('(?m)^Python ' + [regex]::Escape($sources.PythonVersion) + '$') }
            'cmake' { $version -match ('(?m)^cmake version ' + [regex]::Escape($sources.CMakeVersion) + '(\s|$)') }
            'ninja' { $version -ceq $sources.NinjaVersion }
            'mingw' { $version -match ('^gcc.exe \(' + [regex]::Escape($sources.MinGWVariant) + ', Built by MinGW-Builds project\) ' + [regex]::Escape($sources.MinGWVersion) + '(\s|$)') }
            'make' { $version -match ('(?m)^GNU Make ' + [regex]::Escape($sources.MakeVersion) + '$') -and $version -match ('Built for ' + [regex]::Escape($sources.MakePlatform)) }
            'arm-gcc' { $version -match ([regex]::Escape($sources.ArmGccRelease) + '\) ' + [regex]::Escape($sources.ArmGccVersion) + ' 20210824 \(release\)') }
        }
        if (-not $ok) { throw "$Kind version/distribution mismatch: $Directory`n$version" }
        if ($Kind -eq 'cmake') {
            $copyright = @(Get-ChildItem -LiteralPath (Join-Path $Directory 'doc') -Recurse -File -Filter Copyright.txt)
            if (-not $copyright.Count) { throw "CMake redistribution notices missing: $Directory/doc" }
            if ($version -match 'JetBrains' -and $version -notmatch 'JetBrains IDE bundle; build 1\)') {
                throw "CMake JetBrains distribution build identifier differs from requested build 1: $version"
            }
        }
        if ($Kind -in @('mingw', 'arm-gcc')) {
            $prefix = if ($Kind -eq 'mingw') { '' } else { 'arm-none-eabi-' }
            $gcc = Join-Path $Directory ('bin/' + $prefix + 'gcc.exe')
            $gpp = Invoke-Checked 'C++ compiler' (Join-Path $Directory ('bin/' + $prefix + 'g++.exe')) @('--version')
            $expected = if ($Kind -eq 'mingw') { $sources.MinGWVersion } else { $sources.ArmGccVersion }
            if ($gpp -notmatch ('\b' + [regex]::Escape($expected) + '\b')) { throw "C/C++ version mismatch: $Directory" }
            if ($Kind -eq 'mingw' -and $gpp -notmatch [regex]::Escape($sources.MinGWVariant + ', Built by MinGW-Builds project')) {
                throw "C++ compiler distribution mismatch: $Directory : $gpp"
            }
            $target = Invoke-Checked 'GCC target' $gcc @('-dumpmachine')
            $wanted = if ($Kind -eq 'mingw') { 'x86_64-w64-mingw32' } else { 'arm-none-eabi' }
            if ($target -cne $wanted) { throw "GCC target mismatch: $target" }
            if ($Kind -eq 'mingw') {
                $verbose = Invoke-Checked 'GCC distribution' $gcc @('-v')
                if ($verbose -notmatch 'Thread model: mcf') { throw "GCC thread model mismatch: $verbose" }
            }
            foreach ($program in @('cc1', 'cc1plus', 'collect2')) {
                $path = Invoke-Checked "GCC internal $program" $gcc @("-print-prog-name=$program")
                if (-not [IO.Path]::IsPathRooted($path)) { throw "Unresolved GCC internal: $path" }
                Assert-ChildPath $Directory $path
                if (-not (Test-Path -LiteralPath $path)) { throw "Missing GCC internal: $path" }
            }
            foreach ($library in @('libgcc.a','libstdc++.a')) {
                $path = Invoke-Checked "GCC library $library" $gcc @("-print-file-name=$library")
                if (-not [IO.Path]::IsPathRooted($path)) { throw "Missing GCC library: $path in $Directory" }
                Assert-ChildPath $Directory $path
                if (-not (Test-Path -LiteralPath $path)) { throw "Missing GCC library: $path" }
            }
            $search = Invoke-Checked 'GCC search directories' $gcc @('-print-search-dirs')
        }
        return $version
    } finally { $env:PATH = $oldPath }
}

function Find-AssetRoot([string]$Kind, [string]$Directory) {
    $candidates = @($Directory)
    $first = @(Get-ChildItem -LiteralPath $Directory -Directory -Force)
    $candidates += @($first | ForEach-Object { $_.FullName })
    foreach ($child in $first) {
        $candidates += @(Get-ChildItem -LiteralPath $child.FullName -Directory -Force | ForEach-Object { $_.FullName })
    }
    foreach ($candidate in $candidates) { if (Test-Asset $Kind $candidate) { return $candidate } }
    throw "$Kind missing complete directory structure: $Directory"
}

function Copy-DirectoryContents([string]$From, [string]$To) {
    $links = @(Get-ChildItem -LiteralPath $From -Recurse -Force |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
    if ($links.Count) { throw "Source contains reparse points: $From" }
    New-Item -ItemType Directory -Path $To -Force | Out-Null
    foreach ($item in Get-ChildItem -LiteralPath $From -Force) {
        Copy-Item -LiteralPath $item.FullName -Destination $To -Recurse -Force
    }
}

function Write-Receipt([string]$File, [string]$Origin) {
    $receipt = @{ source = $Origin; sha256 = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash;
        size = (Get-Item -LiteralPath $File).Length; recorded_utc = [datetime]::UtcNow.ToString('o') }
    $receipt | ConvertTo-Json | Set-Content -LiteralPath ($File + '.receipt.json') -Encoding UTF8
}

function Save-RemoteFile([string]$Url, [string]$Destination) {
    # Prefer Git's OpenSSL curl when present; it also honours Windows' configured
    # HTTP proxy without weakening TLS certificate validation.
    $git = Get-Command git.exe -ErrorAction SilentlyContinue
    $curl = if ($git) { Join-Path (Split-Path (Split-Path $git.Source)) 'mingw64/bin/curl.exe' } else { '' }
    if ($curl -and (Test-Path -LiteralPath $curl)) {
        $arguments = @('--http1.1','--fail','--silent','--show-error','--location','--max-time','240','--continue-at','-','--output',$Destination)
        if (-not $env:https_proxy -and -not $env:HTTPS_PROXY) {
            $settings = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' -ErrorAction SilentlyContinue
            if ($settings -and $settings.ProxyEnable -and $settings.ProxyServer -and $settings.ProxyServer -notmatch '=') {
                $arguments += @('--proxy',('http://' + $settings.ProxyServer))
            }
        }
        for ($attempt=0; $attempt -lt 5; $attempt++) {
            & $curl @arguments $Url
            if ($LASTEXITCODE -eq 0) { return }
            $code = $LASTEXITCODE
            Write-Host "Download interrupted (exit $code), bounded resume attempt $($attempt+1)/5: $Url"
        }
        throw "Download failed (exit $code): $Url"
    } else { Invoke-WebRequest -Uri $Url -OutFile $Destination -UseBasicParsing -TimeoutSec 900 }
}

function Get-RemoteText([string]$Url) {
    $file = Join-Path $cacheRoot ('.metadata-' + [guid]::NewGuid().ToString('N'))
    try { Save-RemoteFile $Url $file; return [IO.File]::ReadAllText($file) }
    finally { Remove-OutputChild $cacheRoot $file }
}

function Assert-Archive([string]$File, [string]$Expected = '') {
    if (-not (Test-Path -LiteralPath $File -PathType Leaf)) { throw "Missing archive: $File" }
    $actual = (Get-FileHash -LiteralPath $File -Algorithm SHA256).Hash
    if (-not $Expected) {
        if (-not (Test-Path -LiteralPath ($File + '.receipt.json'))) {
            throw "Unverified cache archive: $File. Supply it explicitly via -...Source or prepare it online."
        }
        $Expected = (Get-Content -LiteralPath ($File + '.receipt.json') -Raw | ConvertFrom-Json).sha256
    }
    if ($actual -ine $Expected) { throw "SHA256 mismatch: $File expected=$Expected actual=$actual" }
}

function Expand-ToolArchive([string]$File, [string]$Destination) {
    if ([IO.Path]::GetExtension($File) -ieq '.zip') {
        # .NET extraction rejects traversal entries; no shell-expanded filenames.
        [IO.Compression.ZipFile]::ExtractToDirectory($File, $Destination)
    } elseif ([IO.Path]::GetExtension($File) -ieq '.7z') {
        $seven = Get-Command 7z.exe -ErrorAction SilentlyContinue
        $exe = if ($seven) { $seven.Source } else { Join-Path $env:ProgramFiles '7-Zip/7z.exe' }
        if (-not (Test-Path -LiteralPath $exe)) { throw "7-Zip needed on packaging machine for $File; alternatively supply an extracted directory or ZIP." }
        $null = Invoke-Checked 'Extract 7z' $exe @('x', '-y', "-o$Destination", $File)
    } else { throw "Source must be a full directory, ZIP or upstream .7z: $File" }
}

function Get-TreeHashes([string]$Directory) {
    $result = @{}
    foreach ($f in Get-ChildItem -LiteralPath $Directory -Recurse -File -Force) {
        $key = $f.FullName.Substring($Directory.TrimEnd('\','/').Length + 1).Replace('\','/')
        if ($key -eq '.portable-receipt.json') { continue }
        $result[$key] = (Get-FileHash -LiteralPath $f.FullName -Algorithm SHA256).Hash
    }
    return $result
}

function Assert-TreeReceipt([string]$Directory) {
    $file = Join-Path $Directory '.portable-receipt.json'
    if (-not (Test-Path -LiteralPath $file)) { throw "Unverified extracted cache: $Directory. Reimport with explicit -...Source." }
    $receipt = Get-Content -LiteralPath $file -Raw | ConvertFrom-Json
    $hashes = Get-TreeHashes $Directory
    if ($hashes.Count -ne @($receipt.files.PSObject.Properties).Count) { throw "Cache file count changed: $Directory" }
    foreach ($p in $receipt.files.PSObject.Properties) {
        if (-not $hashes.ContainsKey($p.Name) -or $hashes[$p.Name] -ine $p.Value) { throw "Cache file changed or missing: $Directory/$($p.Name)" }
    }
}

function Resolve-Asset([string]$Kind, [string]$Source, [string]$ArchiveName) {
    $tag = switch ($Kind) { 'python' {$sources.PythonVersion}; 'cmake' {$sources.CMakeVersion}; 'ninja' {$sources.NinjaVersion};
        'mingw' { $sources.MinGWVersion + '-' + $sources.MinGWVariant }; 'make' {$sources.MakeVersion}; 'arm-gcc' {'10.3-2021.10'};
        'vc-runtime' {$sources.VcRuntimeVersion} }
    $cached = Join-Path $cacheRoot ($Kind + '-' + $tag)
    if (-not $Source -and (Test-Path -LiteralPath $cached)) {
        # A wrong/stale cache never quietly falls through to another version.
        $null = Assert-Asset $Kind $cached
        Assert-TreeReceipt $cached
        return $cached
    }
    $stage = Join-Path $cacheRoot ('.extract-' + $Kind + '-' + [guid]::NewGuid().ToString('N'))
    $replacement = Join-Path $cacheRoot ('.prepared-' + $Kind + '-' + [guid]::NewGuid().ToString('N'))
    $backup = Join-Path $cacheRoot ('.previous-' + $Kind + '-' + [guid]::NewGuid().ToString('N'))
    try {
        if ($Source) { $path = (Resolve-Path -LiteralPath $Source).Path }
        else {
            $path = Join-Path $downloadRoot $ArchiveName
            $expected = if ($sources.Sha256.ContainsKey($ArchiveName)) { $sources.Sha256[$ArchiveName] } else { '' }
            Assert-Archive $path $expected
        }
        if (Test-Path -LiteralPath $path -PathType Container) { $root = Find-AssetRoot $Kind $path; $hash = $null }
        else {
            $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
            $name = [IO.Path]::GetFileName($path)
            if ($sources.Sha256.ContainsKey($name) -and $hash -ine $sources.Sha256[$name]) {
                throw "Pinned source SHA256 mismatch: $path expected=$($sources.Sha256[$name]) actual=$hash"
            }
            New-Item -ItemType Directory -Path $stage | Out-Null
            if ($Kind -eq 'vc-runtime' -and [IO.Path]::GetExtension($path) -ieq '.exe') {
                if ($hash -ine $sources.Sha256[$sources.VcRuntimeArchive]) { throw "Microsoft installer SHA256 mismatch: $path" }
                $seven = Get-Command 7z.exe -ErrorAction SilentlyContinue
                $sevenPath = if ($seven) { $seven.Source } else { Join-Path $env:ProgramFiles '7-Zip/7z.exe' }
                if (-not (Test-Path -LiteralPath $sevenPath)) { throw '7-Zip required on packaging machine to extract Microsoft runtime.' }
                $python = Join-Path $cacheRoot ('python-' + $sources.PythonVersion + '/python.exe')
                $null = Invoke-Checked 'Extract official Microsoft runtime (no installation)' $python @('-B',
                    (Join-Path $PSScriptRoot 'extract_vc_runtime.py'),'--installer',$path,'--output',$stage,'--seven',$sevenPath)
            } else { Expand-ToolArchive $path $stage }
            $root = Find-AssetRoot $Kind $stage
        }
        $actual = Assert-Asset $Kind $root
        Copy-DirectoryContents $root $replacement
        $null = Assert-Asset $Kind $replacement
        $receipt = @{ source = $path; archive_sha256 = $hash; version = ($actual -split "`r?`n")[0]; files = (Get-TreeHashes $replacement) }
        $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $replacement '.portable-receipt.json') -Encoding UTF8
        if (Test-Path -LiteralPath $cached) { Assert-ChildPath $cacheRoot $cached; Move-Item -LiteralPath $cached -Destination $backup }
        try { Move-Item -LiteralPath $replacement -Destination $cached }
        catch { if (Test-Path -LiteralPath $backup) { Move-Item -LiteralPath $backup -Destination $cached }; throw }
        Remove-OutputChild $cacheRoot $backup
        return $cached
    } finally {
        Remove-OutputChild $cacheRoot $stage
        Remove-OutputChild $cacheRoot $replacement
    }
}

function Get-LocalToolInventory {
    $items = @()
    foreach ($name in @('gcc.exe','g++.exe','mingw32-make.exe','arm-none-eabi-gcc.exe','cmake.exe','ninja.exe','python.exe')) {
        foreach ($cmd in @(Get-Command $name -All -CommandType Application -ErrorAction SilentlyContinue)) {
            $path = $cmd.Source
            $item = Get-Item -LiteralPath $path -Force
            if ($item.Target) {
                $target = [string]@($item.Target)[0]
                $path = if ([IO.Path]::IsPathRooted($target)) { $target } else { [IO.Path]::GetFullPath((Join-Path $item.DirectoryName $target)) }
            }
            if ($path -like '*\WindowsApps\*') {
                $items += @{ name=$name;path=$path;complete_and_matching=$false;diagnostic='Windows Store execution alias, not executed' }
                continue
            }
            try {
                $version = Invoke-Checked "Discover $name" $path @('--version')
                $kind = switch ($name) { 'gcc.exe' {'mingw'}; 'g++.exe' {'mingw'}; 'mingw32-make.exe' {'make'};
                    'arm-none-eabi-gcc.exe' {'arm-gcc'}; 'cmake.exe' {'cmake'}; 'ninja.exe' {'ninja'}; 'python.exe' {'python'} }
                $candidate = if ($kind -in @('python','ninja')) { Split-Path $path } else { Split-Path (Split-Path $path) }
                $errorText = $null
                try { $null = Assert-Asset $kind $candidate; $match = $true } catch { $match = $false; $errorText = "$_" }
                $dependencies = @($candidate,(Join-Path $candidate 'bin'),(Join-Path $candidate 'lib'),
                    (Join-Path $candidate 'libexec'),(Join-Path $candidate 'opt/bin'),(Join-Path $candidate 'share')) |
                    Where-Object { Test-Path -LiteralPath $_ -PathType Container }
                $items += @{ name=$name; path=$path; command_path=$cmd.Source; version=$version; sha256=(Get-FileHash -LiteralPath $path).Hash;
                    dependency_directories=@($dependencies);
                    root=$candidate; complete_and_matching=$match; diagnostic=$errorText }
            } catch { $items += @{ name=$name; path=$path; error="$_"; complete_and_matching=$false } }
        }
    }
    return $items
}
