package io.github.alisonxx.octopbot.update

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.longOrNull

/** The APK of one channel: `assets.android` in the release manifest. */
data class AndroidAsset(
    val name: String,
    val url: String,
    /** Lowercase hex. */
    val sha256: String,
    val size: Long?,
    val version: String,
    val versionCode: Int,
    val minVersionCode: Int?,
)

/** One channel (`stable` or `beta`). [android] is null when the release has no APK. */
data class ReleaseChannel(val version: String, val rollout: Int, val android: AndroidAsset?)

data class UpdateManifest(val stable: ReleaseChannel?, val beta: ReleaseChannel?)

class ManifestException(message: String) : Exception(message)

/** Reads the signed Octop Bot release manifest (`docs/octop-bot-updates.md`). Unknown keys are ignored. */
object ManifestParser {
    private val json = Json { ignoreUnknownKeys = true }
    private val hex64 = Regex("^[0-9a-fA-F]{64}$")

    fun parse(text: String): UpdateManifest {
        val root = runCatching { json.parseToJsonElement(text) }.getOrNull() as? JsonObject
            ?: throw ManifestException("manifest is not a JSON object")
        if (root.int("schema") != 1) throw ManifestException("unsupported schema")
        if (root.string("product") != "octop-bot") throw ManifestException("not an Octop Bot manifest")
        val channels = root["channels"] as? JsonObject ?: throw ManifestException("channels missing")
        return UpdateManifest(
            stable = channels["stable"]?.let { channel("stable", it) },
            beta = channels["beta"]?.let { channel("beta", it) },
        )
    }

    private fun channel(name: String, element: JsonElement): ReleaseChannel? {
        if (element is JsonNull) return null
        val obj = element as? JsonObject ?: throw ManifestException("$name is not an object")
        val version = obj.string("version")?.takeIf { it.isNotBlank() } ?: throw ManifestException("$name.version missing")
        val rollout = when (obj["rollout"]) {
            null, JsonNull -> 100
            else -> obj.int("rollout")?.takeIf { it in 0..100 } ?: throw ManifestException("$name.rollout must be 0–100")
        }
        val assets = obj["assets"] as? JsonObject ?: throw ManifestException("$name.assets missing")
        val android = when (val raw = assets["android"]) {
            null, JsonNull -> null
            is JsonObject -> android("$name.assets.android", raw)
            else -> throw ManifestException("$name.assets.android is not an object")
        }
        return ReleaseChannel(version, rollout, android)
    }

    private fun android(path: String, obj: JsonObject): AndroidAsset {
        val url = obj.string("url")?.takeIf { it.isNotBlank() } ?: throw ManifestException("$path.url missing")
        val sha = obj.string("sha256")?.takeIf { hex64.matches(it) } ?: throw ManifestException("$path.sha256 missing or malformed")
        val versionCode = obj.int("version_code")?.takeIf { it > 0 } ?: throw ManifestException("$path.version_code missing")
        val version = obj.string("version")?.takeIf { it.isNotBlank() } ?: throw ManifestException("$path.version missing")
        val size = when (obj["size"]) {
            null, JsonNull -> null
            else -> obj.long("size")?.takeIf { it >= 0 } ?: throw ManifestException("$path.size malformed")
        }
        val minVersionCode = when (obj["min_version_code"]) {
            null, JsonNull -> null
            else -> obj.int("min_version_code") ?: throw ManifestException("$path.min_version_code malformed")
        }
        val name = obj.string("name")?.takeIf { it.isNotBlank() } ?: url.substringAfterLast('/')
        return AndroidAsset(name, url, sha.lowercase(), size, version, versionCode, minVersionCode)
    }

    private fun JsonObject.string(key: String): String? = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
    private fun JsonObject.int(key: String): Int? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.intOrNull
    private fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull
}
