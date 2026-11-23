package io.github.alisonxx.octopbot.update

import java.net.URI
import java.security.MessageDigest

/** An APK newer than the installed one that this install may take. */
data class UpdateOffer(
    val version: String,
    val versionCode: Int,
    val url: String,
    val sha256: String,
    val size: Long?,
    /** The installed version is below `min_version_code`: stronger wording, still dismissible. */
    val urgent: Boolean,
)

object UpdateSelection {
    const val RELEASE_HOST = "dl.lynxce.cn"
    private const val CHECK_INTERVAL_MS = 24 * 3600 * 1000L

    /** Stable 0–99 bucket: first 4 bytes of SHA-256("installId:version"), unsigned big-endian, mod 100. */
    fun bucket(installId: String, version: String): Int {
        val digest = MessageDigest.getInstance("SHA-256").digest("$installId:$version".toByteArray(Charsets.UTF_8))
        var value = 0L
        for (i in 0 until 4) value = (value shl 8) or (digest[i].toLong() and 0xFF)
        return (value % 100).toInt()
    }

    fun inRollout(channel: ReleaseChannel, installId: String): Boolean = when {
        channel.rollout >= 100 -> true
        channel.rollout <= 0 -> false
        else -> bucket(installId, channel.version) < channel.rollout
    }

    /**
     * Downloads come from `https://dl.lynxce.cn` only. [debugOrigin] (`scheme://host:port`, debug builds only)
     * also allows a local test server.
     */
    fun isAllowedUrl(url: String, debugOrigin: String = ""): Boolean {
        val uri = runCatching { URI(url) }.getOrNull() ?: return false
        val scheme = uri.scheme?.lowercase()
        val host = uri.host?.lowercase() ?: return false
        if (scheme == "https" && host == RELEASE_HOST && (uri.port == -1 || uri.port == 443)) return true
        if (debugOrigin.isEmpty()) return false
        val allowed = runCatching { URI(debugOrigin) }.getOrNull() ?: return false
        return scheme == allowed.scheme?.lowercase() && host == allowed.host?.lowercase() && uri.port == allowed.port
    }

    /**
     * The update to offer, if any: `stable`, or with [receiveBeta] the higher `version_code` of stable and beta.
     * A channel counts only when this install is inside its rollout and its APK url is allowed.
     */
    fun offer(
        manifest: UpdateManifest,
        receiveBeta: Boolean,
        installId: String,
        currentVersionCode: Int,
        debugOrigin: String = "",
    ): UpdateOffer? {
        val asset = listOfNotNull(manifest.stable, manifest.beta.takeIf { receiveBeta })
            .filter { inRollout(it, installId) }
            .mapNotNull { it.android }
            .filter { isAllowedUrl(it.url, debugOrigin) }
            .maxByOrNull { it.versionCode }
            ?: return null
        if (asset.versionCode <= currentVersionCode) return null
        return UpdateOffer(
            version = asset.version,
            versionCode = asset.versionCode,
            url = asset.url,
            sha256 = asset.sha256,
            size = asset.size,
            urgent = (asset.minVersionCode ?: 0) > currentVersionCode,
        )
    }

    /** The home banner shows an offer until that version is dismissed; a newer version shows it again. */
    fun showBanner(offer: UpdateOffer?, dismissedVersionCode: Int?): Boolean =
        offer != null && offer.versionCode != dismissedVersionCode

    /** Back in the foreground: check again when the last successful check is over 24 h old. */
    fun checkDue(lastCheckAt: Long?, now: Long): Boolean = lastCheckAt == null || now - lastCheckAt > CHECK_INTERVAL_MS
}
