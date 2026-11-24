package io.github.alisonxx.octopbot.ui.chat

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.pdf.PdfRenderer
import android.os.Build
import android.os.ParcelFileDescriptor
import android.util.LruCache
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.Download
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.drawText
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.FileAttachment
import io.github.alisonxx.octopbot.model.FileCards
import io.github.alisonxx.octopbot.model.FileKind
import io.github.alisonxx.octopbot.model.FilePreview
import io.github.alisonxx.octopbot.ui.common.rememberHaptics
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

/** What a file card can do; the chat screen wires these to the signed-in server. */
class AttachmentActions(
    /** The size from the server (`HEAD`), or null when unknown. */
    val size: suspend (FileAttachment) -> Long?,
    /** The downloaded copy for a preview, or null when it can't be fetched. */
    val previewFile: suspend (FileAttachment) -> File?,
    /** "Open with…" another app. */
    val open: (FileAttachment) -> Unit,
    /** Images: the full-screen viewer. */
    val openImage: (FileAttachment) -> Unit,
    val share: (FileAttachment) -> Unit,
    val save: (FileAttachment) -> Unit,
)

private const val MAX_IMAGE_BYTES = 30L * 1024 * 1024
private const val MAX_PDF_BYTES = 20L * 1024 * 1024
private const val MAX_TEXT_BYTES = 1L * 1024 * 1024

private sealed interface PreviewContent {
    class Picture(val bitmap: ImageBitmap) : PreviewContent
    class Excerpt(val lines: List<String>) : PreviewContent
}

/** Decoded previews, so scrolling a chat doesn't decode the same file again. */
private val previewCache = LruCache<String, PreviewContent>(24)

/** One card, or a horizontal row of cards when a reply carries several files. */
@Composable
fun AttachmentStrip(files: List<FileAttachment>, actions: AttachmentActions, modifier: Modifier = Modifier) {
    if (files.size == 1) {
        AttachmentCard(files[0], actions, single = true, modifier = modifier)
        return
    }
    LazyRow(modifier, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(files, key = { it.url }) { file -> AttachmentCard(file, actions, single = false) }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun AttachmentCard(file: FileAttachment, actions: AttachmentActions, single: Boolean, modifier: Modifier = Modifier) {
    val palette = LocalPalette.current
    val haptics = rememberHaptics()
    val previewKind = remember(file.name, file.mime) { FileCards.preview(file.name, file.mime) }
    var size by remember(file.url) { mutableStateOf(file.size) }
    LaunchedEffect(file.url) {
        if (size == null && previewKind != FilePreview.Image) size = actions.size(file)
    }
    val targetPx = with(LocalDensity.current) { 320.dp.roundToPx() }.coerceAtMost(1080)
    val preview by produceState(previewCache.get(file.url), file.url, size) {
        if (value != null) return@produceState
        val known = size
        val allowed = when (previewKind) {
            FilePreview.Image -> known == null || known <= MAX_IMAGE_BYTES
            FilePreview.Pdf -> known != null && known <= MAX_PDF_BYTES
            FilePreview.Text -> known != null && known <= MAX_TEXT_BYTES
            FilePreview.None -> false
        }
        if (!allowed) return@produceState
        val local = actions.previewFile(file) ?: return@produceState
        value = withContext(Dispatchers.IO) { runCatching { loadPreview(previewKind, local, targetPx) }.getOrNull() }
            ?.also { previewCache.put(file.url, it) }
    }
    var menu by remember { mutableStateOf(false) }
    val click = Modifier.combinedClickable(
        onClick = { if (previewKind == FilePreview.Image) actions.openImage(file) else actions.open(file) },
        onLongClick = {
            haptics.longPress()
            menu = true
        },
    )
    val light = palette.background.luminance() > 0.5f
    val shape = RoundedCornerShape(14.dp)
    val cardColor = if (light) Color.White else palette.surface
    val lift = if (light) Modifier.shadow(2.dp, shape, clip = false, ambientColor = Color(0x14000000), spotColor = Color(0x1F000000)) else Modifier

    Box(modifier) {
        val picture = preview as? PreviewContent.Picture
        when {
            // An image is its own card: the picture, rounded, aspect kept.
            previewKind == FilePreview.Image && picture != null -> {
                val ratio = (picture.bitmap.width.toFloat() / picture.bitmap.height).coerceIn(0.6f, 2.4f)
                Image(
                    picture.bitmap,
                    contentDescription = file.name,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier
                        .then(if (single) Modifier.widthIn(max = 320.dp) else Modifier.width(240.dp))
                        .aspectRatio(ratio)
                        .clip(RoundedCornerShape(16.dp))
                        .border(1.dp, palette.hairline, RoundedCornerShape(16.dp))
                        .then(click),
                )
            }
            preview != null -> Column(
                Modifier
                    .width(if (single) 300.dp else 240.dp)
                    .then(lift)
                    .clip(shape)
                    .background(cardColor)
                    .border(1.dp, palette.hairline, shape)
                    .then(click),
            ) {
                when (val content = preview) {
                    is PreviewContent.Picture -> Image(
                        content.bitmap,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        alignment = Alignment.TopCenter,
                        modifier = Modifier.fillMaxWidth().height(168.dp).background(Color.White),
                    )
                    is PreviewContent.Excerpt -> Text(
                        content.lines.joinToString("\n"),
                        style = MaterialTheme.typography.bodySmall.copy(fontFamily = FontFamily.Monospace, fontSize = 11.sp, lineHeight = 15.sp),
                        color = palette.secondary,
                        maxLines = 6,
                        overflow = TextOverflow.Clip,
                        softWrap = false,
                        modifier = Modifier.fillMaxWidth().background(palette.raised).padding(horizontal = 12.dp, vertical = 10.dp),
                    )
                    null -> Unit
                }
                Box(Modifier.fillMaxWidth().height(1.dp).background(palette.hairline))
                FileRow(file, size, Modifier.fillMaxWidth())
            }
            else -> FileRow(
                file,
                size,
                Modifier
                    .then(if (single) Modifier.widthIn(min = 200.dp, max = 320.dp) else Modifier.width(240.dp))
                    .then(lift)
                    .clip(shape)
                    .background(cardColor)
                    .border(1.dp, palette.hairline, shape)
                    .then(click),
            )
        }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            FileMenuItem(Icons.AutoMirrored.Rounded.OpenInNew, stringResource(R.string.file_open_with), { menu = false }) { actions.open(file) }
            FileMenuItem(Icons.Rounded.Share, stringResource(R.string.file_share), { menu = false }) { actions.share(file) }
            val save = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) R.string.file_save else R.string.file_save_to
            FileMenuItem(Icons.Rounded.Download, stringResource(save), { menu = false }) { actions.save(file) }
        }
    }
}

