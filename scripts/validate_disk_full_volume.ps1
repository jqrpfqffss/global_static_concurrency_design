# Creates/formats ONLY a new256MiB VHD; never selects a host disk by guessed number.
# Requires an elevated Windows PowerShell7 session. Every attempt is retained.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Engine,
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$WorkRoot,
    [string]$Python,
    [string]$RuntimePython
)
$ErrorActionPreference = 'Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'An elevated session is required to create this owned virtual test volume' }
$taskWork = [IO.Path]::GetFullPath($WorkRoot)
$taskBase = Split-Path -Parent $taskWork
if (-not (Test-Path -LiteralPath $taskBase -PathType Container)) { throw 'Validation parent must already exist' }
if (Test-Path -LiteralPath $taskWork) { throw 'Preserve existing disk-full attempts; workspace already exists' }
$taskCheck = $taskBase
while ($taskCheck) {
    if (((Get-Item -LiteralPath $taskCheck -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Validation path has a reparse-point ancestor' }
    $taskCheck = Split-Path -Parent $taskCheck
}
$taskEngine = (Resolve-Path -LiteralPath $Engine).Path
$taskPackage = (Resolve-Path -LiteralPath $Package).Path
if (-not (Test-Path -LiteralPath (Join-Path $taskEngine 'ecra/studio/server.py') -PathType Leaf)) { throw 'Expected ECRA runtime not found' }
if ($taskWork.StartsWith($taskEngine.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Validation data must be outside the program directory' }
if ($Python) { $taskPython = (Resolve-Path -LiteralPath $Python).Path } else {
    $taskPython = (py -3.10 -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Host Python3.10 unavailable' }
}
if ($RuntimePython) { $taskRuntime = (Resolve-Path -LiteralPath $RuntimePython).Path } else { $taskRuntime = (Resolve-Path -LiteralPath (Join-Path $taskEngine 'runtime/python.exe')).Path }
$taskHarness = Join-Path $PSScriptRoot 'validate_disk_full_ui.py'
if (-not (Test-Path -LiteralPath $taskHarness -PathType Leaf)) { throw 'Validation harness must exist before image creation' }
$taskWorkItem = New-Item -ItemType Directory -Path $taskWork
if (($taskWorkItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Image workspace is a reparse point' }
$taskImage = Join-Path $taskWork 'owned-test-volume.vhd'
if (Test-Path -LiteralPath $taskImage) { throw 'Never attach or format an existing image' }
$taskState = @{ passed=$false; status='CREATING_OWNED_IMAGE'; image=$taskImage; scope='New256MiB file-backed virtual NTFS only. Not a physical disk-full/G4/32GB/second-PC claim. Image and all evidence retained.' }
$taskMounted = $false
function Save-TaskState { $taskState | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath (Join-Path $taskWork 'lifecycle.json') -Encoding utf8 }
Save-TaskState
try {
    $taskLetters = @((Get-Volume | Where-Object DriveLetter | ForEach-Object { [string]$_.DriveLetter }) + (Get-PSDrive -PSProvider FileSystem | ForEach-Object Name))
    $taskCreate = Join-Path $taskWork 'create-image.txt'
    ('create vdisk file="{0}" maximum=256 type=expandable' -f $taskImage) + "`r`nexit`r`n" | Set-Content -LiteralPath $taskCreate -Encoding ascii
    & (Join-Path $env:SystemRoot 'System32/diskpart.exe') /s $taskCreate *> (Join-Path $taskWork 'create-image.log')
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $taskImage -PathType Leaf)) { throw 'Owned image creation failed; do not touch any disk' }
    $taskAttached = Mount-DiskImage -ImagePath $taskImage -StorageType VHD -Access ReadWrite -NoDriveLetter -PassThru
    $taskMounted = $true
    $taskAssociated = Get-DiskImage -ImagePath $taskImage
    if (-not $taskAssociated.Attached -or [IO.Path]::GetFullPath($taskAssociated.ImagePath) -ne $taskImage) { throw 'Image association mismatch' }
    $taskDisks = @(Get-DiskImage -ImagePath $taskImage | Get-Disk)
    if ($taskDisks.Count -ne 1) { throw 'Image must identify exactly one disk' }
    $taskDisk = $taskDisks[0]
    if ($taskDisk.IsBoot -or $taskDisk.IsSystem -or $taskDisk.PartitionStyle -ne 'RAW' -or $taskDisk.Size -ne 256MB -or $taskDisk.BusType.ToString() -notin @('File Backed Virtual','FileBackedVirtual')) { throw 'Refuse to initialize anything except this new small RAW file-backed image' }
    $taskState.initial_disk = $taskDisk | Select-Object Number,Path,UniqueId,Size,BusType,PartitionStyle,IsBoot,IsSystem
    Save-TaskState
    $taskInitialized = Initialize-Disk -InputObject $taskDisk -PartitionStyle MBR -PassThru -Confirm:$false
    $taskPartition = New-Partition -InputObject $taskInitialized -UseMaximumSize -AssignDriveLetter
    $taskRecheck = Get-DiskImage -ImagePath $taskImage | Get-Disk
    if ($taskRecheck.Number -ne $taskDisk.Number -or $taskRecheck.IsBoot -or $taskRecheck.IsSystem -or $taskRecheck.UniqueId -ne $taskInitialized.UniqueId -or $taskPartition.DiskNumber -ne $taskRecheck.Number -or @(Get-Partition -DiskNumber $taskRecheck.Number).Count -ne 1 -or -not $taskPartition.DriveLetter -or [string]$taskPartition.DriveLetter -in $taskLetters) { throw 'Rechecked image/partition/unused drive identity mismatch; never format' }
    $taskState.partition = $taskPartition | Select-Object DiskNumber,PartitionNumber,DiskId,DriveLetter,Size,AccessPaths
    $taskState.status = 'VERIFIED_NEW_IMAGE_BEFORE_FORMAT'
    Save-TaskState
    $taskVolume = Format-Volume -Partition $taskPartition -FileSystem NTFS -NewFileSystemLabel 'ECRA-DISKFULL-V1' -AllocationUnitSize 4096 -Force -Confirm:$false
    $taskRoot = '{0}:\' -f $taskPartition.DriveLetter
    $taskOwned = Join-Path $taskRoot 'ECRA-DISKFULL-V1'
    New-Item -ItemType Directory -Path $taskOwned | Out-Null
    $taskNonce = [Guid]::NewGuid().ToString('N')
    [IO.File]::WriteAllText((Join-Path $taskOwned 'owner.txt'),$taskNonce)
    $taskMetadata = @{ image=$taskImage; drive_root=$taskRoot; owned_root=$taskOwned; data_root=(Join-Path $taskOwned 'data'); filler=(Join-Path $taskOwned 'filler.bin'); marker=(Join-Path $taskOwned 'owner.txt'); nonce=$taskNonce; total_bytes=$taskVolume.Size; filesystem=$taskVolume.FileSystem; volume_id=$taskVolume.UniqueId; disk_number=$taskRecheck.Number; disk_unique_id=$taskRecheck.UniqueId }
    $taskMetadata | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskWork 'volume.json') -Encoding utf8
    $taskState.status='RUNNING_REAL_NTFS_FULL_UI_TEST'; Save-TaskState
    & $taskPython -B -X utf8 $taskHarness --volume (Join-Path $taskWork 'volume.json') --work (Join-Path $taskWork 'harness') --evidence (Join-Path $taskWork 'evidence') --engine $taskEngine --package $taskPackage --python $taskRuntime *> (Join-Path $taskWork 'harness.log')
    $taskState.harness_exit_code = $LASTEXITCODE
    $taskState.passed = ($LASTEXITCODE -eq 0)
    $taskState.status = if ($taskState.passed) { 'PASS_SCOPED' } else { 'FAIL' }
} catch {
    $taskState.status='FAIL';$taskState.error=$_.Exception.ToString()
} finally {
    if ($taskMounted) {
        try {
            $taskVerifyImage = Get-DiskImage -ImagePath $taskImage
            if ([IO.Path]::GetFullPath($taskVerifyImage.ImagePath) -ne $taskImage) { throw 'Refuse detach after image-path mismatch' }
            Dismount-DiskImage -ImagePath $taskImage -StorageType VHD -Confirm:$false
            $taskState.detached = -not (Get-DiskImage -ImagePath $taskImage).Attached
            if (-not $taskState.detached) { throw 'Owned validation image remained attached' }
        } catch { $taskState.detach_error=$_.Exception.ToString();$taskState.passed=$false;$taskState.status='FAIL_DETACH' }
    }
    Save-TaskState
}
if (-not $taskState.passed) { exit 1 }
