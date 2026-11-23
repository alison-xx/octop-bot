import java.io.File
import java.net.URI
import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// In-app updates read this signed manifest. A debug build can point at a local fake with
// -PoctopBotUpdateManifestUrl=… -PoctopBotUpdatePublicKey=<base64 SPKI>; release builds always use these.
val updateManifestUrl = "https://dl.lynxce.cn/releases/octop-bot/manifest.json"
val updatePublicKey = "MCowBQYDK2VwAyEAjfzS5kpiVxqx/79rU5tYno7Js31ezDt05RmrmXnRTa0="
val debugManifestUrl = providers.gradleProperty("octopBotUpdateManifestUrl").orNull
val debugPublicKey = providers.gradleProperty("octopBotUpdatePublicKey").orNull

// Release signing comes from a properties file kept outside the repo (storeFile, storePassword,
// keyAlias, keyPassword). Default ~/.octop-bot-release/android-signing.properties, or
// -PoctopBotSigning=<path>. Without it the release APK is unsigned.
val signingFile = File(
    providers.gradleProperty("octopBotSigning").orNull
        ?: "${System.getProperty("user.home")}/.octop-bot-release/android-signing.properties",
)
val releaseSigning = signingFile.takeIf { it.isFile }?.let { file ->
    Properties().apply { file.inputStream().use { load(it) } }
}

fun quoted(value: String) = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    namespace = "io.github.alisonxx.octopbot"
    compileSdk = 36

    defaultConfig {
        applicationId = "io.github.alisonxx.octopbot"
        minSdk = 26
        targetSdk = 36
        versionCode = 2
        versionName = "1.0.0"

        buildConfigField("String", "UPDATE_MANIFEST_URL", quoted(updateManifestUrl))
        buildConfigField("String", "UPDATE_PUBLIC_KEY", quoted(updatePublicKey))
        // Debug only: the origin (scheme://host:port) of a test manifest, also allowed for the APK download.
        buildConfigField("String", "UPDATE_DEBUG_ORIGIN", quoted(""))
    }

    signingConfigs {
        releaseSigning?.let { props ->
            create("release") {
                storeFile = File(props.getProperty("storeFile"))
                storePassword = props.getProperty("storePassword")
                keyAlias = props.getProperty("keyAlias")
                keyPassword = props.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        debug {
            debugManifestUrl?.let { url ->
                val uri = URI(url)
                buildConfigField("String", "UPDATE_MANIFEST_URL", quoted(url))
                val port = if (uri.port == -1) "" else ":${uri.port}"
                buildConfigField("String", "UPDATE_DEBUG_ORIGIN", quoted("${uri.scheme}://${uri.host}$port"))
            }
            debugPublicKey?.let { buildConfigField("String", "UPDATE_PUBLIC_KEY", quoted(it)) }
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

    buildFeatures {
        compose = true
        buildConfig = true
    }

    androidResources {
        localeFilters += listOf("en", "zh")
    }

    // The in-app language picker needs every language on the device, not only the system one.
    bundle {
        language {
            enableSplit = false
        }
    }
}

dependencies {
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.graphics)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.androidx.core.splashscreen)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.coil.compose)
    implementation(libs.markdown.m3)
    debugImplementation(libs.compose.ui.tooling)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
}
