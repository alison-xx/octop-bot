package io.github.alisonxx.octopbot.ui.chat

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color as AndroidColor
import android.view.ViewGroup
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.scaleIn
import androidx.compose.animation.scaleOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Computer
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.OpenInFull
import androidx.compose.material.icons.rounded.PanTool
import androidx.compose.material.icons.rounded.Remove
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.net.ApiException
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.net.ServerProtocol.ComputerStatus
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

/**
 * The floating view of a Bot's cloud computer in its chat (plan §12.7, like the web float): a small 16:9
 * card while the Bot works on the computer, a pill when minimised, full screen with take-over on tap, and
 * closed until the header button shows it again.
 */
class CloudFloatState(val server: ServerBackend, val botId: String, context: Context) {
    enum class Mode { Hidden, Pill, Card }
    enum class Corner { TopStart, TopEnd, BottomStart, BottomEnd }

    private val prefs = context.getSharedPreferences("octop.cloudFloat", Context.MODE_PRIVATE)

    /** The server has cloud computers (status answers instead of 404). */
    var available by mutableStateOf(false)
        private set
    var status by mutableStateOf<ComputerStatus?>(null)
        private set
    var window by mutableStateOf<String?>(null)
        private set
    var thumbnail by mutableStateOf<Bitmap?>(null)
        private set
    var mode by mutableStateOf(Mode.Hidden)
        private set
    var expanded by mutableStateOf(false)
    var corner by mutableStateOf(runCatching { Corner.valueOf(prefs.getString("corner", null) ?: "") }.getOrDefault(Corner.BottomEnd))
        private set

    /** Closed by the user: no auto-show in this Bot's chat until the header button. */
    private var closed: Boolean
        get() = prefs.getBoolean("closed.$botId", false)
        set(value) = prefs.edit().putBoolean("closed.$botId", value).apply()

    /** Minimised by the user: later turns of this chat only show the pill. */
    private var pillOnly = false
    /** Opened from the header while the computer is off: keep the card up anyway. */
    private var pinned = false
    private var idleSince: Long? = null

    val running get() = status?.state == ComputerStatus.State.Running
    val busy get() = running && status?.busy == true

    /** Polls while the chat is on screen and resumed (the caller's coroutine is cancelled when it leaves). */
    suspend fun run() {
        while (true) {
            refresh()
            delay(POLL_MILLIS)
        }
    }

    suspend fun refresh() {
        val next = try {
            server.computerStatus(botId)
        } catch (e: CancellationException) {
            throw e
        } catch (e: ApiException) {
            if (e.status == 404) {
                available = false
                mode = Mode.Hidden
            }
            return
        } catch (_: Exception) {
            return
        }
        available = true
        status = next
        if (next.state != ComputerStatus.State.Running) {
            thumbnail = null
            window = null
            if (!pinned) mode = Mode.Hidden
            return
        }
        val now = System.currentTimeMillis()
        if (next.busy) {
            idleSince = null
            if (!closed && (mode == Mode.Hidden || (mode == Mode.Pill && !pillOnly))) mode = if (pillOnly) Mode.Pill else Mode.Card
        } else {
            val since = idleSince ?: now.also { idleSince = it }
            if (mode == Mode.Card && !pinned && now - since > IDLE_TO_PILL_MILLIS) mode = Mode.Pill
            if (mode == Mode.Hidden && !closed) mode = Mode.Pill
        }
        if (mode != Mode.Hidden || expanded) {
            val glance = runCatching { server.glance(botId) }.getOrNull() ?: return
            window = glance.window
            glance.thumbnail?.let { bytes -> BitmapFactory.decodeByteArray(bytes, 0, bytes.size)?.let { thumbnail = it } }
        }
    }

    /** The chat header's button: show the card, or close it when it is showing. */
    fun toggle() {
        if (mode == Mode.Hidden || closed) {
            closed = false
            pinned = true
            pillOnly = false
            mode = Mode.Card
        } else {
            close()
        }
    }

    fun close() {
        closed = true
        pinned = false
        mode = Mode.Hidden
    }

    fun minimise() {
        pillOnly = true
        pinned = false
        mode = Mode.Pill
    }

    fun open() {
        pillOnly = false
        mode = Mode.Card
    }

    fun moveTo(next: Corner) {
        corner = next
        prefs.edit().putString("corner", next.name).apply()
    }

    /** What the Bot just did, for the card's header. */
    val activityText: Int
        get() = when {
            !running -> R.string.computer_float_off
            status?.takeover == true -> R.string.computer_float_yours
            !busy -> R.string.computer_float_idle
            else -> when (status?.activity) {
                "screenshot" -> R.string.computer_activity_screenshot
                "click" -> R.string.computer_activity_click
                "type" -> R.string.computer_activity_type
                "key" -> R.string.computer_activity_key
                "scroll" -> R.string.computer_activity_scroll
                "command" -> R.string.computer_activity_command
                "file" -> R.string.computer_activity_file
                else -> R.string.computer_float_busy
            }
        }

    companion object {
        const val POLL_MILLIS = 3_000L
        /** A turn ends: the card shrinks to the pill after this long without actions. */
        const val IDLE_TO_PILL_MILLIS = 30_000L
    }
}

