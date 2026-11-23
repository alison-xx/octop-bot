package io.github.alisonxx.octopbot.ui.group

import android.content.ClipData
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.rounded.ContentCopy
import androidx.compose.material.icons.rounded.ErrorOutline
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.GroupRoom
import io.github.alisonxx.octopbot.app.GroupRoomState
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.character.GroupCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.GroupDraft
import io.github.alisonxx.octopbot.model.GroupMessage
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.Timeline
import io.github.alisonxx.octopbot.net.Mentions
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.ui.chat.Composer
import io.github.alisonxx.octopbot.ui.chat.MarkdownText
import io.github.alisonxx.octopbot.ui.chat.TimeSeparator
import io.github.alisonxx.octopbot.ui.chat.TypingDots
import io.github.alisonxx.octopbot.ui.chat.rememberDictation
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.BottomFade
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.chatText
import io.github.alisonxx.octopbot.ui.common.rememberHaptics
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import kotlinx.coroutines.launch

@Composable
fun GroupRoomScreen(model: AppViewModel, groupId: String, onBack: () -> Unit) {
    val session by model.session.collectAsStateWithLifecycle()
    val server = (session as? SessionState.Ready)?.backend as? ServerBackend ?: return
    val groups by model.groups.collectAsStateWithLifecycle()
    val bots by model.bots.collectAsStateWithLifecycle()
    val group = groups.firstOrNull { it.id == groupId } ?: return
    val room = viewModel(key = "group-$groupId") { GroupRoom(server, groupId, model) }
    val state by room.state.collectAsStateWithLifecycle()
    var draft by rememberSaveable { mutableStateOf("") }
    var info by rememberSaveable { mutableStateOf(false) }
    val members = group.memberIds.mapNotNull { id -> bots.firstOrNull { it.id == id } }
    val dictation = rememberDictation(model.voiceInput, server) { heard ->
        draft = listOf(draft.trimEnd(), heard).filter { it.isNotEmpty() }.joinToString(" ")
    }
    val haptics = rememberHaptics()
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val copied = stringResource(R.string.common_copied)
    GroupRoomContent(
        group = group,
        members = members,
        state = state,
        draft = draft,
        onDraftChange = { draft = it },
        dictating = dictation.active,
        onDictate = dictation.toggle,
        onSend = {
            if (room.send(draft, members.map { Mentions.Member(it.id, it.name) })) {
                haptics.tap()
                draft = ""
            }
        },
        onRetry = room::retry,
        onCopy = { text ->
            haptics.tap()
            scope.launch {
                clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Octop Bot", text)))
                model.notice(copied)
            }
        },
        onBack = onBack,
        onInfo = {
            room.loadInfo()
            info = true
        },
    )
    if (info) GroupInfoSheet(group, members, state, onDismiss = { info = false })
}