/** Type glyph · name (middle-ellipsized, extension kept) over the size. */
@Composable
private fun FileRow(file: FileAttachment, size: Long?, modifier: Modifier) {
    val palette = LocalPalette.current
    val label = remember(file.name) { FileCards.typeLabel(file.name) }
    Row(modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        DocumentGlyph(FileCards.kind(file.name, file.mime), label)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f, fill = false)) {
            Text(
                remember(file.name) { FileCards.middleEllipsis(file.name) },
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
                color = palette.text,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                size?.let(FileCards::formatFileSize) ?: label ?: stringResource(R.string.file_kind_file),
                style = MaterialTheme.typography.bodySmall,
                color = palette.secondary,
                maxLines = 1,
            )
        }
    }
}

/** A page with a folded corner; its bottom band is colored by type and carries the extension. */
@Composable
private fun DocumentGlyph(kind: FileKind, label: String?) {
    val palette = LocalPalette.current
    val light = palette.background.luminance() > 0.5f
    val paper = if (light) Color.White else palette.raised
    val edge = palette.hairline
    val band = Color(kind.argb)
    val measurer = rememberTextMeasurer()
    val style = TextStyle(color = Color.White, fontSize = 8.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.2.sp)
    Canvas(Modifier.size(34.dp, 42.dp)) {
        val w = size.width
        val h = size.height
        val fold = w * 0.3f
        val r = 4.dp.toPx()
        val page = Path().apply {
            moveTo(r, 0f)
            lineTo(w - fold, 0f)
            lineTo(w, fold)
            lineTo(w, h - r)
            quadraticTo(w, h, w - r, h)
            lineTo(r, h)
            quadraticTo(0f, h, 0f, h - r)
            lineTo(0f, r)
            quadraticTo(0f, 0f, r, 0f)
            close()
        }
        val bandTop = h * 0.56f
        drawPath(page, paper)
        clipPath(page) { drawRect(band, topLeft = Offset(0f, bandTop), size = Size(w, h - bandTop)) }
        drawPath(page, edge, style = Stroke(1.dp.toPx()))
        val corner = Path().apply {
            moveTo(w - fold, 0f)
            lineTo(w - fold, fold)
            lineTo(w, fold)
            close()
        }
        drawPath(corner, edge)
        if (label != null) {
            val text = measurer.measure(label, style)
            drawText(
                text,
                topLeft = Offset((w - text.size.width) / 2f, bandTop + (h - bandTop - text.size.height) / 2f),
            )
        }
    }
}

@Composable
private fun FileMenuItem(icon: ImageVector, label: String, dismiss: () -> Unit, onClick: () -> Unit) {
    DropdownMenuItem(
        text = { Text(label) },
        leadingIcon = { Icon(icon, null) },
        onClick = {
            dismiss()
            onClick()
        },
    )
}

private fun loadPreview(kind: FilePreview, file: File, targetPx: Int): PreviewContent? = when (kind) {
    FilePreview.Image -> decodeSampled(file, targetPx)?.let { PreviewContent.Picture(it.asImageBitmap()) }
    FilePreview.Pdf -> firstPdfPage(file, targetPx)?.let { PreviewContent.Picture(it.asImageBitmap()) }
    FilePreview.Text -> file.bufferedReader().useLines { lines -> lines.take(6).map { it.take(160) }.toList() }
        .takeIf { lines -> lines.any { it.isNotBlank() } }
        ?.let(PreviewContent::Excerpt)
    FilePreview.None -> null
}

/** Decodes at a power-of-two scale no smaller than [targetPx] wide. */
private fun decodeSampled(file: File, targetPx: Int): Bitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.path, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
    var sample = 1
    while (bounds.outWidth / (sample * 2) >= targetPx) sample *= 2
    return BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
}

private fun firstPdfPage(file: File, targetPx: Int): Bitmap? =
    ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY).use { descriptor ->
        PdfRenderer(descriptor).use { renderer ->
            if (renderer.pageCount == 0) return null
            renderer.openPage(0).use { page ->
                val height = (targetPx * page.height.toFloat() / page.width).toInt().coerceIn(1, targetPx * 2)
                Bitmap.createBitmap(targetPx, height, Bitmap.Config.ARGB_8888).apply {
                    eraseColor(android.graphics.Color.WHITE)
                    page.render(this, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY)
                }
            }
        }
    }