private val CARD_WIDTH = 208.dp
private val MARGIN = 12.dp

/** The card or pill over the chat, draggable to the four corners. */
@Composable
fun CloudFloatOverlay(state: CloudFloatState, botName: String, bottomInset: Dp, modifier: Modifier = Modifier) {
    var drag by remember { mutableStateOf(androidx.compose.ui.geometry.Offset.Zero) }
    BoxWithConstraints(modifier.fillMaxSize()) {
        val width = constraints.maxWidth.toFloat()
        val height = constraints.maxHeight.toFloat()
        val alignment = when (state.corner) {
            CloudFloatState.Corner.TopStart -> Alignment.TopStart
            CloudFloatState.Corner.TopEnd -> Alignment.TopEnd
            CloudFloatState.Corner.BottomStart -> Alignment.BottomStart
            CloudFloatState.Corner.BottomEnd -> Alignment.BottomEnd
        }
        val top = state.corner == CloudFloatState.Corner.TopStart || state.corner == CloudFloatState.Corner.TopEnd
        AnimatedVisibility(
            visible = state.mode != CloudFloatState.Mode.Hidden,
            enter = fadeIn() + scaleIn(initialScale = 0.85f),
            exit = fadeOut() + scaleOut(targetScale = 0.85f),
            modifier = Modifier
                .align(alignment)
                .padding(start = MARGIN, end = MARGIN, top = MARGIN, bottom = if (top) MARGIN else bottomInset)
                .offset { IntOffset(drag.x.roundToInt(), drag.y.roundToInt()) }
                .pointerInput(state.corner) {
                    detectDragGestures(
                        onDragEnd = {
                            // Where the float's centre would land: the nearest corner wins.
                            val startX = if (state.corner == CloudFloatState.Corner.TopStart || state.corner == CloudFloatState.Corner.BottomStart) 0f else width
                            val startY = if (top) 0f else height
                            val left = startX + drag.x < width / 2
                            val upper = startY + drag.y < height / 2
                            state.moveTo(
                                when {
                                    upper && left -> CloudFloatState.Corner.TopStart
                                    upper -> CloudFloatState.Corner.TopEnd
                                    left -> CloudFloatState.Corner.BottomStart
                                    else -> CloudFloatState.Corner.BottomEnd
                                },
                            )
                            drag = androidx.compose.ui.geometry.Offset.Zero
                        },
                        onDragCancel = { drag = androidx.compose.ui.geometry.Offset.Zero },
                    ) { change, amount ->
                        change.consume()
                        drag += amount
                    }
                },
        ) {
            if (state.mode == CloudFloatState.Mode.Pill) Pill(state) else Card(state, botName)
        }
    }
}

@Composable
private fun Card(state: CloudFloatState, botName: String) {
    val palette = LocalPalette.current
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier
            .width(CARD_WIDTH + 12.dp)
            .shadow(14.dp, shape)
            .clip(shape)
            .background(palette.raised)
            .then(glow(state, palette.accent, shape)),
    ) {
        Row(Modifier.fillMaxWidth().height(40.dp).padding(start = 10.dp), verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Rounded.Computer, contentDescription = null, modifier = Modifier.size(16.dp), tint = palette.text)
            Column(Modifier.weight(1f).padding(start = 6.dp)) {
                Text(state.window ?: botName, style = MaterialTheme.typography.labelMedium, color = palette.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(stringResource(state.activityText), style = MaterialTheme.typography.labelSmall, color = palette.secondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            SmallIcon(Icons.Rounded.OpenInFull, R.string.computer_float_expand) { state.expanded = true }
            SmallIcon(Icons.Rounded.Remove, R.string.computer_float_minimise) { state.minimise() }
            SmallIcon(Icons.Rounded.Close, R.string.computer_float_close) { state.close() }
        }
        Box(
            Modifier
                .padding(start = 6.dp, end = 6.dp, bottom = 6.dp)
                .width(CARD_WIDTH)
                .aspectRatio(16f / 9f)
                .clip(RoundedCornerShape(8.dp))
                .background(Color.Black)
                .clickable { state.expanded = true },
            contentAlignment = Alignment.Center,
        ) {
            val image = state.thumbnail
            if (image != null) {
                Image(image.asImageBitmap(), contentDescription = null, contentScale = ContentScale.Fit, modifier = Modifier.fillMaxSize())
            } else {
                Text(
                    stringResource(if (state.running) R.string.computer_float_loading else R.string.computer_float_off),
                    style = MaterialTheme.typography.labelSmall,
                    color = Color.White.copy(alpha = 0.7f),
                    modifier = Modifier.padding(10.dp),
                )
            }
        }
    }
}

/** A breathing accent edge while the Bot works; solid blue while the user has the computer. */
@Composable
private fun glow(state: CloudFloatState, accent: Color, shape: RoundedCornerShape): Modifier {
    if (state.status?.takeover == true) return Modifier.border(BorderStroke(2.dp, Color(0xFF2F7BF6)), shape)
    if (!state.busy) return Modifier
    val alpha by rememberInfiniteTransition(label = "glow").animateFloat(
        initialValue = 0.45f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(1300), RepeatMode.Reverse),
        label = "glowAlpha",
    )
    return Modifier.border(BorderStroke(2.dp, accent.copy(alpha = alpha)), shape)
}

