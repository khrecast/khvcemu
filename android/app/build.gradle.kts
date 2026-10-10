plugins {
    id("com.android.application")
}

android {
    namespace = "com.khrecast.recast"
    compileSdk = 36
    ndkVersion = "28.2.13676358"

    defaultConfig {
        applicationId = "com.khrecast.recast"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "0.0.1-spike"
        ndk {
            // Unicorn is built for the phone's 64-bit ARM only (see android/NOTES.md)
            abiFilters += listOf("arm64-v8a")
        }
        externalNativeBuild {
            cmake {
                arguments += listOf("-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON")
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = "3.31.6"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
