# Sets up the Android toolchain for THIS PowerShell session only (nothing system-wide).
#   . .\android\env.ps1
# The toolchain lives outside the repo, by default in C:\Android (override with $env:ANDROID_ROOT first).
$root = if ($env:ANDROID_ROOT) { $env:ANDROID_ROOT } else { "C:\Android" }
$jdk = Get-ChildItem -Path $root -Directory -Filter "jdk-17*" | Select-Object -First 1
if (-not $jdk) { throw "No JDK 17 under $root (see android/NOTES.md, section 7)" }
$env:JAVA_HOME = $jdk.FullName
$env:ANDROID_HOME = Join-Path $root "sdk"
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$env:ANDROID_NDK_HOME = Join-Path $env:ANDROID_HOME "ndk\28.2.13676358"
$cmake = Join-Path $env:ANDROID_HOME "cmake\3.31.6\bin"
$env:PATH = "$env:JAVA_HOME\bin;$env:ANDROID_HOME\platform-tools;$cmake;$env:PATH"
Write-Host "JAVA_HOME=$env:JAVA_HOME"
Write-Host "ANDROID_HOME=$env:ANDROID_HOME"
Write-Host "ANDROID_NDK_HOME=$env:ANDROID_NDK_HOME"