@Composable
fun GroupRoomContent(
    group: GroupSummary,
    members: List<BotProfile>,
    state: GroupRoomState,
    draft: String,
    onDraftChange: (String) -> Unit,
    dictating: Boolean,
    onDictate: () -> Unit,
    onSend: () -> Unit,
    onBack: () -> Unit,
    onInfo: () -> Unit,
    onCopy: (String) -> Unit,
    onRetry: (String) -> Unit = {},
) {
    val palette = LocalPalette.current
    val density = LocalDensity.current
    var composerHeight by remember { mutableStateOf(96.dp) }
    val list = rememberLazyListState()
    // Local echoes are shown as user rows after the server's messages until the server lists them.
    val failed = state.pending.filter { it.failed }.map { it.id }.toSet()
    val sendingIds = state.pending.filterNot { it.failed }.map { it.id }.toSet()
    val timeline = state.messages + state.pending.map { GroupMessage(it.id, "user", null, it.text, it.createdAt, it.requestId) }
    val separators = remember(timeline) { Timeline.separators(timeline.map { it.createdAt }) }
    LaunchedEffect(timeline.size, state.drafts.size) { list.animateScrollToItem(0) }
    val query = Mentions.activeQuery(draft)
    val suggestions = query?.let { q -> members.filter { it.name.startsWith(q, ignoreCase = true) || it.id.startsWith(q) } }.orEmpty()

    Box(Modifier.fillMaxSize().imePadding()) {
        Column(Modifier.fillMaxSize()) {
            TopBar(
                titleInset = 64.dp,
                leading = { BackButton(onBack) },
                trailing = {
                    IconButton(onClick = onInfo) { Icon(Icons.Outlined.Info, contentDescription = stringResource(R.string.groups_info)) }
                },
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    GroupCharacter(members.map { it.id to it.look }, 30.dp)
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text(group.name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(
                            pluralStringResource(R.plurals.groups_member_count, members.size, members.size),
                            style = MaterialTheme.typography.labelSmall,
                            color = palette.secondary,
                        )
                    }
                }
            }
            LazyColumn(
                state = list,
                reverseLayout = true,
                contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 8.dp, bottom = composerHeight + 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp, Alignment.Bottom),
                modifier = Modifier.weight(1f).fillMaxWidth(),
            ) {
                items(state.drafts.asReversed(), key = { "draft-" + it.agentId }) { draft ->
                    BotMessage(members.firstOrNull { it.id == draft.agentId }, draft.agentId, draft.text, live = true)
                }
                itemsIndexed(timeline.asReversed(), key = { _, message -> message.id }) { index, message ->
                    Column {
                        if (separators.getOrElse(timeline.lastIndex - index) { false }) TimeSeparator(message.createdAt)
                        CopyOnLongPress(message.text, onCopy) {
                            when (message.role) {
                                "user" -> UserMessage(
                                    message.text,
                                    sending = message.id in sendingIds,
                                    failed = message.id in failed,
                                    onRetry = { message.requestId?.let(onRetry) },
                                )
                                "error" -> Text(
                                    message.text,
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = MaterialTheme.colorScheme.error,
                                    modifier = Modifier.padding(start = 40.dp),
                                )
                                else -> BotMessage(
                                    members.firstOrNull { it.id == message.agentId },
                                    message.agentId.orEmpty(),
                                    message.text,
                                    live = false,
                                )
                            }
                        }
                    }
                }
            }
        }
        BottomFade(composerHeight + 16.dp, Modifier.align(Alignment.BottomCenter))
        Column(
            Modifier
                .align(Alignment.BottomCenter)
                .onSizeChanged { composerHeight = with(density) { it.height.toDp() } }
                .navigationBarsPadding()
                .padding(horizontal = 12.dp, vertical = 8.dp),
        ) {
            if (suggestions.isNotEmpty()) {
                Column(
                    Modifier
                        .padding(bottom = 8.dp)
                        .clip(RoundedCornerShape(18.dp))
                        .background(palette.raised),
                ) {
                    suggestions.forEach { member ->
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clickable { onDraftChange(draft.dropLast(query!!.length + 1) + "@" + member.name + " ") }
                                .padding(horizontal = 14.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            BotCharacter(member.look, 26.dp, seed = member.id)
                            Spacer(Modifier.width(10.dp))
                            Text(member.name, style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                }
            }
            Composer(
                text = draft,
                onTextChange = onDraftChange,
                images = emptyList(),
                onRemoveImage = {},
                streaming = false,
                dictating = dictating,
                placeholder = stringResource(R.string.groups_placeholder),
                onPickPhotos = {},
                onTakePhoto = {},
                onSend = onSend,
                onStop = {},
                onDictate = onDictate,
                allowPhotos = false,
            )
        }
    }
}

/** Long-press shows a one-item menu: copy. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CopyOnLongPress(text: String, onCopy: (String) -> Unit, content: @Composable () -> Unit) {
    val haptics = rememberHaptics()
    var menu by remember { mutableStateOf(false) }
    Box(Modifier.combinedClickable(onClick = {}, onLongClick = { haptics.longPress(); menu = true })) {
        content()
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.common_copy)) },
                leadingIcon = { Icon(Icons.Rounded.ContentCopy, null) },
                onClick = {
                    menu = false
                    onCopy(text)
                },
            )
        }
    }
}

/** The user's message; a local echo is dimmed while sending, and a failed one offers a retry. */
@Composable
private fun UserMessage(text: String, sending: Boolean = false, failed: Boolean = false, onRetry: () -> Unit = {}) {
    val palette = LocalPalette.current
    Column(Modifier.fillMaxWidth().padding(start = 48.dp), horizontalAlignment = Alignment.End) {
        Text(
            text,
            style = chatText(MaterialTheme.typography.bodyLarge),
            modifier = Modifier
                .alpha(if (sending) 0.7f else 1f)
                .clip(RoundedCornerShape(20.dp))
                .background(palette.surface)
                .padding(horizontal = 16.dp, vertical = 10.dp),
        )
        if (failed) {
            Row(
                Modifier
                    .padding(top = 4.dp)
                    .clip(RoundedCornerShape(10.dp))
                    .clickable(onClick = onRetry)
                    .padding(horizontal = 6.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Rounded.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp))
                Text(stringResource(R.string.groups_not_sent), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.error)
            }
        }
    }
}

