package io.github.alisonxx.octopbot.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Edit
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.ConversationSummary
import io.github.alisonxx.octopbot.ui.common.relativeTime
import io.github.alisonxx.octopbot.ui.theme.LocalPalette

/** The current Bot's conversations: new chat, pick one, swipe to delete. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistorySheet(
    conversations: List<ConversationSummary>,
    currentId: String?,
    onNewChat: () -> Unit,
    onOpen: (ConversationSummary) -> Unit,
    onDelete: (ConversationSummary) -> Unit,
    onDismiss: () -> Unit,
) {
    val palette = LocalPalette.current
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = false),
        containerColor = palette.surface,
        contentColor = palette.text,
    ) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding()) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(stringResource(R.string.chat_history), style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                Row(
                    Modifier
                        .clip(CircleShape)
                        .background(palette.text)
                        .clickable(onClick = onNewChat)
                        .padding(horizontal = 14.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Rounded.Edit, contentDescription = null, tint = palette.background)
                    Spacer(Modifier.width(6.dp))
                    Text(stringResource(R.string.chat_new), color = palette.background, style = MaterialTheme.typography.labelLarge)
                }
            }
            Text(
                stringResource(R.string.drawer_recent),
                style = MaterialTheme.typography.labelLarge,
                color = palette.secondary,
                modifier = Modifier.padding(start = 20.dp, top = 12.dp, bottom = 4.dp),
            )
            if (conversations.isEmpty()) {
                Text(
                    stringResource(R.string.drawer_empty),
                    color = palette.secondary,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 24.dp),
                )
            }
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 520.dp)) {
                items(conversations, key = { it.id }) { conversation ->
                    ConversationRow(
                        conversation,
                        selected = conversation.id == currentId,
                        onOpen = { onOpen(conversation) },
                        onDelete = { onDelete(conversation) },
                    )
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ConversationRow(conversation: ConversationSummary, selected: Boolean, onOpen: () -> Unit, onDelete: () -> Unit) {
    val palette = LocalPalette.current
    val dismiss = rememberSwipeToDismissBoxState()
    SwipeToDismissBox(
        state = dismiss,
        enableDismissFromStartToEnd = false,
        onDismiss = { if (it == SwipeToDismissBoxValue.EndToStart) onDelete() },
        backgroundContent = {
            Box(
                Modifier.fillMaxSize().background(MaterialTheme.colorScheme.error).padding(horizontal = 24.dp),
                contentAlignment = Alignment.CenterEnd,
            ) {
                Icon(Icons.Rounded.Delete, contentDescription = stringResource(R.string.common_delete), tint = Color.White)
            }
        },
    ) {
        Row(
            Modifier
                .fillMaxWidth()
                .background(if (selected) palette.raised else palette.surface)
                .clickable(onClick = onOpen)
                .padding(horizontal = 20.dp, vertical = 14.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                conversation.title.ifBlank { stringResource(R.string.chat_new) },
                style = MaterialTheme.typography.bodyLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            conversation.updatedAt?.let {
                Text(relativeTime(it), style = MaterialTheme.typography.labelMedium, color = palette.secondary)
            }
        }
    }
}
