plugins {
    id("com.android.application")
}

android {
    namespace = "app.lodestar.mobile"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.lodestar.mobile"
        minSdk = 26  // Android 8.0+
        targetSdk = 35
        // build.ps1 passes a build number that grows with every build (the phone's self-update needs a newer one)
        versionCode = (project.findProperty("lodestarCode") as String?)?.toInt() ?: 1
        versionName = (project.findProperty("lodestarName") as String?) ?: "0.1.0"
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

    lint {
        abortOnError = true
        warningsAsErrors = false
        // English-only app built in code: no string resources to translate
        disable += "SetTextI18n"
        // by design: Lodestar's page needs JavaScript, and its phone listener is plain HTTP on your own network
        // (MainActivity.isPrivate keeps the app to private addresses); see README.md
        disable += "SetJavaScriptEnabled"
        disable += "InsecureBaseConfiguration"
    }
}

dependencies {
    testImplementation("junit:junit:4.13.2")  // AddressTest: the private-address rule, on the JVM
}
