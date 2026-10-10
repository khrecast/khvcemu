# Puts the prebuilt libunicorn.so (ARM-only, arm64-v8a) where the app build expects it.
#   .\android\fetch_unicorn.ps1 [path\to\libunicorn.so]
# The library is NOT committed. For now it is the one built on the phone in Termux by
# android/spike/termux_spike.sh (copied to the PC with adb), kept at C:\Android\libs\arm64-v8a\libunicorn.so.
# Building it from Windows with the NDK does not work (see android/NOTES.md, chunk 3).
param([string]$Source = "C:\Android\libs\arm64-v8a\libunicorn.so")
if (-not (Test-Path $Source)) { throw "No ${Source}: build it in Termux (android/spike/termux_spike.sh) and adb pull it." }
$dest = Join-Path $PSScriptRoot "app\src\main\jniLibs\arm64-v8a"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item $Source (Join-Path $dest "libunicorn.so") -Force
$h = (Get-FileHash (Join-Path $dest "libunicorn.so") -Algorithm SHA256).Hash
Write-Host "libunicorn.so -> $dest  (sha256 $h)"
