# ECRA Windows Full Portable 交付报告

日期：2026-10-20。基于本地 optimize_cc 工作区。构建、隔离构建、中文/空格路径 ZIP 解压验收均通过；真实 OpenCode 模型复核未计为通过。

## 1. 交付文件

- ZIP：[ECRA-Portable.zip](<H:/global_static_concurrency_design/dist/ECRA-Portable.zip>)
- 绝对路径：`H:\global_static_concurrency_design\dist\ECRA-Portable.zip`
- 大小：**492,679,654 bytes**（469.86 MiB）
- SHA256：`29da91f1a3d4d89dcd329964b7a7d244e9ed86a96839ad3ede7ae9f8bcaa7bdd`
- 文件校验：[SHA256 文件](<H:/global_static_concurrency_design/dist/ECRA-Portable.zip.sha256>)
- 机器可读汇总：[validation.json](<H:/global_static_concurrency_design/dist/ECRA-Portable.validation.json>)
- 新解压前构建目录：`H:\global_static_concurrency_design\dist\delivery-20261020\ECRA-Portable`。原有 `dist/ECRA-Portable` 目录及用户配置保留；旧 ZIP 单独备份，不能把旧目录当成本次新包。

支持 Windows 10 1903+ / Windows 11 x64。官方 ARM 工具链采用原 Win32 host 发行包，在 Windows x64 的系统 WOW64 环境运行。

## 2. 工具版本和来源

| 工具 | 要求 | 实际打包 | 来源 | 匹配 |
|---|---|---|---|---|
| Python | 3.10.9 / Windows x64 | 3.10.9 amd64 embeddable | Python.org 官方归档 | 是 |
| CMake | 3.29.6 | 官方 3.29.6 | Kitware 官方 ZIP，SHA256 对照发布值 | 是；没有 JetBrains build 1 标识 |
| Ninja | 1.13.2 | 1.13.2 | 本地 WinGet 完整安装目录 | 是 |
| MinGW GCC/G++ | 14.2.0 x86_64-mcf-seh-rev0 | 14.2.0，mcf/seh，rt_v12 rev0 / UCRT | MinGW-Builds 官方发布归档 | 是 |
| GNU Make | 4.4.1，x86_64-w64-mingw32 | 同发行版 4.4.1 | 配套 MinGW；仅增加进程 UTF-8 manifest | 是；实现代码段未改变 |
| ARM GCC/G++ | 10.3.1，10.3-2021.10 | 10.3.1 20210824 (release) | 本机完整 GNU Arm Embedded Toolchain 10.3-2021.10 | 是 |
| libclang | 18.1.1 | 18.1.1，实际加载及 AST 解析成功 | PyPI win_amd64 wheel | 是 |
| PyYAML | >=6.0.2,<7 | 6.0.3 | PyPI cp310-cp310-win_amd64 wheel | 是 |
| 必需 MSVC runtime | 与 libclang/Python 兼容 | x64 14.44.35211.0 | 微软官方签名 redist；MSVCP140/VCRUNTIME140/VCRUNTIME140_1 应用目录部署 | 是 |

所有版本均通过运行实际二进制或导入实际依赖核验，没有用配置字符串替代运行检查。GCC 另核验 target、mcf 线程模型、cc1/cc1plus/collect2 和 libgcc/libstdc++ 的解析路径。

本机 CLion 实际是 CMake 3.30.5 build 22、GCC 13.1.0、Make 4.4，不是任务要求的发行包，所以未打包。官方 CMake 的 BSD 版权文件完整保留。

GNU Make 原件 SHA256：`528e0090d25e2b96e122c8e6c0d9e05c452bebde97451d811e157b30c41e5439`。适配后 SHA256：`c76a0b2b6f12807ba2c1458b8b768f71fd6b3392ea2f832723afe2a181e04073`。所有非资源 PE 段完全相同，实际版本仍是 4.4.1；适配配方、原 manifest 和段哈希随包保存。

