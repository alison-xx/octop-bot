package io.github.alisonxx.octopbot.ui.home

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.ui.common.accentOf
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.launch

/** Server mode: name a group and pick at least two Bots. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun NewGroupSheet(bots: List<BotProfile>, onCreate: suspend (String, List<BotProfile>) -> Boolean, onDismiss: () -> Unit) {
    val palette = LocalPalette.current
    val scope = rememberCoroutineScope()
    var name by rememberSaveable { mutableStateOf("") }
    var picked by rememberSaveable { mutableStateOf(listOf<String>()) }
    var saving by rememberSaveable { mutableStateOf(false) }
    val members = bots.filter { it.id in picked }
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = palette.surface,
        contentColor = palette.text,
    ) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().imePadding()) {
            Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.groups_new), style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                TextButton(
                    onClick = {
                        saving = true
                        scope.launch {
                            if (onCreate(name, members)) onDismiss()
                            saving = false
                        }
                    },
                    enabled = name.isNotBlank() && members.size >= 2 && !saving,
                ) { Text(stringResource(R.string.common_save), style = MaterialTheme.typography.titleSmall) }
            }
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                label = { Text(stringResource(R.string.groups_name)) },
                placeholder = { Text(stringResource(R.string.groups_name_placeholder)) },
                singleLine = true,
                shape = RoundedCornerShape(16.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    unfocusedContainerColor = palette.background,
                    focusedContainerColor = palette.background,
                    unfocusedBorderColor = palette.hairline,
                ),
                modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
            )
            Text(
                stringResource(R.string.groups_members),
                style = MaterialTheme.typography.labelLarge,
                color = palette.secondary,
                modifier = Modifier.padding(start = 20.dp, top = 8.dp, bottom = 4.dp),
            )
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 420.dp)) {
                items(bots, key = { it.id }) { bot ->
                    val selected = bot.id in picked
                    val ink = accentOf(bot.look)
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable { picked = if (selected) picked - bot.id else picked + bot.id }
                            .padding(horizontal = 20.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Start,
                    ) {
                        BotCharacter(bot.look, 34.dp, seed = bot.id)
                        Spacer(Modifier.width(12.dp))
                        Text(
                            bot.name,
                            style = MaterialTheme.typography.bodyLarge,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                        Box(
                            Modifier
                                .size(24.dp)
                                .clip(CircleShape)
                                .background(if (selected) ink else Color.Transparent)
                                .border(1.5.dp, if (selected) ink else palette.hairline, CircleShape),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (selected) Icon(Icons.Rounded.Check, contentDescription = null, tint = Color.White, modifier = Modifier.size(16.dp))
                        }
                    }
                }
            }
        }
    }
}
