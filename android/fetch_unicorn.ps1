# Puts Unicorn where the app build expects it: the prebuilt libunicorn.so (ARM-only, arm64-v8a) and the pure-Python binding.
#   .\android\fetch_unicorn.ps1 [path\to\libunicorn.so] [path\to\unicorn-source\bindings\python\unicorn]
# Neither is committed (Unicorn is GPLv2; see android/NOTES.md). For now the library is the one built on the phone in
# Termux by android/spike/termux_spike.sh (copied to the PC with adb), kept at C:\Android\libs\arm64-v8a\libunicorn.so;
# the binding comes from the Unicorn 2.1.4 source checkout (git clone --branch 2.1.4) at C:\Android\src\unicorn.
# Building the library from Windows with the NDK does not work (see android/NOTES.md, chunk 3).
param(
    [string]$Source = "C:\Android\libs\arm64-v8a\libunicorn.so",
    [string]$Binding = "C:\Android\src\unicorn\bindings\python\unicorn"
)
if (-not (Test-Path $Source)) { throw "No ${Source}: build it in Termux (android/spike/termux_spike.sh) and adb pull it." }
if (-not (Test-Path $Binding)) { throw "No ${Binding}: clone Unicorn 2.1.4 (git clone --depth 1 --branch 2.1.4 https://github.com/unicorn-engine/unicorn.git)." }
$dest = Join-Path $PSScriptRoot "app\src\main\jniLibs\arm64-v8a"
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item $Source (Join-Path $dest "libunicorn.so") -Force
$h = (Get-FileHash (Join-Path $dest "libunicorn.so") -Algorithm SHA256).Hash
Write-Host "libunicorn.so -> $dest  (sha256 $h)"
$py = Join-Path $PSScriptRoot "app\src\main\python\unicorn"
if (Test-Path $py) { Remove-Item -Recurse -Force $py }
Copy-Item $Binding $py -Recurse -Force
Get-ChildItem $py -Recurse -Include "__pycache__" -Directory | Remove-Item -Recurse -Force
Get-ChildItem $py -Recurse -Include "*.so*", "*.dll", "*.dylib" -File | Remove-Item -Force
Write-Host "Python binding -> $py"
