# Puts Unicorn where the app build expects it: the prebuilt libunicorn.so (ARM guest only) for each ABI, and the pure-Python binding.
#   .\android\fetch_unicorn.ps1 [-Source path\to\arm64\libunicorn.so] [-Binding path\to\unicorn-source\bindings\python\unicorn] [-SourceX86 path\to\x86_64\libunicorn.so]
# Neither is committed (Unicorn is GPLv2; see android/NOTES.md). The libraries are kept outside the repository, under
# $env:ANDROID_ROOT (default C:\Android), the same folder android/tools/build_unicorn_docker.py --install writes to:
#   <root>\libs\arm64-v8a\libunicorn.so   for now still the one built on the phone in Termux (android/build_unicorn_termux.sh)
#   <root>\libs\x86_64\libunicorn.so      built with the Linux NDK in Docker by android/tools/build_unicorn_docker.py
# (that script also builds an arm64-v8a library into <root>\libs\docker\; android/NOTES.md says how to switch to it).
# Each library is compared with the SHA-256 of the known builds (below, and in android/NOTES.md); another file is copied anyway
# but with a loud warning, so a rebuild with other options or another NDK cannot slip in unnoticed.
# The binding comes from the Unicorn 2.1.4 source checkout (git clone --branch 2.1.4) at <root>\src\unicorn.
param(
    [string]$Source = "",
    [string]$Binding = "",
    [string]$SourceX86 = ""
)
$root = if ($env:ANDROID_ROOT) { $env:ANDROID_ROOT } else { "C:\Android" }
if (-not $Source) { $Source = Join-Path $root "libs\arm64-v8a\libunicorn.so" }
if (-not $SourceX86) { $SourceX86 = Join-Path $root "libs\x86_64\libunicorn.so" }
if (-not $Binding) { $Binding = Join-Path $root "src\unicorn\bindings\python\unicorn" }
$known = @{
    "arm64-v8a" = @(
        "7CDDE39921149A95B9358DEAA37056AF50B1C9935B2761FA3EE2ECBCD0BFCA72",   # Termux on the S23 (2026-10-10), what the app ships today
        "ACDC11C0C2807B87C6CB960B073571F0D3C462B319D94C7609607A67D9D03516"    # build_unicorn_docker.py, NDK r28c (2026-11-03)
    )
    "x86_64" = @(
        "A425CF5231901E9719D7D5594987D19BC944E1D40FDA65037A32B842FE790690"    # build_unicorn_docker.py, NDK r28c (2026-11-03)
    )
}
if (-not (Test-Path $Source)) { throw "No ${Source}: build it (python -I android/tools/build_unicorn_docker.py, or Termux) first." }
if (-not (Test-Path $SourceX86)) { throw "No ${SourceX86}: build it with python -I android/tools/build_unicorn_docker.py --install x86_64." }
if (-not (Test-Path $Binding)) { throw "No ${Binding}: clone Unicorn 2.1.4 (git clone --depth 1 --branch 2.1.4 https://github.com/unicorn-engine/unicorn.git)." }
foreach ($pair in @(@("arm64-v8a", $Source), @("x86_64", $SourceX86))) {
    $abi = $pair[0]
    $h = (Get-FileHash $pair[1] -Algorithm SHA256).Hash
    if ($known[$abi] -notcontains $h) {
        Write-Warning "=================================================================="
        Write-Warning "$abi libunicorn.so is NOT a known build: $($pair[1])"
        Write-Warning "sha256 $h"
        Write-Warning "Known: $($known[$abi] -join ', '). Copied anyway; check it before a release."
        Write-Warning "=================================================================="
    }
    $dest = Join-Path $PSScriptRoot ("app\src\main\jniLibs\" + $abi)
    New-Item -ItemType Directory -Force $dest | Out-Null
    Copy-Item $pair[1] (Join-Path $dest "libunicorn.so") -Force
    Write-Host "libunicorn.so ($abi) -> $dest  (sha256 $h)"
}
$py = Join-Path $PSScriptRoot "app\src\main\python\unicorn"
if (Test-Path $py) { Remove-Item -Recurse -Force $py }
Copy-Item $Binding $py -Recurse -Force
Get-ChildItem $py -Recurse -Include "__pycache__" -Directory | Remove-Item -Recurse -Force
Get-ChildItem $py -Recurse -Include "*.so*", "*.dll", "*.dylib" -File | Remove-Item -Force
Write-Host "Python binding -> $py"