详细本地来源和归档 SHA256：
```json
{
  "Python": {
    "source": "H:\\global_static_concurrency_design\\.tools-cache\\downloads\\python-3.10.9-embed-amd64.zip",
    "archive_sha256": "8712433E84811FB8FCF877BEABE12F86CB843C94BB1CAC62C43E2D717A87B2AD",
    "version": "Python 3.10.9"
  },
  "CMake": {
    "source": "H:\\global_static_concurrency_design\\.tools-cache\\downloads\\cmake-3.29.6-windows-x86_64.zip",
    "archive_sha256": "5C648EAC06C33477E510BAE14CE1F969E9ABB38992B71F245633B182FCCB474D",
    "version": "cmake version 3.29.6"
  },
  "Ninja": {
    "source": "C:\\Users\\Administrator\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Ninja-build.Ninja_Microsoft.Winget.Source_8wekyb3d8bbwe",
    "archive_sha256": null,
    "version": "1.13.2"
  },
  "MinGW": {
    "source": "H:\\global_static_concurrency_design\\.tools-cache\\downloads\\x86_64-14.2.0-release-mcf-seh-ucrt-rt_v12-rev0.7z",
    "archive_sha256": "80FA0D1DD58C9EED4CA9D21F6E5A83E3262978AED0A2B4994296A0EE5809503E",
    "version": "gcc.exe (x86_64-mcf-seh-rev0, Built by MinGW-Builds project) 14.2.0"
  },
  "ARM GCC": {
    "source": "D:\\gcc-arm-none-eabi-10.3-2021.10",
    "archive_sha256": null,
    "version": "arm-none-eabi-gcc.exe (GNU Arm Embedded Toolchain 10.3-2021.10) 10.3.1 20210824 (release)"
  },
  "VC Runtime": {
    "source": "H:\\global_static_concurrency_design\\.tools-cache\\downloads\\vc_redist.x64.exe",
    "archive_sha256": "CC0FF0EB1DC3F5188AE6300FAEF32BF5BEEBA4BDD6E8E445A9184072096B713B",
    "version": "Microsoft VC++ x64 Runtime 14.44.35211.0"
  }
}
```

## 3. 构建与测试结果

| 测试 | 实际结果 |
|---|---|
| 版本一致性、Python wheel 兼容及 libclang 加载 | 原目录和 ZIP 解压目录均通过 |
| MinGW Makefiles 本机 C/C++ | Configure/Build/运行均退出 0；C++ 包括 std::thread/vector/numeric，校验运行库 |
| MinGW Makefiles + ARM GCC | C/C++/ASM 配置编译链接成功，生成真实 ARM ELF，Make 与编译器路径均校验 |
| Ninja 回归 | 独立目录 Configure/Build/运行均退出 0 |
| ARM + Ninja 额外回归 | 独立项目用 ARM GCC 10.3.1 + Ninja 编译链接并完成 2 个 TU 的 AST 扫描；退出 2 为待复核语义 |
| 无外部开发工具 PATH | 全部验收子进程仅内置工具和 Windows 系统目录；未使用外部编译器 |
| ZIP 完整性 | 逐文件 SHA256、283 个 EXE/DLL/PYD 的正常和延迟导入依赖检查通过 |
| 中文和空格路径 | 工具解压根、原生项目根、ARM 项目根都包含中文/空格，真实构建及扫描通过 |
| ECRA CLI | ecra.cmd --help/doctor/run --no-review/review/report/status 均已实际执行 |
| build:false | 生成数据库且完成静态扫描；对应目录没有 firmware.elf |
| 原有及新增回归 | 736 项：734 通过，2 项原有真实 OpenCode opt-in 用例跳过 |
| 缓存、目录和二进制适配负向测试 | 已验证缓存文件篡改、旧 Make/Generator、未缓存的外部编译器、正式目录保护、越界清理、已有用户配置保护、别名冲突、缺 DLL、错误适配源 SHA 拒绝 |
| 显式 libclang_file | 新进程 doctor 回归退出 0，正确加载配置的库 |
| 离线缓存检查 | prepare_portable_cache.ps1 -OfflineCheck 退出 0 |

静态测试故意包含并发写入变量；run --no-review 和禁用复核的 review/report 返回 2，表示保留待复核结论，不表示编译失败。doctor 配置检查和 status 返回 0。报告 analysis_status 为 INCOMPLETE 不等于解析失败：两份验收均实际解析 2/2 C/C++ 翻译单元，覆盖率 100%，失败/部分解析均为 0。

