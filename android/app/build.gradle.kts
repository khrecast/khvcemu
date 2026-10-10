plugins {
    id("com.android.application")
    id("com.chaquo.python")
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

    packaging {
        jniLibs {
            // libunicorn.so is loaded from Python by its file path, so it has to be a real file on disk
            useLegacyPackaging = true
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

// The emulator core is the repository's own khvcemu/ package: it is copied (not duplicated in git) into a
// staging folder that Chaquopy packs as Python source, together with the benchmark script of the spike.
val stagePython = tasks.register<Copy>("stagePython") {
    into(layout.buildDirectory.dir("python-stage"))
    from("../../khvcemu") {
        into("khvcemu")
        exclude("**/__pycache__/**", "**/*.flac", "**/*.wav", "**/*.mp3", "**/*.ogg")
    }
    from("../spike/bench_headless.py")
}
tasks.named("preBuild") { dependsOn(stagePython) }
// Chaquopy's merge task reads the staging folder, so Gradle needs the dependency spelled out
tasks.matching { it.name.endsWith("PythonSources") }.configureEach { dependsOn(stagePython) }

chaquopy {
    defaultConfig {
        version = "3.12"
        // Chaquopy needs a Python of the same version (3.12) on this PC to fetch the packages. Give its path with
        // -Precast.buildPython=<path to python.exe or python3.12> (kept out of the repository on purpose); without it
        // the py launcher (Windows) or python3.12 is tried.
        val buildPy = providers.gradleProperty("recast.buildPython").orNull
        if (buildPy != null) {
            buildPython(buildPy)
        } else if (System.getProperty("os.name").lowercase().contains("windows")) {
            buildPython("py", "-3.12")
        } else {
            buildPython("python3.12")
        }
        pip {
            install("numpy==1.26.2")
        }
        // These packages build file paths from their own location (Unicorn's loader, the core's data files), so they
        // are unpacked to real files at startup instead of being read from inside the APK.
        extractPackages("unicorn", "khvcemu")
    }
    sourceSets {
        getByName("main") {
            srcDir(layout.buildDirectory.dir("python-stage"))
        }
    }
}
