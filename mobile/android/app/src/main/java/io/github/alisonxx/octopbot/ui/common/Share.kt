package io.github.alisonxx.octopbot.ui.common

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import androidx.core.content.FileProvider
import coil3.imageLoader
import coil3.request.ImageRequest
import coil3.request.SuccessResult
import coil3.request.allowHardware
import coil3.toBitmap
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** The Android share sheet for a message's text. */
fun shareText(context: Context, text: String) {
    val send = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
    context.startActivity(Intent.createChooser(send, null))
}

/**
 * The share sheet for an image shown in a chat ([model] is a content URI or a URL). It is re-encoded into the
 * app cache so the receiving app can read it. Returns false when the image couldn't be loaded.
 */
suspend fun shareImage(context: Context, model: String): Boolean {
    val request = ImageRequest.Builder(context).data(model).allowHardware(false).build()
    val bitmap = (context.imageLoader.execute(request) as? SuccessResult)?.image?.toBitmap() ?: return false
    val file = withContext(Dispatchers.IO) {
        val folder = File(context.cacheDir, "shared").apply { mkdirs() }
        File(folder, "image.jpg").apply { outputStream().use { bitmap.compress(Bitmap.CompressFormat.JPEG, 92, it) } }
    }
    val uri = FileProvider.getUriForFile(context, context.packageName + ".photos", file)
    val send = Intent(Intent.ACTION_SEND)
        .setType("image/jpeg")
        .putExtra(Intent.EXTRA_STREAM, uri)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    send.clipData = ClipData.newRawUri(null, uri)
    context.startActivity(Intent.createChooser(send, null))
    return true
}