@Composable
private fun Pill(state: CloudFloatState) {
    val palette = LocalPalette.current
    Row(
        Modifier
            .shadow(10.dp, CircleShape)
            .clip(CircleShape)
            .background(palette.raised)
            .padding(start = 8.dp, end = 2.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Row(
            Modifier.clickable { state.open() }.padding(vertical = 2.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            val image = state.thumbnail
            if (image != null) {
                Image(
                    image.asImageBitmap(),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.width(40.dp).height(24.dp).clip(RoundedCornerShape(4.dp)),
                )
            } else {
                Icon(Icons.Rounded.Computer, contentDescription = null, modifier = Modifier.size(18.dp), tint = palette.text)
            }
            Box(Modifier.size(7.dp).clip(CircleShape).background(if (state.busy) Color(0xFF34C759) else palette.secondary))
            Text(stringResource(state.activityText), style = MaterialTheme.typography.labelMedium, color = palette.text, maxLines = 1)
        }
        SmallIcon(Icons.Rounded.Close, R.string.computer_float_close) { state.close() }
    }
}

@Composable
private fun SmallIcon(icon: androidx.compose.ui.graphics.vector.ImageVector, label: Int, onClick: () -> Unit) {
    IconButton(onClick = onClick, modifier = Modifier.size(32.dp)) {
        Icon(icon, contentDescription = stringResource(label), modifier = Modifier.size(16.dp), tint = LocalPalette.current.text)
    }
}

/** The chat header's cloud computer button: shows or closes the float; a green dot while the Bot works. */
@Composable
fun CloudFloatToggle(state: CloudFloatState) {
    IconButton(onClick = { state.toggle() }, modifier = Modifier.size(44.dp)) {
        Box {
            Icon(Icons.Rounded.Computer, contentDescription = stringResource(R.string.computer_float_toggle))
            if (state.busy) {
                Box(Modifier.align(Alignment.TopEnd).offset(x = 3.dp, y = (-2).dp).size(8.dp).clip(CircleShape).background(Color(0xFF34C759)))
            }
        }
    }
}

/** Full screen: the live screen page (noVNC) with take-over and hand-back. */
@Composable
fun CloudScreenDialog(state: CloudFloatState, botName: String) {
    val palette = LocalPalette.current
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf<String?>(null) }
    var working by remember { mutableStateOf(false) }
    val takenOver = state.status?.takeover == true
    LaunchedEffect(Unit) { url = runCatching { state.server.screenUrl(state.botId, control = takenOver) }.getOrNull() }
    Dialog(
        onDismissRequest = { state.expanded = false },
        properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
    ) {
        Column(Modifier.fillMaxSize().background(Color(0xFF0E0F13))) {
            Row(
                Modifier.fillMaxWidth().background(palette.background).statusBarsPadding().padding(horizontal = 6.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = { state.expanded = false }) {
                    Icon(Icons.Rounded.ExpandMore, contentDescription = stringResource(R.string.computer_float_minimise), tint = palette.text)
                }
                Column(Modifier.weight(1f)) {
                    Text(state.window ?: botName, style = MaterialTheme.typography.titleSmall, color = palette.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(stringResource(state.activityText), style = MaterialTheme.typography.labelSmall, color = palette.secondary, maxLines = 1)
                }
                Spacer(Modifier.width(8.dp))
                Button(
                    enabled = !working && state.running,
                    colors = ButtonDefaults.buttonColors(containerColor = if (takenOver) Color(0xFF2F7BF6) else palette.accent),
                    onClick = {
                        working = true
                        scope.launch {
                            if (runCatching { state.server.setTakeover(state.botId, !takenOver) }.isSuccess) {
                                state.refresh()
                                url = null
                                url = runCatching { state.server.screenUrl(state.botId, control = !takenOver) }.getOrNull()
                            }
                            working = false
                        }
                    },
                ) {
                    Icon(Icons.Rounded.PanTool, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(if (takenOver) R.string.computer_hand_back else R.string.computer_take_over))
                }
            }
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                val page = url
                if (page == null) {
                    CircularProgressIndicator(color = Color.White, modifier = Modifier.size(28.dp), strokeWidth = 2.dp)
                } else {
                    ScreenWebView(page)
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun ScreenWebView(url: String) {
    AndroidView(
        factory = { context ->
            WebView(context).apply {
                // A wrap_content WebView reports 100vh as 0, which sizes the screen page's frame to nothing.
                layoutParams = ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT)
                setBackgroundColor(AndroidColor.BLACK)
                settings.javaScriptEnabled = true
                settings.domStorageEnabled = true
                webViewClient = WebViewClient()
                loadUrl(url)
            }
        },
        update = { view -> if (view.url != url) view.loadUrl(url) },
        onRelease = { it.destroy() },
        modifier = Modifier.fillMaxSize(),
    )
}
