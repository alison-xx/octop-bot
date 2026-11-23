package io.github.alisonxx.octopbot.media

import android.content.ContentResolver
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.Build
import androidx.core.graphics.scale
import io.github.alisonxx.octopbot.model.ImageAttachment
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.roundToInt

object Photos {
    private const val MAX_SIDE = 1600

    /** Decode a picked photo upright, shrink it to at most 1600 px and re-encode as JPEG; null when unreadable. */
    suspend fun load(context: Context, uri: Uri): ImageAttachment? = withContext(Dispatchers.IO) {
        runCatching {
            val bitmap = decode(context.contentResolver, uri) ?: return@runCatching null
            val out = ByteArrayOutputStream()
            bitmap.compress(Bitmap.CompressFormat.JPEG, 85, out)
            ImageAttachment(uri.toString(), out.toByteArray())
        }.getOrNull()
    }

    private fun decode(resolver: ContentResolver, uri: Uri): Bitmap? {
        if (Build.VERSION.SDK_INT >= 28) {
            // ImageDecoder applies EXIF rotation, so camera shots arrive upright.
            return ImageDecoder.decodeBitmap(ImageDecoder.createSource(resolver, uri)) { decoder, info, _ ->
                val scale = MAX_SIDE.toFloat() / max(info.size.width, info.size.height)
                if (scale < 1f) decoder.setTargetSize((info.size.width * scale).roundToInt(), (info.size.height * scale).roundToInt())
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            }
        }
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        resolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        var sample = 1
        while (max(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2
        val decoded = resolver.openInputStream(uri)?.use {
            BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
        } ?: return null
        val scale = MAX_SIDE.toFloat() / max(decoded.width, decoded.height)
        if (scale >= 1f) return decoded
        return decoded.scale((decoded.width * scale).roundToInt(), (decoded.height * scale).roundToInt())
    }
}