```json
{
  "uncompressed": {
    "translation_units_total": 2,
    "translation_units_parsed": 2,
    "translation_units_failed": 0,
    "translation_units_partial": 0,
    "parse_coverage_percent": 100.0,
    "external_tools": []
  },
  "zip-extracted": {
    "translation_units_total": 2,
    "translation_units_parsed": 2,
    "translation_units_failed": 0,
    "translation_units_partial": 0,
    "parse_coverage_percent": 100.0,
    "external_tools": []
  }
}
```

OpenCode 1.18.35 在本机独立安装，--version 已核验。真实模型调用未执行，两个既有 live opt-in 用例仍明确跳过，不能宣称模型提供商和真实 AI 复核验收通过。OpenCode/Node/npm 未随包分发。

全套回归日志：[regression.log](<H:/global_static_concurrency_design/build/portable-delivery-final-regression.log>)。
离线检查日志：[offline.log](<H:/global_static_concurrency_design/build/portable-delivery-offline.log>)。
Windows PowerShell 完整打包日志：[build.log](<H:/global_static_concurrency_design/build/portable-delivery-build.log>)。
显式 libclang 配置回归：[custom-libclang.log](<H:/global_static_concurrency_design/build/portable-custom-clang-doctor.log>)。

额外 ARM + Ninja 命令和结果：[arm-ninja-extra-result.json](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/arm-ninja-extra-result.json>)；[完整日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/arm-ninja-extra.log>)。

## 4. 每条验收命令、退出码和日志

### uncompressed

实际工具根：`H:\global_static_concurrency_design\dist\delivery-20261020\ECRA-Portable`。结果：**PASS**。

[完整 argv/Windows 命令行与退出码 JSON](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/acceptance.json>)

| 检查 | 退出码 | 关键日志 |
|---|---|---|
| Python | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/00-Python.log>) |
| cmake | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/01-cmake.log>) |
| arm-none-eabi-gcc | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/02-arm-none-eabi-gcc.log>) |
| g++ | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/03-g__.log>) |
| mingw32-make | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/04-mingw32-make.log>) |
| gcc | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/05-gcc.log>) |
| ninja | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/06-ninja.log>) |
| Python dependencies and AST | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/07-Python_dependencies_and_AST.log>) |
| MinGW Makefiles configure | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/08-MinGW_Makefiles_configure.log>) |
| MinGW Makefiles build | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/09-MinGW_Makefiles_build.log>) |
| MinGW Makefiles execute | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/10-MinGW_Makefiles_execute.log>) |
| Ninja configure | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/11-Ninja_configure.log>) |
| Ninja build | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/12-Ninja_build.log>) |
| Ninja execute | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/13-Ninja_execute.log>) |
| ecra.cmd help | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/14-ecra_cmd_help.log>) |
| ecra.cmd doctor configure only | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/15-ecra_cmd_doctor_configure_only.log>) |
| ecra.cmd run no review real ARM build and scan | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/16-ecra_cmd_run_no_review_real_ARM_build_and_scan.log>) |
| ecra.cmd review disabled interface | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/17-ecra_cmd_review_disabled_interface.log>) |
| ecra.cmd report | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/18-ecra_cmd_report.log>) |
| ecra.cmd status | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/19-ecra_cmd_status.log>) |
| ecra.cmd build false | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/uncompressed/20-ecra_cmd_build_false.log>) |

