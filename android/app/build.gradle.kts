plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "app.burdamix"
    compileSdk = 34

    defaultConfig {
        applicationId = "app.burdamix"
        minSdk = 26            // Android 8; Chaquopy 17.2 itself needs 24 or more
        targetSdk = 34
        versionCode = 1
        versionName = "0.1.0-movil-prueba"

        ndk {
            // Python 3.12 and newer is 64-bit only. arm64-v8a is every current phone.
            // For an x86_64 emulator (it does not run arm64 libraries natively) build with: -Pburdamix.abis=arm64-v8a,x86_64
            val abis = (project.findProperty("burdamix.abis") as String? ?: "arm64-v8a").split(",")
            abiFilters += abis.map { it.trim() }
        }
    }

    packaging {
        // youtubedl-android asks for android:extractNativeLibs="true": its python, yt-dlp and ffmpeg are unpacked from the APK.
        jniLibs { useLegacyPackaging = true }
    }

    ndkVersion = "27.1.12297006"   // only for libc++_shared.so, see copyLibcxx below

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

// The ffmpeg executable of youtubedl-android links against libc++_shared.so but does not ship it, so the app must. It is copied
// from the NDK at build time (no binary in the repository) into jniLibs, where the Android installer unpacks it.
val libcxxDir = layout.buildDirectory.dir("generated/libcxx")
val copyLibcxx by tasks.registering {
    val ndk = android.ndkDirectory
    val abis = android.defaultConfig.ndk.abiFilters.toList()
    outputs.dir(libcxxDir)
    doLast {
        val triples = mapOf("arm64-v8a" to "aarch64-linux-android", "x86_64" to "x86_64-linux-android")
        abis.forEach { abi ->
            val source = ndk.walkTopDown().first { it.name == "libc++_shared.so" && it.parentFile.name == triples.getValue(abi) }
            source.copyTo(libcxxDir.get().asFile.resolve("$abi/libc++_shared.so"), overwrite = true)
        }
    }
}
android.sourceSets["main"].jniLibs.srcDir(libcxxDir)
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("JniLibFolders") }.configureEach { dependsOn(copyLibcxx) }

// One source for the desktop and the phone: the page is gui/web itself (served as assets) and the bridge is gui/bridge.py.
android.sourceSets["main"].assets.srcDir("../../gui/web")
// The program's Python (root modules, apis/, gui/) is packaged as it is; bridge.py goes to the top level so burdamix_host finds it.
val programPy = layout.buildDirectory.dir("generated/programpy")
val copyProgram by tasks.registering(Sync::class) {
    from("../..") {
        include("*.py", "apis/**/*.py", "gui/*.py")
        exclude("gui_app.py", "spotify2mp3.py", "tests/**", "android/**")
    }
    from("../../gui/bridge.py")
    into(programPy)
}
chaquopy.sourceSets.getByName("main").srcDir(programPy)
tasks.matching { it.name.contains("Python") }.configureEach { dependsOn(copyProgram) }

chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            install("yt-dlp")
            listOf("flask", "mutagen", "pillow", "requests", "segno", "tekore", "eyed3").forEach { install(it) }
        }
    }
}

dependencies {
    implementation("androidx.webkit:webkit:1.12.1")   // WebViewAssetLoader: serves gui/web from https://appassets.androidplatform.net
    // yt-dlp and ffmpeg for Android (JunkFood02's maintained fork of yausername/youtubedl-android), from Maven Central.
    implementation("io.github.junkfood02.youtubedl-android:library:0.16.0")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.16.0")
}
