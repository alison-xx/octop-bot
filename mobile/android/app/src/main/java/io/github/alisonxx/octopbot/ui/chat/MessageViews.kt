package io.github.alisonxx.octopbot.ui.chat

import android.content.ClipData
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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Build
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.ExpandLess
import androidx.compose.material.icons.rounded.ExpandMore
import androidx.compose.material.icons.rounded.Lightbulb
import androidx.compose.material.icons.rounded.Refresh
import androidx.compose.material.icons.automirrored.rounded.VolumeUp
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import com.mikepenz.markdown.m3.Markdown
import com.mikepenz.markdown.m3.markdownColor
import com.mikepenz.markdown.m3.markdownTypography
import com.mikepenz.markdown.model.rememberMarkdownState
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.ChatMessage
import io.github.alisonxx.octopbot.model.MessageRole
import io.github.alisonxx.octopbot.model.MessageStatus
import io.github.alisonxx.octopbot.model.ToolStep
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.launch

/** What a long-press can do with a message. */
class MessageActions(
    val readAloud: (String) -> Unit,
    /** Confirms a copy (snackbar). */
    val copied: () -> Unit,
    /** Present only for the last assistant reply. */
    val retry: (() -> Unit)?,
)

@Composable
fun MessageRow(message: ChatMessage, bot: BotProfile, motion: BotMotion, actions: MessageActions, modifier: Modifier = Modifier) {
    var menu by remember { mutableStateOf(false) }
    Box(modifier) {
        if (message.role == MessageRole.User) {
            UserBubble(message, onLongPress = { menu = true })
        } else {
            AssistantReply(message, bot, motion, onLongPress = { menu = true }, onRetry = actions.retry)
        }
        MessageMenu(message, expanded = menu, onDismiss = { menu = false }, actions = actions)
    }
}

@OptIn(ExperimentalFoundationApi::class)
private fun Modifier.longPress(onLongPress: () -> Unit, haptic: () -> Unit) =
    combinedClickable(onClick = {}, onLongClick = { haptic(); onLongPress() })

@Composable
private fun UserBubble(message: ChatMessage, onLongPress: () -> Unit) {
    val palette = LocalPalette.current
    val haptics = LocalHapticFeedback.current
    Column(Modifier.fillMaxWidth().padding(start = 48.dp), horizontalAlignment = Alignment.End) {
        if (message.images.isNotEmpty()) {
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.padding(bottom = 6.dp)) {
                for (image in message.images.take(4)) {
                    AsyncImage(
                        model = image,
                        contentDescription = null,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.size(96.dp).clip(RoundedCornerShape(16.dp)).background(palette.raised),
                    )
                }
            }
        }
        if (message.text.isNotEmpty()) {
            Text(
                message.text,
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier
                    .clip(RoundedCornerShape(20.dp))
                    .longPress(onLongPress) { haptics.performHapticFeedback(HapticFeedbackType.LongPress) }
                    .background(palette.surface)
                    .padding(horizontal = 16.dp, vertical = 10.dp),
            )
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AssistantReply(message: ChatMessage, bot: BotProfile, motion: BotMotion, onLongPress: () -> Unit, onRetry: (() -> Unit)?) {
    val palette = LocalPalette.current
    val haptics = LocalHapticFeedback.current
    val streaming = message.status == MessageStatus.Streaming
    Row(
        Modifier
            .fillMaxWidth()
            .longPress(onLongPress) { haptics.performHapticFeedback(HapticFeedbackType.LongPress) },
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
            (message.status as? MessageStatus.Failed)?.let { failed ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        failed.message ?: stringResource(R.string.chat_failed),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    if (onRetry != null) {
                        Spacer(Modifier.width(8.dp))
                        Text(
                            stringResource(R.string.chat_retry),
                            style = MaterialTheme.typography.labelLarge,
                            color = palette.text,
                            modifier = Modifier
                                .clip(CircleShape)
                                .clickable(onClick = onRetry)
                                .background(palette.raised)
                                .padding(horizontal = 12.dp, vertical = 6.dp),
                        )
                    }
                }
            }
        }
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
            h1 = type.headlineSmall,
            h2 = type.titleLarge,
            h3 = type.titleMedium,
            h4 = type.titleSmall,
            h5 = type.titleSmall,
            h6 = type.titleSmall,
            text = type.bodyLarge,
            paragraph = type.bodyLarge,
            bullet = type.bodyLarge,
            list = type.bodyLarge,
            ordered = type.bodyLarge,
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
private fun ThinkingRow(thinking: String, thinkingNow: Boolean) {
    val palette = LocalPalette.current
    var open by rememberSaveable { mutableStateOf(false) }
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
                style = MaterialTheme.typography.bodyMedium,
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
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    DropdownMenu(expanded = expanded, onDismissRequest = onDismiss) {
        if (message.text.isNotEmpty()) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.common_copy)) },
                leadingIcon = { Icon(Icons.Rounded.ContentCopy, null) },
                onClick = {
                    onDismiss()
                    scope.launch {
                        clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Octop Bot", message.text)))
                        actions.copied()
                    }
                },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.chat_read_aloud)) },
                leadingIcon = { Icon(Icons.AutoMirrored.Rounded.VolumeUp, null) },
                onClick = {
                    onDismiss()
                    actions.readAloud(message.text)
                },
            )
        }
        actions.retry?.let { retry ->
            if (message.role == MessageRole.Assistant) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.chat_retry)) },
                    leadingIcon = { Icon(Icons.Rounded.Refresh, null) },
                    onClick = {
                        onDismiss()
                        retry()
                    },
                )
            }
        }
    }
}

/** Keeps a long reply readable on tablets. */
val MessageMaxWidth = Modifier.widthIn(max = 720.dp)