实际参数数组（保留完整路径，不使用概略命令代替）：
```json
[
  {
    "label": "Python",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\runtime\\python.exe",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "cmake",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\cmake\\bin\\cmake.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "arm-none-eabi-gcc",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\arm-gcc\\bin\\arm-none-eabi-gcc.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "g++",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\g++.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "mingw32-make",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\mingw32-make.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "gcc",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\gcc.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "ninja",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\ninja\\ninja.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "Python dependencies and AST",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\runtime\\python.exe",
      "-B",
      "-c",
      "import sys, struct, json, sqlite3, ssl, multiprocessing, yaml\nfrom importlib.metadata import version\nfrom clang import cindex\ncindex.Index.create()\nassert struct.calcsize('P') == 8\nprint(json.dumps({'python':sys.version.split()[0], 'PyYAML':version('PyYAML'), 'libclang':version('libclang'), 'libclang_loaded':True}))\n"
    ],
    "exit_code": 0
  },
  {
    "label": "MinGW Makefiles configure",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\cmake\\bin\\cmake.exe",
      "-S",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\05079ce690fb5c0f94ac624c9a1c3340",
      "-B",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\05079ce690fb5c0f94ac624c9a1c3340\\mingw",
      "-G",
      "MinGW Makefiles",
      "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
      "-DCMAKE_MAKE_PROGRAM:FILEPATH=H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\mingw32-make.exe",
      "-DCMAKE_C_COMPILER:FILEPATH=H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\gcc.exe",
      "-DCMAKE_CXX_COMPILER:FILEPATH=H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\g++.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "MinGW Makefiles build",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\cmake\\bin\\cmake.exe",
      "--build",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\05079ce690fb5c0f94ac624c9a1c3340\\mingw",
      "--verbose"
    ],
    "exit_code": 0
  },
  {
    "label": "MinGW Makefiles execute",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\native C C++ 中文\\mingw\\native.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "Ninja configure",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\cmake\\bin\\cmake.exe",
      "-S",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\05079ce690fb5c0f94ac624c9a1c3340",
      "-B",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\05079ce690fb5c0f94ac624c9a1c3340\\ninja",
      "-G",
      "Ninja",
      "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
      "-DCMAKE_MAKE_PROGRAM:FILEPATH=H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\ninja\\ninja.exe",
      "-DCMAKE_C_COMPILER:FILEPATH=H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\gcc.exe",
      "-DCMAKE_CXX_COMPILER:FILEPATH=H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\mingw\\bin\\g++.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "Ninja build",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\tools\\cmake\\bin\\cmake.exe",
      "--build",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\05079ce690fb5c0f94ac624c9a1c3340\\ninja",
      "--verbose"
    ],
    "exit_code": 0
  },
  {
    "label": "Ninja execute",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\native C C++ 中文\\ninja\\native.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd help",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\ecra.cmd\" --help\""
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd doctor configure only",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\ecra.cmd doctor --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\fixture-semantics.json\""
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd run no review real ARM build and scan",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\ecra.cmd run --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\fixture-semantics.json --no-review\""
    ],
    "exit_code": 2
  },
  {
    "label": "ecra.cmd review disabled interface",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\ecra.cmd review --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\fixture-semantics.json\""
    ],
    "exit_code": 2
  },
  {
    "label": "ecra.cmd report",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\ecra.cmd report --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\fixture-semantics.json\""
    ],
    "exit_code": 2
  },
  {
    "label": "ecra.cmd status",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\ecra.cmd status --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\fixture-semantics.json --json\""
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd build false",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\ECRA-Portable\\ecra.cmd run --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\uncompressed\\configure-only.json --no-review\""
    ],
    "exit_code": 2
  }
]
```

### zip-extracted

实际工具根：`H:\global_static_concurrency_design\dist\delivery-20261020\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\ECRA-Portable`。结果：**PASS**。

[完整 argv/Windows 命令行与退出码 JSON](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/acceptance.json>)

| 检查 | 退出码 | 关键日志 |
|---|---|---|
| Python | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/00-Python.log>) |
| cmake | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/01-cmake.log>) |
| arm-none-eabi-gcc | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/02-arm-none-eabi-gcc.log>) |
| g++ | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/03-g__.log>) |
| mingw32-make | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/04-mingw32-make.log>) |
| gcc | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/05-gcc.log>) |
| ninja | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/06-ninja.log>) |
| Python dependencies and AST | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/07-Python_dependencies_and_AST.log>) |
| MinGW Makefiles configure | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/08-MinGW_Makefiles_configure.log>) |
| MinGW Makefiles build | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/09-MinGW_Makefiles_build.log>) |
| MinGW Makefiles execute | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/10-MinGW_Makefiles_execute.log>) |
| Ninja configure | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/11-Ninja_configure.log>) |
| Ninja build | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/12-Ninja_build.log>) |
| Ninja execute | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/13-Ninja_execute.log>) |
| ecra.cmd help | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/14-ecra_cmd_help.log>) |
| ecra.cmd doctor configure only | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/15-ecra_cmd_doctor_configure_only.log>) |
| ecra.cmd run no review real ARM build and scan | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/16-ecra_cmd_run_no_review_real_ARM_build_and_scan.log>) |
| ecra.cmd review disabled interface | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/17-ecra_cmd_review_disabled_interface.log>) |
| ecra.cmd report | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/18-ecra_cmd_report.log>) |
| ecra.cmd status | 0 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/19-ecra_cmd_status.log>) |
| ecra.cmd build false | 2 | [日志](<H:/global_static_concurrency_design/dist/delivery-20261020/portable-evidence/zip-extracted/20-ecra_cmd_build_false.log>) |

