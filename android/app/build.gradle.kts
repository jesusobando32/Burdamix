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
            abiFilters += listOf("arm64-v8a")
        }
    }

    packaging {
        // youtubedl-android asks for android:extractNativeLibs="true": its python, yt-dlp and ffmpeg are unpacked from the APK.
        jniLibs { useLegacyPackaging = true }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

chaquopy {
    defaultConfig {
        version = "3.13"
        pip {
            install("yt-dlp")
        }
    }
}

dependencies {
    // yt-dlp and ffmpeg for Android (JunkFood02's maintained fork of yausername/youtubedl-android), from Maven Central.
    implementation("io.github.junkfood02.youtubedl-android:library:0.16.0")
    implementation("io.github.junkfood02.youtubedl-android:ffmpeg:0.16.0")
}
