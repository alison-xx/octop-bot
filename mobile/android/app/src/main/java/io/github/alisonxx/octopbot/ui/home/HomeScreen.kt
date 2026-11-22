package io.github.alisonxx.octopbot.ui.home

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.CloudOff
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Groups
import androidx.compose.material.icons.rounded.SmartToy
import androidx.compose.material.icons.rounded.Palette
import androidx.compose.material.icons.rounded.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.TextButton
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
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
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
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
import io.github.alisonxx.octopbot.ui.common.relativeTime
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme

/** Everything the directory shows; separate from the ViewModel so previews can feed it. */
data class DirectoryState(
    val bots: List<BotProfile>,
    val groups: List<GroupSummary>,
    val previews: Map<String, BotPreview>,
    val replying: Set<String>,
    val showGroups: Boolean,
    /** Shown as a banner when a refresh failed and cached Bots are on screen. */
    val error: String? = null,
)

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
    Directory(
        state = DirectoryState(
            bots = bots,
            groups = groups,
            previews = previews,
            replying = replying,
            showGroups = backend.supportsGroups,
            error = error,
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
) {
    val palette = LocalPalette.current
    var query by rememberSaveable { mutableStateOf("") }
    val bots = state.bots.filter { query.isBlank() || it.name.contains(query.trim(), ignoreCase = true) }
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
            SearchField(query, onQueryChange = { query = it }, modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
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
private fun SearchField(query: String, onQueryChange: (String) -> Unit, modifier: Modifier = Modifier) {
    val palette = LocalPalette.current
    Row(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(14.dp))
            .background(palette.surface)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Rounded.Search, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Box(Modifier.weight(1f)) {
            if (query.isEmpty()) {
                Text(stringResource(R.string.home_search), style = MaterialTheme.typography.bodyLarge, color = palette.secondary)
            }
            BasicTextField(
                value = query,
                onValueChange = onQueryChange,
                singleLine = true,
                textStyle = MaterialTheme.typography.bodyLarge.copy(color = palette.text),
                cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                modifier = Modifier.fillMaxWidth(),
            )
        }
        if (query.isNotEmpty()) {
            Icon(
                Icons.Rounded.Close,
                contentDescription = stringResource(R.string.common_close),
                tint = palette.secondary,
                modifier = Modifier.size(20.dp).clip(CircleShape).clickable { onQueryChange("") },
            )
        }
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
    val haptics = LocalHapticFeedback.current
    var menu by remember { mutableStateOf(false) }
    Box {
        Row(
            Modifier
                .fillMaxWidth()
                .combinedClickable(
                    onClick = onClick,
                    onLongClick = {
                        haptics.performHapticFeedback(HapticFeedbackType.LongPress)
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
                }
                Text(
                    if (replying) stringResource(R.string.chat_thinking) else preview?.text ?: bot.subtitle.orEmpty(),
                    style = MaterialTheme.typography.bodyMedium,
                    color = palette.secondary,
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
                    "engineer" to BotPreview("The crash comes from a null adapter in onResume().", now - 3 * 3_600_000),
                ),
                replying = setOf("researcher"),
                showGroups = true,
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
