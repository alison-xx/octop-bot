package io.github.alisonxx.octopbot.ui.home

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.CloudOff
import androidx.compose.material.icons.rounded.SystemUpdate
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Groups
import androidx.compose.material.icons.rounded.SmartToy
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.TextButton
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.DpOffset
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.GraphicEq
import androidx.compose.material.icons.rounded.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.character.GroupCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.store.BotPreview
import io.github.alisonxx.octopbot.store.Previews
import io.github.alisonxx.octopbot.ui.common.SearchField
import io.github.alisonxx.octopbot.ui.common.accentOf
import io.github.alisonxx.octopbot.ui.common.relativeTime
import io.github.alisonxx.octopbot.ui.common.rememberHaptics
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import io.github.alisonxx.octopbot.update.UpdatePhase
import io.github.alisonxx.octopbot.update.UpdateSelection

/** Everything the directory shows; separate from the ViewModel so previews can feed it. */
data class DirectoryState(
    val bots: List<BotProfile>,
    val groups: List<GroupSummary>,
    val previews: Map<String, BotPreview>,
    val replying: Set<String>,
    val showGroups: Boolean,
    /** Shown as a banner when a refresh failed and cached Bots are on screen. */
    val error: String? = null,
    /** A newer version, until its banner is closed. */
    val update: UpdateBanner? = null,
)

data class UpdateBanner(val version: String, val versionCode: Int, val urgent: Boolean, val phase: UpdatePhase)