@Composable
private fun BotMessage(bot: BotProfile?, agentId: String, text: String, live: Boolean) {
    val palette = LocalPalette.current
    Row(Modifier.fillMaxWidth()) {
        BotCharacter(bot?.look ?: Look.fallback, 30.dp, motion = if (live) BotMotion.Working else BotMotion.Idle, seed = agentId)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(bot?.name ?: agentId, style = MaterialTheme.typography.labelLarge, color = palette.secondary)
            if (text.isBlank()) TypingDots(Modifier.padding(top = 6.dp)) else MarkdownText(text)
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun GroupInfoSheet(group: GroupSummary, members: List<BotProfile>, state: GroupRoomState, onDismiss: () -> Unit) {
    val palette = LocalPalette.current
    ModalBottomSheet(onDismissRequest = onDismiss, containerColor = palette.surface, contentColor = palette.text) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).navigationBarsPadding(),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text(group.name, style = MaterialTheme.typography.titleLarge)
            InfoTitle(stringResource(R.string.groups_goal))
            Text(state.goal?.let { "${it.title} · ${it.status}" } ?: stringResource(R.string.groups_no_goal), style = MaterialTheme.typography.bodyLarge)
            InfoTitle(stringResource(R.string.groups_members))
            members.forEach { bot ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    BotCharacter(bot.look, 28.dp, seed = bot.id)
                    Spacer(Modifier.width(10.dp))
                    Text(bot.name, style = MaterialTheme.typography.bodyLarge)
                }
            }
            InfoTitle(stringResource(R.string.groups_memory))
            if (state.memory.isBlank()) {
                Text(stringResource(R.string.groups_memory_empty), color = palette.secondary)
            } else {
                MarkdownText(state.memory)
            }
            Spacer(Modifier.padding(bottom = 16.dp))
        }
    }
}

@Composable
private fun InfoTitle(text: String) {
    Text(text, style = MaterialTheme.typography.labelLarge, color = LocalPalette.current.secondary, modifier = Modifier.padding(top = 8.dp))
}

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 800)
@Composable
private fun GroupRoomPreview() {
    val chief = BotProfile("chief", "Chief", look = Look.chief, isChief = true)
    val researcher = BotProfile("r1", "Researcher", look = Look("acorn", "violet"))
    OctopTheme(dark = true) {
        GroupRoomContent(
            group = GroupSummary("g", "Launch Team", "chief", listOf("chief", "r1")),
            members = listOf(chief, researcher),
            state = GroupRoomState(
                messages = listOf(
                    GroupMessage("1", "user", null, "@Researcher what do users say about onboarding?", 0),
                    GroupMessage("2", "assistant", "r1", "Most feedback mentions the **sign-in step** being long.", 0),
                ),
                drafts = listOf(GroupDraft("chief", "Let's shorten it to one screen and")),
            ),
            draft = "@Re",
            onDraftChange = {},
            dictating = false,
            onDictate = {},
            onSend = {},
            onBack = {},
            onInfo = {},
            onCopy = {},
        )
    }
}
