param([Parameter(Mandatory=$true)][string]$ProjectRoot)

$root = (Resolve-Path -LiteralPath $ProjectRoot -ErrorAction Stop).Path.TrimEnd('\', '/')
$expected = @('.ecra', 'build/manual')
foreach ($relative in $expected) {
    $candidate = Join-Path $root $relative
    if (-not (Test-Path -LiteralPath $candidate)) { continue }
    $resolved = (Resolve-Path -LiteralPath $candidate -ErrorAction Stop).Path
    $intended = [System.IO.Path]::GetFullPath($candidate)
    $prefix = $root + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $resolved.Equals($intended, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside configured project: $resolved"
    }
    Write-Output "Removing $resolved"
    Remove-Item -LiteralPath $resolved -Recurse -Force -ErrorAction Stop
}
