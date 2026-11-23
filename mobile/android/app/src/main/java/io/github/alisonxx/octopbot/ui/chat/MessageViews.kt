package io.github.alisonxx.octopbot.ui.chat

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Build
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material.icons.rounded.Share
import androidx.compose.material.icons.rounded.StopCircle
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.Lightbulb
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.automirrored.rounded.VolumeUp
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.m3.markdownColor
import com.mikepenz.markdown.m3.markdownTypography
import com.mikepenz.markdown.model.rememberMarkdownState
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.QueuedMessage
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.Timeline
import io.github.alisonxx.octopbot.model.ToolStep
import io.github.alisonxx.octopbot.ui.common.LocalUiPrefs
import io.github.alisonxx.octopbot.ui.common.chatText
import io.github.alisonxx.octopbot.ui.common.rememberHaptics
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import java.time.ZoneId

/** What a message's action row and long-press menu can do. */
class MessageActions(
    /** Copies the text and confirms it. */
    val copy: (String) -> Unit,
    val readAloud: (ChatMessage) -> Unit,
    val stopReading: () -> Unit,
    val share: (String) -> Unit,
    /** User messages: put the text back into the composer. */
    val edit: (String) -> Unit,
    val openImage: (String) -> Unit,
    /** Present only for the last assistant reply. */
    val retry: (() -> Unit)?,
    /** This message is being read aloud right now. */
    val speaking: Boolean,
)