@Composable
fun HomeScreen(
    model: AppViewModel,
    onOpenBot: (String) -> Unit,
    onOpenGroup: (String) -> Unit,
    onEditBot: (String) -> Unit,
    onNewBot: () -> Unit,
    onSettings: () -> Unit,
    onVoice: (String) -> Unit,
) {
    var newGroup by rememberSaveable { mutableStateOf(false) }
    val session by model.session.collectAsStateWithLifecycle()
    val backend = (session as? SessionState.Ready)?.backend ?: return
    val bots by model.bots.collectAsStateWithLifecycle()
    val groups by model.groups.collectAsStateWithLifecycle()
    val previews by model.previews.collectAsStateWithLifecycle()
    val replying by model.replying.collectAsStateWithLifecycle()
    val lastBot by model.lastBotId.collectAsStateWithLifecycle()
    val error by model.directoryError.collectAsStateWithLifecycle()
    val refreshing by model.refreshing.collectAsStateWithLifecycle()
    val update by model.update.collectAsStateWithLifecycle()
    val dismissedUpdate by model.dismissedUpdate.collectAsStateWithLifecycle()
    Directory(
        state = DirectoryState(
            bots = bots,
            groups = groups,
            previews = previews,
            replying = replying,
            showGroups = backend.supportsGroups,
            error = error,
            update = update.offer?.takeIf { UpdateSelection.showBanner(it, dismissedUpdate) }
                ?.let { UpdateBanner(it.version, it.versionCode, it.urgent, update.phase) },
        ),
        refreshing = refreshing,
        onRefresh = model::refreshDirectory,
        onOpenBot = { model.noteBotOpened(it); onOpenBot(it) },
        onOpenGroup = onOpenGroup,
        onEditBot = onEditBot,
        onNewBot = onNewBot,
        onSettings = onSettings,
        onVoice = { botId ->
            val target = botId ?: lastBot?.takeIf { id -> bots.any { it.id == id } } ?: bots.firstOrNull()?.id
            if (target != null) onVoice(target)
        },
        onDeleteBot = model::deleteBot,
        onNewGroup = { newGroup = true },
        onUpdate = model::startUpdate,
        onCancelUpdate = model::cancelUpdateDownload,
        onDismissUpdate = { model.dismissUpdate(it) },
    )
    if (newGroup) NewGroupSheet(bots, onCreate = model::createGroup, onDismiss = { newGroup = false })
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Directory(
    state: DirectoryState,
    refreshing: Boolean,
    onRefresh: () -> Unit,
    onOpenBot: (String) -> Unit,
    onOpenGroup: (String) -> Unit,
    onEditBot: (String) -> Unit,
    onNewBot: () -> Unit,
    onSettings: () -> Unit,
    /** null opens voice with the last-used Bot. */
    onVoice: (String?) -> Unit,
    onDeleteBot: (BotProfile) -> Unit,
    onNewGroup: () -> Unit,
    onUpdate: () -> Unit = {},
    onCancelUpdate: () -> Unit = {},
    /** The version code whose banner was closed. */
    onDismissUpdate: (Int) -> Unit = {},
) {
    val palette = LocalPalette.current
    var query by rememberSaveable { mutableStateOf("") }
    val bots = Previews.directoryOrder(state.bots, state.previews)
        .filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }
    val groups = state.groups.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }
    var deleting by remember { mutableStateOf<BotProfile?>(null) }
    Box(Modifier.fillMaxSize()) {
        Column(Modifier.fillMaxSize()) {
            Row(
                Modifier
                    .fillMaxWidth()
                    .statusBarsPadding()
                    .padding(horizontal = 4.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                IconButton(onClick = onSettings) {
                    Icon(Icons.Rounded.Settings, contentDescription = stringResource(R.string.settings_title))
                }
                Spacer(Modifier.weight(1f))
                // On a server "+" also creates groups.
                var addMenu by remember { mutableStateOf(false) }
                Box {
                    IconButton(onClick = { if (state.showGroups) addMenu = true else onNewBot() }) {
                        Icon(Icons.Rounded.Add, contentDescription = stringResource(R.string.bot_new))
                    }
                    DropdownMenu(expanded = addMenu, onDismissRequest = { addMenu = false }) {
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.bot_new)) },
                            leadingIcon = { Icon(Icons.Rounded.SmartToy, null) },
                            onClick = { addMenu = false; onNewBot() },
                        )
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.groups_new)) },
                            leadingIcon = { Icon(Icons.Rounded.Groups, null) },
                            onClick = { addMenu = false; onNewGroup() },
                        )
                    }
                }
            }
            Text(
                "Octop Bot",
                style = MaterialTheme.typography.headlineLarge,
                modifier = Modifier.padding(start = 20.dp, top = 4.dp, bottom = 8.dp),
            )
            state.update?.let { UpdateBannerRow(it, onUpdate, onCancelUpdate, onDismiss = { onDismissUpdate(it.versionCode) }) }
            SearchField(
                query = query,
                onQueryChange = { query = it },
                placeholder = stringResource(R.string.home_search),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
            )
            state.error?.let { ErrorBanner(it, onRetry = onRefresh) }
            PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.weight(1f)) {
                LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 112.dp)) {
                    items(bots, key = { it.id }) { bot ->
                        BotRow(
                            bot = bot,
                            preview = state.previews[bot.id],
                            replying = bot.id in state.replying,
                            onClick = { onOpenBot(bot.id) },
                            onEdit = { onEditBot(bot.id) },
                            onVoice = { onVoice(bot.id) },
                            onDelete = if (bot.isLocal) ({ deleting = bot }) else null,
                        )
                    }
                    if (state.showGroups && (groups.isNotEmpty() || query.isBlank())) {
                        item(key = "groups-header") {
                            Text(
                                stringResource(R.string.groups_title),
                                style = MaterialTheme.typography.titleSmall,
                                color = palette.secondary,
                                modifier = Modifier.padding(start = 20.dp, top = 20.dp, bottom = 6.dp),
                            )
                        }
                        if (state.groups.isEmpty() && query.isBlank()) {
                            item(key = "groups-empty") {
                                Text(
                                    stringResource(R.string.groups_empty),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = palette.secondary,
                                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                                )
                            }
                        }
                        items(groups, key = { "group-" + it.id }) { group ->
                            val members = group.memberIds.mapNotNull { id -> state.bots.firstOrNull { it.id == id } }
                            GroupRow(group, members, onClick = { onOpenGroup(group.id) })
                        }
                    }
                }
            }
        }
        FloatingActionButton(
            onClick = { onVoice(null) },
            shape = CircleShape,
            containerColor = palette.text,
            contentColor = palette.background,
            modifier = Modifier
                .align(Alignment.BottomEnd)
                .navigationBarsPadding()
                .padding(20.dp)
                .size(60.dp),
        ) {
            Icon(Icons.Rounded.GraphicEq, contentDescription = stringResource(R.string.voice_title), modifier = Modifier.size(28.dp))
        }
    }
    deleting?.let { bot ->
        AlertDialog(
            onDismissRequest = { deleting = null },
            text = { Text(stringResource(R.string.bot_delete_confirm, bot.name)) },
            confirmButton = {
                TextButton(onClick = { deleting = null; onDeleteBot(bot) }) {
                    Text(stringResource(R.string.common_delete), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { deleting = null }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
}

@Composable
private fun ErrorBanner(message: String, onRetry: () -> Unit) {
    val palette = LocalPalette.current
    Row(
        Modifier
            .padding(horizontal = 16.dp, vertical = 6.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(palette.raised)
            .padding(start = 12.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Rounded.CloudOff, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(10.dp))
        Text(message, style = MaterialTheme.typography.bodyMedium, color = palette.secondary, modifier = Modifier.weight(1f))
        TextButton(onClick = onRetry) { Text(stringResource(R.string.chat_retry)) }
    }
}

/** "Version X is available" with Update, download progress, and a close button that hides this version for good. */
@Composable
private fun UpdateBannerRow(banner: UpdateBanner, onUpdate: () -> Unit, onCancel: () -> Unit, onDismiss: () -> Unit) {
    val palette = LocalPalette.current
    val phase = banner.phase
    Column(
        Modifier
            .padding(horizontal = 16.dp, vertical = 6.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(palette.raised)
            .padding(start = 12.dp, top = 4.dp, bottom = 4.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                Icons.Rounded.SystemUpdate,
                contentDescription = null,
                tint = if (banner.urgent) MaterialTheme.colorScheme.error else palette.text,
                modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    stringResource(if (banner.urgent) R.string.update_banner_urgent else R.string.update_banner, banner.version),
                    style = MaterialTheme.typography.bodyMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = palette.text,
                )
                val detail = when (phase) {
                    is UpdatePhase.Downloading -> if (phase.percent < 0) {
                        stringResource(R.string.update_status_downloading_plain)
                    } else {
                        stringResource(R.string.update_status_downloading, phase.percent)
                    }
                    is UpdatePhase.DownloadFailed -> stringResource(
                        if (phase.integrity) R.string.update_status_verify_failed else R.string.update_status_download_failed,
                    )
                    else -> null
                }
                detail?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = palette.secondary) }
            }
            when (phase) {
                is UpdatePhase.Downloading -> TextButton(onClick = onCancel) { Text(stringResource(R.string.common_cancel)) }
                is UpdatePhase.DownloadFailed -> TextButton(onClick = onUpdate) { Text(stringResource(R.string.chat_retry)) }
                else -> TextButton(onClick = onUpdate) { Text(stringResource(R.string.update_action)) }
            }
            IconButton(onClick = onDismiss) {
                Icon(Icons.Rounded.Close, contentDescription = stringResource(R.string.common_close), tint = palette.secondary)
            }
        }
        if (phase is UpdatePhase.Downloading) {
            val progress = Modifier.fillMaxWidth().padding(end = 12.dp, top = 2.dp, bottom = 6.dp)
            if (phase.percent < 0) {
                LinearProgressIndicator(progress, color = palette.text, trackColor = palette.hairline)
            } else {
                LinearProgressIndicator(
                    progress = { phase.percent / 100f },
                    modifier = progress,
                    color = palette.text,
                    trackColor = palette.hairline,
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun BotRow(
    bot: BotProfile,
    preview: BotPreview?,
    replying: Boolean,
    onClick: () -> Unit,
    onEdit: () -> Unit,
    onVoice: () -> Unit,
    onDelete: (() -> Unit)?,
) {
    val palette = LocalPalette.current
    val haptics = rememberHaptics()
    val unread = preview?.unread == true && !replying
    var menu by remember { mutableStateOf(false) }
    Box {
        Row(
            Modifier
                .fillMaxWidth()
                .combinedClickable(
                    onClick = onClick,
                    onLongClick = {
                        haptics.longPress()
                        menu = true
                    },
                )
                .padding(horizontal = 20.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            BotCharacter(bot.look, 48.dp, motion = if (replying) BotMotion.Working else BotMotion.Idle, seed = bot.id)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        bot.name,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f),
                    )
                    preview?.let {
                        Text(relativeTime(it.at), style = MaterialTheme.typography.labelMedium, color = palette.secondary)
                    }
                    if (unread) {
                        val label = stringResource(R.string.home_unread)
                        Spacer(Modifier.width(6.dp))
                        Box(
                            Modifier
                                .size(9.dp)
                                .clip(CircleShape)
                                .background(accentOf(bot.look))
                                .semantics { contentDescription = label },
                        )
                    }
                }
                Text(
                    // Previews saved by older versions may still hold Markdown marks.
                    if (replying) stringResource(R.string.chat_replying) else preview?.text?.let(Previews::snippet) ?: bot.subtitle.orEmpty(),
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (unread) palette.text else palette.secondary,
                    fontWeight = if (unread) FontWeight.SemiBold else null,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }, offset = DpOffset(72.dp, 0.dp)) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.bot_edit)) },
                leadingIcon = { Icon(Icons.Rounded.Palette, null) },
                onClick = { menu = false; onEdit() },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.voice_title)) },
                leadingIcon = { Icon(Icons.Rounded.GraphicEq, null) },
                onClick = { menu = false; onVoice() },
            )
            onDelete?.let { delete ->
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.bot_delete), color = MaterialTheme.colorScheme.error) },
                    leadingIcon = { Icon(Icons.Rounded.Delete, null, tint = MaterialTheme.colorScheme.error) },
                    onClick = { menu = false; delete() },
                )
            }
        }
    }
}