实际参数数组（保留完整路径，不使用概略命令代替）：
```json
[
  {
    "label": "Python",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\runtime\\python.exe",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "cmake",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\cmake\\bin\\cmake.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "arm-none-eabi-gcc",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\arm-gcc\\bin\\arm-none-eabi-gcc.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "g++",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\g++.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "mingw32-make",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\mingw32-make.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "gcc",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\gcc.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "ninja",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\ninja\\ninja.EXE",
      "--version"
    ],
    "exit_code": 0
  },
  {
    "label": "Python dependencies and AST",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\runtime\\python.exe",
      "-B",
      "-c",
      "import sys, struct, json, sqlite3, ssl, multiprocessing, yaml\nfrom importlib.metadata import version\nfrom clang import cindex\ncindex.Index.create()\nassert struct.calcsize('P') == 8\nprint(json.dumps({'python':sys.version.split()[0], 'PyYAML':version('PyYAML'), 'libclang':version('libclang'), 'libclang_loaded':True}))\n"
    ],
    "exit_code": 0
  },
  {
    "label": "MinGW Makefiles configure",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\cmake\\bin\\cmake.exe",
      "-S",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\5ee8f038887926939573a3cfb5bc2c98",
      "-B",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\5ee8f038887926939573a3cfb5bc2c98\\mingw",
      "-G",
      "MinGW Makefiles",
      "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
      "-DCMAKE_MAKE_PROGRAM:FILEPATH=C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\mingw32-make.exe",
      "-DCMAKE_C_COMPILER:FILEPATH=C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\gcc.exe",
      "-DCMAKE_CXX_COMPILER:FILEPATH=C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\g++.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "MinGW Makefiles build",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\cmake\\bin\\cmake.exe",
      "--build",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\5ee8f038887926939573a3cfb5bc2c98\\mingw",
      "--verbose"
    ],
    "exit_code": 0
  },
  {
    "label": "MinGW Makefiles execute",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\native C C++ 中文\\mingw\\native.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "Ninja configure",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\cmake\\bin\\cmake.exe",
      "-S",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\5ee8f038887926939573a3cfb5bc2c98",
      "-B",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\5ee8f038887926939573a3cfb5bc2c98\\ninja",
      "-G",
      "Ninja",
      "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
      "-DCMAKE_MAKE_PROGRAM:FILEPATH=C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\ninja\\ninja.exe",
      "-DCMAKE_C_COMPILER:FILEPATH=C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\gcc.exe",
      "-DCMAKE_CXX_COMPILER:FILEPATH=C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\mingw\\bin\\g++.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "Ninja build",
    "command": [
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\638d894f0ba535aa979aa78b5fd459f9\\tools\\cmake\\bin\\cmake.exe",
      "--build",
      "C:\\Users\\ADMINI~1\\AppData\\Local\\Temp\\ECRA-P~1\\5ee8f038887926939573a3cfb5bc2c98\\ninja",
      "--verbose"
    ],
    "exit_code": 0
  },
  {
    "label": "Ninja execute",
    "command": [
      "H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\native C C++ 中文\\ninja\\native.exe"
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd help",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\\ECRA-Portable\\ecra.cmd\" --help\""
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd doctor configure only",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\\ECRA-Portable\\ecra.cmd\" doctor --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\fixture-semantics.json\""
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd run no review real ARM build and scan",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\\ECRA-Portable\\ecra.cmd\" run --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\fixture-semantics.json --no-review\""
    ],
    "exit_code": 2
  },
  {
    "label": "ecra.cmd review disabled interface",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\\ECRA-Portable\\ecra.cmd\" review --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\fixture-semantics.json\""
    ],
    "exit_code": 2
  },
  {
    "label": "ecra.cmd report",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\\ECRA-Portable\\ecra.cmd\" report --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\fixture-semantics.json\""
    ],
    "exit_code": 2
  },
  {
    "label": "ecra.cmd status",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\\ECRA-Portable\\ecra.cmd\" status --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\fixture-semantics.json --json\""
    ],
    "exit_code": 0
  },
  {
    "label": "ecra.cmd build false",
    "command": [
      "C:\\Windows\\system32\\cmd.exe",
      "/d",
      "/s",
      "/c",
      "\"\"H:\\global_static_concurrency_design\\dist\\delivery-20261020\\.zip-check 空格 中文-f581dedd714b4f07b8d8f1902a478cfa\\ECRA-Portable\\ecra.cmd\" run --config H:\\global_static_concurrency_design\\dist\\delivery-20261020\\portable-evidence\\zip-extracted\\configure-only.json --no-review\""
    ],
    "exit_code": 2
  }
]
```

