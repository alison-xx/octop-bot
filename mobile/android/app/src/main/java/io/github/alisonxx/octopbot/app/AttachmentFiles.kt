package io.github.alisonxx.octopbot.app

import android.content.ClipData
import android.content.ContentValues
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.webkit.MimeTypeMap
import androidx.core.content.FileProvider
import io.github.alisonxx.octopbot.model.FileAttachment
import io.github.alisonxx.octopbot.model.FileCards
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File
import java.security.MessageDigest
import java.util.concurrent.ConcurrentHashMap

/**
 * Files Bots sent, fetched once into `cache/attachment-sessions/` (served to other apps through the FileProvider),
 * plus their sizes from `HEAD`, remembered for this run of the app.
 */
class AttachmentFiles(private val cacheDir: File) {
    private val sizes = ConcurrentHashMap<String, Long>()
    private val locks = ConcurrentHashMap<String, Mutex>()

    suspend fun size(scope: String, file: FileAttachment, fetch: suspend (String) -> Long?): Long? {
        file.size?.let { return it }
        val key = digest(scope, file.url)
        sizes[key]?.let { return it }
        return fetch(file.url)?.also { sizes[key] = it }
    }

    /** The local copy of [file], downloading it the first time. */
    suspend fun local(scope: String, file: FileAttachment, fetch: suspend (String, File) -> Unit): File {
        val key = digest(scope, file.url)
        val folder = File(File(cacheDir, "attachment-sessions"), key)
        val target = File(folder, safeName(file.name))
        locks.getOrPut(target.path) { Mutex() }.withLock {
            if (target.isFile) return target
            withContext(Dispatchers.IO) { folder.mkdirs() }
            fetch(file.url, target)
            sizes.putIfAbsent(key, target.length())
        }
        return target
    }

    private fun digest(scope: String, url: String): String =
        MessageDigest.getInstance("SHA-256").digest((scope + "\u0000" + url).toByteArray()).joinToString("") { "%02x".format(it) }

    private fun safeName(name: String): String =
        name.replace(Regex("""[\\/:*?"<>|\u0000-\u001f]"""), "_").trim().ifEmpty { "file" }.take(120)

    companion object {
        fun mimeOf(file: FileAttachment): String =
            file.mime?.takeIf { it.isNotBlank() && it != "application/octet-stream" }
                ?: FileCards.extension(file.name)?.let { MimeTypeMap.getSingleton().getMimeTypeFromExtension(it) }
                ?: "application/octet-stream"

        private fun contentUri(context: Context, file: File): Uri =
            FileProvider.getUriForFile(context, context.packageName + ".photos", file)

        /** "Open with…": the system chooser of apps that view this type; the share sheet when none can. */
        fun openWith(context: Context, file: File, mime: String) {
            val uri = contentUri(context, file)
            val view = Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, mime)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            view.clipData = ClipData.newRawUri(null, uri)
            if (view.resolveActivity(context.packageManager) == null) {
                share(context, file, mime)
                return
            }
            context.startActivity(Intent.createChooser(view, null))
        }

        fun share(context: Context, file: File, mime: String) {
            val uri = contentUri(context, file)
            val send = Intent(Intent.ACTION_SEND)
                .setType(mime)
                .putExtra(Intent.EXTRA_STREAM, uri)
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            send.clipData = ClipData.newRawUri(null, uri)
            context.startActivity(Intent.createChooser(send, null))
        }

        /** Android 10+: a copy in the public Downloads folder, no permission needed. */
        fun saveToDownloads(context: Context, file: File, name: String, mime: String) {
            check(Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q)
            val resolver = context.contentResolver
            val values = ContentValues().apply {
                put(MediaStore.Downloads.DISPLAY_NAME, name)
                put(MediaStore.Downloads.MIME_TYPE, mime)
                put(MediaStore.Downloads.IS_PENDING, 1)
            }
            val uri = resolver.insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI, values) ?: error("no Downloads")
            try {
                copyTo(context, file, uri)
                resolver.update(uri, ContentValues().apply { put(MediaStore.Downloads.IS_PENDING, 0) }, null, null)
            } catch (error: Exception) {
                resolver.delete(uri, null, null)
                throw error
            }
        }

        /** Writes [file] into a document the user picked (Android 8–9 "Save to…"). */
        fun copyTo(context: Context, file: File, uri: Uri) {
            val out = context.contentResolver.openOutputStream(uri) ?: error("cannot write")
            out.use { stream -> file.inputStream().use { it.copyTo(stream) } }
        }
    }
}
