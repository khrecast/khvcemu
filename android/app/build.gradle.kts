import java.util.Properties

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
        versionName = "0.1.0"                // the first release; raise versionCode with every release you hand out (Android refuses a lower one)
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

    // The release signing key is read from android/keystore.properties (gitignored: storeFile, storePassword, keyAlias, keyPassword). Without that
    // file the release build is simply unsigned, as before. Keep the key file and that file safe: an app signed with another key cannot update this one.
    val keystoreProps = Properties().apply {
        val f = rootProject.file("keystore.properties")
        if (f.isFile) {
            f.inputStream().use { load(it) }
        }
    }
    signingConfigs {
        if (keystoreProps.getProperty("storeFile") != null) {
            create("release") {
                storeFile = file(keystoreProps.getProperty("storeFile"))
                storePassword = keystoreProps.getProperty("storePassword")
                keyAlias = keystoreProps.getProperty("keyAlias")
                keyPassword = keystoreProps.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            // -Precast.debugSuffix=true installs the debug build beside the release one (app id ...recast.debug), for screenshots
            if (project.hasProperty("recast.debugSuffix")) applicationIdSuffix = ".debug"
        }
        release {
            isMinifyEnabled = false
            signingConfigs.findByName("release")?.let { signingConfig = it }
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

// The Wonderland theme (Aid1043's rendering, credited in docs/CREDITS.md) is packed into the app the same way the desktop installers
// carry it: from the repository's gitignored wonderland/ folder, only if that file is there when the app is built. It is not in git.
val stageWonderland = tasks.register<Copy>("stageWonderland") {
    into(layout.buildDirectory.dir("wonderland-assets/wonderland"))
    doFirst { delete(layout.buildDirectory.dir("wonderland-assets")) }      // (a theme removed from wonderland/ must leave the next build too)
    from("../../wonderland") {
        include("Wonderland.flac")
    }
}
tasks.named("preBuild") { dependsOn(stageWonderland) }
tasks.matching { it.name.contains("Assets") }.configureEach { dependsOn(stageWonderland) }
androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(stageWonderland, { project.objects.directoryProperty().also { it.set(layout.buildDirectory.dir("wonderland-assets")) } })
    }
}
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
            // draws the game's text and decodes its images where pygame is missing (khvcemu/hostgfx.py)
            install("Pillow==11.0.0")
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