## 5. 代码、配置及异常处理

[逐文件修改清单、原架构审计及设计说明](<H:/global_static_concurrency_design/docs/portable-audit.md>)

配置、requirements 和入口的字节 SHA256 已与新包一致；Git 对这些源文件没有修改：
```json
{
  "config/semantics.yaml": "8a9139813876979a7e0f65ad9fcd33a5ba8598bb6634627b5220d9bbdf1b4f42",
  "requirements.txt": "6dc32b8286cd980da63bb0db2c5920d43fc9559b814ce88db2b03f6be9afeee3",
  "run_ecra.py": "336fd94c4d03ecdb9535515cf9bd41a4796c88ffe96933fcfbbd045ffbb38a18"
}
```

解决的真实阻塞包括：旧版本缓存、pip 缺少验证凭据、libclang 缺 MSVCP140、ARM 可选 Python 2 调试器依赖、MinGW GDB 的 opt/bin DLL 路径、CMake 非缓存编译器路径，以及 GNU Make 对中文 UTF-8 生成文件的代码页问题。修复后均重新测试，没有忽略失败后发布 ZIP。

没有未解决的必需工具版本或 DLL 缺失。上游可选的 ARM Python 2.7 调试器 gdb-py/gdb-add-index-py 已明确排除，标准 GDB、编译器、binutils、头文件和库保留。GNU Make 适配要求 Windows 10 1903+；路径兼容缓存需要可写、可取得 ASCII 名称的 TEMP。外部工具链必须显式选择并接受诊断。

MSVC runtime 使用微软官方来源并保留许可证；向第三方再分发须具备对应 Visual Studio 许可赋予的权利，见 https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files 。这次仅创建本地交付文件，没有发布到外部服务。

## 6. 用户操作

已准备好缓存时，在源仓库用新输出目录打包，避免覆盖已有用户配置：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\prepare_portable_cache.ps1 -OfflineCheck
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_portable.ps1 -OutputDir .\dist-new
```

首次联网准备可去掉 -OfflineCheck。可显式提供 -PythonSource/-CMakeSource/-NinjaSource/-MinGWSource/-MinGWMakeSource/-ArmGccSource/-VcRuntimeSource。来源必须完整、版本匹配；不会自动降级。

在目标电脑解压 ZIP 到新目录，保留整个目录结构；编辑 config/semantics.yaml 的 project.root，按真实工程选择 MinGW Makefiles 和 ARM 工具链，初次选用新的 build/ecra。随后：

```powershell
.\ecra.cmd doctor
.\ecra.cmd run --no-review
.\ecra.cmd report
.\ecra.cmd status
```

需要 AI 复核时独立安装、配置并认证 OpenCode，启用 review.enabled，再执行 .\ecra.cmd review。更多说明见包内 README.txt。

再次自检原始解压副本（尚未修改出厂配置，工作目录必须不存在）：

```powershell
.\runtime\python.exe -B .\validate_portable.py --bundle . --work C:\Temp\ecra-check-new
```