@Composable
private fun GroupRow(group: GroupSummary, members: List<BotProfile>, onClick: () -> Unit) {
    val palette = LocalPalette.current
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick)
            .padding(horizontal = 20.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        GroupCharacter(members.map { it.id to it.look }, 48.dp)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(group.name, style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                pluralStringResource(R.plurals.groups_member_count, group.memberIds.size, group.memberIds.size),
                style = MaterialTheme.typography.bodyMedium,
                color = palette.secondary,
            )
        }
    }
}

private val previewBots = listOf(
    BotProfile("chief", "Chief", "Your main assistant", Look.chief, isChief = true),
    BotProfile("researcher", "Researcher", "Research and analysis", Look("acorn", "green")),
    BotProfile("engineer", "Engineer", "Code and debugging", Look("beacon", "cobalt")),
    BotProfile("translator", "Translator", "Translation", Look("wave", "sky")),
    BotProfile("writer", "Writer", "Drafting and editing", Look("cushion", "violet")),
    BotProfile("companion", "Buddy", "Just chat", Look("bunny", "tangerine")),
)

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 800)
@Composable
private fun DirectoryPreview() {
    val now = System.currentTimeMillis()
    OctopTheme(dark = true) {
        Directory(
            state = DirectoryState(
                bots = previewBots,
                groups = listOf(GroupSummary("g1", "Launch crew", "chief", listOf("chief", "researcher", "engineer"))),
                previews = mapOf(
                    "chief" to BotPreview("Here's a plan for your week, split into three focus blocks.", now - 4 * 60_000),
                    "engineer" to BotPreview("The crash comes from a null adapter in onResume().", now - 3 * 3_600_000, unread = true),
                ),
                replying = setOf("researcher"),
                showGroups = true,
                update = UpdateBanner("0.2.0", 2, urgent = false, phase = UpdatePhase.Downloading(42)),
            ),
            refreshing = false,
            onRefresh = {},
            onOpenBot = {},
            onOpenGroup = {},
            onEditBot = {},
            onNewBot = {},
            onSettings = {},
            onVoice = {},
            onDeleteBot = {},
            onNewGroup = {},
        )
    }
}
