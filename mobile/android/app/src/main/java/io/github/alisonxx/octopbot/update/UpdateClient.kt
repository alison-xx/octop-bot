package io.github.alisonxx.octopbot.update

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.job
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.File
import java.io.IOException
import java.security.MessageDigest

/** Why a download did not produce an installable APK. */
class UpdateException(val integrity: Boolean, message: String) : IOException(message)

/**
 * Network side of updates: the signed manifest and the APK. No Android APIs, so it runs in unit tests.
 * The app always passes [verifySignature] = true; the flag exists for tests. https, the SHA-256 and
 * the signing certificate guard the APK on top of the signed manifest.
 */
class UpdateClient(
    private val client: OkHttpClient,
    private val manifestUrl: String,
    private val publicKey: String,
    private val verifySignature: Boolean,
) {
    suspend fun fetchManifest(): UpdateManifest = withContext(Dispatchers.IO) {
        val body = get(manifestUrl)
        if (verifySignature) {
            val signature = get("$manifestUrl.sig").toString(Charsets.US_ASCII)
            if (!ManifestSignature.verify(body, signature, publicKey)) throw ManifestException("manifest signature is invalid")
        }
        ManifestParser.parse(body.toString(Charsets.UTF_8))
    }

    /**
     * Download [offer] to [target], reporting whole percents (or -1 without a known size). A file already at
     * [target] with the right hash is reused. The hash is checked while streaming; a mismatch deletes the file.
     */
    suspend fun download(offer: UpdateOffer, target: File, onProgress: (Int) -> Unit): File = withContext(Dispatchers.IO) {
        if (target.isFile && sha256(target) == offer.sha256) return@withContext target
        target.parentFile?.mkdirs()
        val partial = File(target.path + ".part")
        val call = client.newCall(Request.Builder().url(offer.url).build())
        // Cancelling the coroutine aborts a blocked read.
        val cancel = currentCoroutineContext().job.invokeOnCompletion { call.cancel() }
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) throw UpdateException(false, "HTTP ${response.code}")
                val total = offer.size ?: response.body.contentLength().takeIf { it > 0 }
                val digest = MessageDigest.getInstance("SHA-256")
                var read = 0L
                var lastPercent = -2
                response.body.byteStream().use { input ->
                    partial.outputStream().use { output ->
                        val buffer = ByteArray(64 * 1024)
                        while (true) {
                            currentCoroutineContext().ensureActive()
                            val n = input.read(buffer)
                            if (n < 0) break
                            output.write(buffer, 0, n)
                            digest.update(buffer, 0, n)
                            read += n
                            val percent = if (total == null) -1 else (read * 100 / total).toInt().coerceIn(0, 100)
                            if (percent != lastPercent) {
                                lastPercent = percent
                                onProgress(percent)
                            }
                        }
                    }
                }
                val hex = digest.digest().joinToString("") { "%02x".format(it) }
                if (hex != offer.sha256) throw UpdateException(true, "SHA-256 mismatch")
            }
            if (!partial.renameTo(target)) throw UpdateException(false, "could not save the download")
            target
        } catch (error: Throwable) {
            partial.delete()
            throw error
        } finally {
            cancel.dispose()
        }
    }

    private fun get(url: String): ByteArray {
        val request = Request.Builder().url(url).header("Cache-Control", "no-cache").build()
        return client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) throw IOException("HTTP ${response.code} for $url")
            response.body.bytes()
        }
    }

    companion object {
        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    digest.update(buffer, 0, n)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
