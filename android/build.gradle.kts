// Versions are pinned here, in one place. Chaquopy 17.2 supports the Android Gradle plugin from 7.3 to 9.5 and needs
// a Python on the build machine with the same major.minor as the app's (3.13, see app/build.gradle.kts).
plugins {
    id("com.android.application") version "8.7.3" apply false
    id("org.jetbrains.kotlin.android") version "2.0.21" apply false
    id("com.chaquo.python") version "17.2.0" apply false
}
