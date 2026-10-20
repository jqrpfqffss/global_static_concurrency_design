@{
    PythonVersion = '3.10.9'
    PythonArchive = 'python-3.10.9-embed-amd64.zip'
    PythonUrl = 'https://www.python.org/ftp/python/3.10.9/python-3.10.9-embed-amd64.zip'

    CMakeVersion = '3.29.6'
    CMakeArchive = 'cmake-3.29.6-windows-x86_64.zip'
    CMakeUrl = 'https://github.com/Kitware/CMake/releases/download/v3.29.6/cmake-3.29.6-windows-x86_64.zip'
    CMakeChecksumUrl = 'https://github.com/Kitware/CMake/releases/download/v3.29.6/cmake-3.29.6-SHA-256.txt'

    NinjaVersion = '1.13.2'
    NinjaArchive = 'ninja-win-1.13.2.zip'
    NinjaUrl = 'https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip'
    NinjaLicenseUrl = 'https://raw.githubusercontent.com/ninja-build/ninja/v1.13.2/COPYING'
    NinjaLicenseArchive = 'ninja-1.13.2-COPYING.txt'

    MinGWVersion = '14.2.0'
    MinGWVariant = 'x86_64-mcf-seh-rev0'
    MinGWArchive = 'x86_64-14.2.0-release-mcf-seh-ucrt-rt_v12-rev0.7z'
    MinGWUrl = 'https://github.com/niXman/mingw-builds-binaries/releases/download/14.2.0-rt_v12-rev0/x86_64-14.2.0-release-mcf-seh-ucrt-rt_v12-rev0.7z'
    MinGWReleaseUrl = 'https://github.com/niXman/mingw-builds-binaries/releases/tag/14.2.0-rt_v12-rev0'
    MakeVersion = '4.4.1'
    MakePlatform = 'x86_64-w64-mingw32'
    # Make normally comes from the complete MinGW distribution. A separate
    # local directory/ZIP is accepted only after the same runtime/build checks.
    MakeArchive = 'mingw-make-4.4.1-win64.zip'

    ArmGccVersion = '10.3.1'
    ArmGccRelease = 'GNU Arm Embedded Toolchain 10.3-2021.10'
    ArmGccArchive = 'gcc-arm-none-eabi-10.3-2021.10-win32.zip'
    ArmGccUrl = 'https://developer.arm.com/-/media/Files/downloads/gnu-rm/10.3-2021.10/gcc-arm-none-eabi-10.3-2021.10-win32.zip'

    PipVersion = '25.2'
    PipWheel = 'pip-25.2-py3-none-any.whl'
    PipMetadataUrl = 'https://pypi.org/pypi/pip/25.2/json'

    LibClangVersion = '18.1.1'
    PyYamlVersion = '6.0.3'
    VcRuntimeVersion = '14.44.35211.0'
    VcRuntimeArchive = 'vc-redist-14.44.35211.0-x64.exe'
    # Reject a future changed redirect by pinned version AND SHA256.
    VcRuntimeUrl = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
    # Publisher SHA256 values, when available, take precedence over cache receipts.
    # Other official TLS downloads receive a SHA256 receipt; every later reuse
    # verifies it. Local inputs record their own provenance and full file hashes.
    Sha256 = @{
        'python-3.10.9-embed-amd64.zip' = '8712433e84811fb8fcf877beabe12f86cb843c94bb1cac62c43e2d717a87b2ad'
        'cmake-3.29.6-windows-x86_64.zip' = '5c648eac06c33477e510bae14ce1f969e9abb38992b71f245633b182fccb474d'
        'x86_64-14.2.0-release-mcf-seh-ucrt-rt_v12-rev0.7z' = '80fa0d1dd58c9eed4ca9d21f6e5a83e3262978aed0a2b4994296a0ee5809503e'
        'vc-redist-14.44.35211.0-x64.exe' = 'cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b'
    }
}
