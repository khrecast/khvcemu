cmake_minimum_required(VERSION 3.22)
project(recast_native C)

# A tiny probe that loads libunicorn.so (put into app/src/main/jniLibs/<abi>/, arm64-v8a and x86_64, by android/fetch_unicorn.ps1,
# not committed) with dlopen and runs three ARM instructions. No Unicorn headers are needed.
add_library(unicorn_probe SHARED unicorn_probe.c)
target_link_libraries(unicorn_probe log dl)
# 16 KB page alignment: NDK r28 already does this by default; the explicit option is belt and braces.
target_link_options(unicorn_probe PRIVATE -Wl,-z,max-page-size=16384)
