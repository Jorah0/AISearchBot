// Lodestar for Android (pass 55): a small native companion that opens your own Lodestar over your home Wi-Fi or a
// phone tether. No third-party libraries: only the Android Gradle plugin. Build: android/build.ps1 (see README.md).
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "LodestarMobile"
include(":app")