@Composable
fun MessageRow(message: ChatMessage, bot: BotProfile, motion: BotMotion, actions: MessageActions, modifier: Modifier = Modifier) {
    if (message.role == MessageRole.Note) {
        NoteCaption(message.text, modifier)
        return
    }
    var menu by remember { mutableStateOf(false) }
    Box(modifier) {
        if (message.role == MessageRole.User) {
            UserBubble(message, onLongPress = { menu = true }, onOpenImage = actions.openImage)
        } else {
            AssistantReply(message, bot, motion, actions, onLongPress = { menu = true })
        }
        // Anchored under the message: at the right edge for the user's bubble, the left for a reply.
        Box(Modifier.align(if (message.role == MessageRole.User) Alignment.BottomEnd else Alignment.BottomStart)) {
            MessageMenu(message, expanded = menu, onDismiss = { menu = false }, actions = actions)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
private fun Modifier.longPress(onLongPress: () -> Unit, haptic: () -> Unit) =
    combinedClickable(onClick = {}, onLongClick = { haptic(); onLongPress() })

/** A centered caption in the timeline, e.g. "Approved: Run command". */
@Composable
private fun NoteCaption(text: String, modifier: Modifier) {
    val palette = LocalPalette.current
    Box(modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
        Text(
            text,
            style = MaterialTheme.typography.labelMedium,
            color = palette.secondary,
            textAlign = TextAlign.Center,
            modifier = Modifier
                .clip(CircleShape)
                .background(palette.surface)
                .padding(horizontal = 12.dp, vertical = 5.dp),
        )
    }
}

/** A message written while a reply streams: dashed, "Queued", cancellable until it is sent. */
@Composable
fun QueuedBubble(message: QueuedMessage, onCancel: () -> Unit, modifier: Modifier = Modifier) {
    val palette = LocalPalette.current
    val dash = palette.secondary
    Column(modifier.fillMaxWidth().padding(start = 48.dp), horizontalAlignment = Alignment.End) {
        Row(
            Modifier
                .clip(RoundedCornerShape(20.dp))
                .drawBehind {
                    drawRoundRect(
                        color = dash,
                        cornerRadius = CornerRadius(20.dp.toPx()),
                        style = Stroke(width = 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 6f))),
                    )
                }
                .padding(start = 16.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            message.images.firstOrNull()?.let { image ->
                AsyncImage(
                    model = image.uri,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.padding(end = 8.dp).size(36.dp).clip(RoundedCornerShape(10.dp)),
                )
            }
            if (message.text.isNotEmpty()) {
                Text(
                    message.text,
                    style = chatText(MaterialTheme.typography.bodyLarge),
                    color = palette.secondary,
                    modifier = Modifier.weight(1f, fill = false).padding(vertical = 6.dp),
                )
            }
            IconButton(onClick = onCancel, modifier = Modifier.size(36.dp)) {
                Icon(Icons.Rounded.Close, contentDescription = stringResource(R.string.chat_queued_cancel), tint = palette.secondary, modifier = Modifier.size(18.dp))
            }
        }
        Text(
            stringResource(R.string.chat_queued),
            style = MaterialTheme.typography.labelSmall,
            color = palette.secondary,
            modifier = Modifier.padding(top = 4.dp, end = 8.dp),
        )
    }
}

/** A centered time caption between messages ("14:05", "Yesterday 14:05", "Nov 20 14:05"). */
@Composable
fun TimeSeparator(at: Long, modifier: Modifier = Modifier) {
    val yesterday = stringResource(R.string.time_yesterday)
    val locale = LocalConfiguration.current.locales[0]
    Text(
        Timeline.label(at, System.currentTimeMillis(), ZoneId.systemDefault(), locale) { yesterday.format(it) },
        style = MaterialTheme.typography.labelMedium,
        color = LocalPalette.current.secondary,
        textAlign = TextAlign.Center,
        modifier = modifier.fillMaxWidth().padding(top = 4.dp, bottom = 14.dp),
    )
}

/** Message photos; tap opens the full-screen viewer. */
@Composable
private fun MessageImages(images: List<String>, size: Dp, onOpen: (String) -> Unit, modifier: Modifier = Modifier) {
    val palette = LocalPalette.current
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = modifier) {
        for (image in images.take(4)) {
            AsyncImage(
                model = image,
                contentDescription = stringResource(R.string.image_open),
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .size(size)
                    .clip(RoundedCornerShape(16.dp))
                    .background(palette.raised)
                    .clickable { onOpen(image) },
            )
        }
    }
}

@Composable
private fun UserBubble(message: ChatMessage, onLongPress: () -> Unit, onOpenImage: (String) -> Unit) {
    val palette = LocalPalette.current
    val haptics = rememberHaptics()
    Column(Modifier.fillMaxWidth().padding(start = 48.dp), horizontalAlignment = Alignment.End) {
        if (message.images.isNotEmpty()) {
            MessageImages(message.images, 96.dp, onOpenImage, Modifier.padding(bottom = 6.dp))
        }
        if (message.text.isNotEmpty()) {
            Text(
                message.text,
                style = chatText(MaterialTheme.typography.bodyLarge),
                modifier = Modifier
                    .clip(RoundedCornerShape(20.dp))
                    .longPress(onLongPress, haptics::longPress)
                    .background(palette.surface)
                    .padding(horizontal = 16.dp, vertical = 10.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AssistantReply(message: ChatMessage, bot: BotProfile, motion: BotMotion, actions: MessageActions, onLongPress: () -> Unit) {
    val palette = LocalPalette.current
    val haptics = rememberHaptics()
    val streaming = message.status == MessageStatus.Streaming
    Row(
        Modifier
            .fillMaxWidth()
            .longPress(onLongPress, haptics::longPress),
    ) {
        BotCharacter(
            bot.look,
            26.dp,
            motion = if (streaming) motion else BotMotion.Idle,
            seed = bot.id,
            modifier = Modifier.padding(top = 1.dp),
        )
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (message.thinking.isNotEmpty()) ThinkingRow(message.thinking, thinkingNow = streaming && message.text.isEmpty())
            if (message.tools.size > 2) {
                ToolGroup(message.tools)
            } else if (message.tools.isNotEmpty()) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    message.tools.forEach { ToolChip(it) }
                }
            }
            when {
                message.text.isNotEmpty() -> MarkdownText(message.text)
                streaming && message.thinking.isEmpty() -> TypingDots(Modifier.padding(top = 8.dp))
            }
            if (message.images.isNotEmpty()) MessageImages(message.images, 160.dp, actions.openImage)
            (message.status as? MessageStatus.Failed)?.let { failed ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        failed.message ?: stringResource(R.string.chat_failed),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    actions.retry?.let { retry ->
                        Spacer(Modifier.width(8.dp))
                        Text(
                            stringResource(R.string.chat_retry),
                            style = MaterialTheme.typography.labelLarge,
                            color = palette.text,
                            modifier = Modifier
                                .clip(CircleShape)
                                .clickable(onClick = retry)
                                .background(palette.raised)
                                .padding(horizontal = 12.dp, vertical = 6.dp),
                        )
                    }
                }
            }
            if (message.status == MessageStatus.Done && message.text.isNotEmpty()) ReplyActions(message, actions)
        }
    }
}

/** Under a finished reply: copy · read aloud (stop while speaking) · share · retry (last reply). */
@Composable
private fun ReplyActions(message: ChatMessage, actions: MessageActions) {
    Row(Modifier.offset(x = (-8).dp), verticalAlignment = Alignment.CenterVertically) {
        SmallAction(Icons.Rounded.ContentCopy, stringResource(R.string.common_copy)) { actions.copy(message.text) }
        if (actions.speaking) {
            SmallAction(Icons.Rounded.StopCircle, stringResource(R.string.chat_stop_reading), actions.stopReading)
        } else {
            SmallAction(Icons.AutoMirrored.Rounded.VolumeUp, stringResource(R.string.chat_read_aloud)) { actions.readAloud(message) }
        }
        SmallAction(Icons.Rounded.Share, stringResource(R.string.chat_share)) { actions.share(message.text) }
        actions.retry?.let { SmallAction(Icons.Rounded.Refresh, stringResource(R.string.chat_retry), it) }
    }
}

@Composable
private fun SmallAction(icon: ImageVector, label: String, onClick: () -> Unit) {
    IconButton(onClick = onClick, modifier = Modifier.size(36.dp)) {
        Icon(icon, contentDescription = label, tint = LocalPalette.current.secondary, modifier = Modifier.size(18.dp))
    }
}

@Composable
fun MarkdownText(text: String, modifier: Modifier = Modifier) {
    val palette = LocalPalette.current
    val type = MaterialTheme.typography
    // retainState keeps the previous render while a streaming update re-parses, so text doesn't flicker.
    val state = rememberMarkdownState(text, retainState = true)
    Markdown(
        markdownState = state,
        colors = markdownColor(
            text = palette.text,
            codeBackground = palette.surface,
            inlineCodeBackground = palette.raised,
            dividerColor = palette.hairline,
            tableBackground = palette.surface,
        ),
        typography = markdownTypography(
            h1 = chatText(type.headlineSmall),
            h2 = chatText(type.titleLarge),
            h3 = chatText(type.titleMedium),
            h4 = chatText(type.titleSmall),
            h5 = chatText(type.titleSmall),
            h6 = chatText(type.titleSmall),
            text = chatText(type.bodyLarge),
            code = chatText(type.bodyMedium.copy(fontFamily = FontFamily.Monospace)),
            inlineCode = chatText(type.bodyLarge.copy(fontFamily = FontFamily.Monospace)),
            paragraph = chatText(type.bodyLarge),
            bullet = chatText(type.bodyLarge),
            list = chatText(type.bodyLarge),
            ordered = chatText(type.bodyLarge),
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
private fun ThinkingRow(thinking: String, thinkingNow: Boolean) {
    val palette = LocalPalette.current
    val expand = LocalUiPrefs.current.expandReasoning
    var open by rememberSaveable(expand) { mutableStateOf(expand) }
    Column {
        Row(
            Modifier.clip(RoundedCornerShape(8.dp)).clickable { open = !open }.padding(vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Rounded.Lightbulb, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(6.dp))
            Text(
                stringResource(if (thinkingNow) R.string.chat_thinking else R.string.chat_thought),
                style = MaterialTheme.typography.labelLarge,
                color = palette.secondary,
            )
            Icon(
                if (open) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                contentDescription = null,
                tint = palette.secondary,
                modifier = Modifier.size(18.dp),
            )
        }
        AnimatedVisibility(open) {
            Text(
                thinking.trim(),
                style = chatText(MaterialTheme.typography.bodyMedium),
                color = palette.secondary,
                modifier = Modifier
                    .padding(top = 4.dp)
                    .background(palette.surface, RoundedCornerShape(12.dp))
                    .padding(12.dp),
            )
        }
    }
}

/** More than two steps fold into one chip ("Used 3 tools · 5 steps"); tap to see them all. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ToolGroup(tools: List<ToolStep>) {
    val palette = LocalPalette.current
    var open by rememberSaveable { mutableStateOf(false) }
    val running = tools.lastOrNull { !it.done }
    val summary = if (running != null) {
        stringResource(R.string.chat_tool_running, running.name)
    } else {
        val distinct = tools.map { it.name }.distinct().size
        stringResource(
            R.string.chat_tools_summary,
            pluralStringResource(R.plurals.chat_tools_count, distinct, distinct),
            pluralStringResource(R.plurals.chat_steps_count, tools.size, tools.size),
        )
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(
            Modifier
                .clip(CircleShape)
                .background(palette.surface)
                .clickable { open = !open }
                .padding(start = 10.dp, end = 6.dp, top = 5.dp, bottom = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                if (running == null) Icons.Rounded.CheckCircle else Icons.Rounded.Build,
                contentDescription = null,
                tint = if (running == null) palette.secondary else MaterialTheme.colorScheme.primary,
                modifier = Modifier.size(14.dp),
            )
            Spacer(Modifier.width(6.dp))
            Text(summary, style = MaterialTheme.typography.labelMedium, color = palette.secondary)
            Icon(
                if (open) Icons.Rounded.ExpandLess else Icons.Rounded.ExpandMore,
                contentDescription = null,
                tint = palette.secondary,
                modifier = Modifier.size(16.dp),
            )
        }
        AnimatedVisibility(open) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                tools.forEach { ToolChip(it) }
            }
        }
    }
}

@Composable
private fun ToolChip(step: ToolStep) {
    val palette = LocalPalette.current
    Row(
        Modifier
            .background(palette.surface, CircleShape)
            .padding(horizontal = 10.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            if (step.done) Icons.Rounded.CheckCircle else Icons.Rounded.Build,
            contentDescription = null,
            tint = if (step.done) palette.secondary else MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(14.dp),
        )
        Spacer(Modifier.width(6.dp))
        Text(
            stringResource(if (step.done) R.string.chat_tool_done else R.string.chat_tool_running, step.name),
            style = MaterialTheme.typography.labelMedium,
            color = palette.secondary,
        )
    }
}

@Composable
fun TypingDots(modifier: Modifier = Modifier) {
    val transition = rememberInfiniteTransition(label = "typing")
    val palette = LocalPalette.current
    Row(modifier.height(12.dp), horizontalArrangement = Arrangement.spacedBy(5.dp), verticalAlignment = Alignment.CenterVertically) {
        repeat(3) { index ->
            val alpha by transition.animateFloat(
                initialValue = 0.25f,
                targetValue = 1f,
                animationSpec = infiniteRepeatable(
                    tween(600, delayMillis = index * 180),
                    repeatMode = RepeatMode.Reverse,
                ),
                label = "dot$index",
            )
            Box(Modifier.size(7.dp).alpha(alpha).background(palette.secondary, CircleShape))
        }
    }
}

@Composable
private fun MessageMenu(message: ChatMessage, expanded: Boolean, onDismiss: () -> Unit, actions: MessageActions) {
    val user = message.role == MessageRole.User
    DropdownMenu(expanded = expanded, onDismissRequest = onDismiss) {
        if (message.text.isEmpty()) return@DropdownMenu
        MenuItem(Icons.Rounded.ContentCopy, stringResource(R.string.common_copy), onDismiss) { actions.copy(message.text) }
        if (user) {
            MenuItem(Icons.Rounded.Edit, stringResource(R.string.chat_edit), onDismiss) { actions.edit(message.text) }
            return@DropdownMenu
        }
        if (actions.speaking) {
            MenuItem(Icons.Rounded.StopCircle, stringResource(R.string.chat_stop_reading), onDismiss, actions.stopReading)
        } else {
            MenuItem(Icons.AutoMirrored.Rounded.VolumeUp, stringResource(R.string.chat_read_aloud), onDismiss) { actions.readAloud(message) }
        }
        MenuItem(Icons.Rounded.Share, stringResource(R.string.chat_share), onDismiss) { actions.share(message.text) }
        actions.retry?.let { MenuItem(Icons.Rounded.Refresh, stringResource(R.string.chat_retry), onDismiss, it) }
    }
}

@Composable
private fun MenuItem(icon: ImageVector, label: String, dismiss: () -> Unit, onClick: () -> Unit) {
    DropdownMenuItem(
        text = { Text(label) },
        leadingIcon = { Icon(icon, null) },
        onClick = {
            dismiss()
            onClick()
        },
    )
}

/** Keeps a long reply readable on tablets. */
val MessageMaxWidth = Modifier.widthIn(max = 720.dp)
