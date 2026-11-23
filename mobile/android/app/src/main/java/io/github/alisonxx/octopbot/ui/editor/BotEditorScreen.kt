package io.github.alisonxx.octopbot.ui.editor

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Delete
import androidx.compose.material.icons.rounded.Shuffle
import androidx.compose.material3.Icon
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlin.math.max
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.character.rememberCharacterLibrary
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.TopBarTitle
import io.github.alisonxx.octopbot.ui.common.accentOf
import io.github.alisonxx.octopbot.ui.common.rememberHaptics
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import kotlinx.coroutines.launch

/** New Bot (Lynxce mode) or edit an existing Bot's look — and name/persona for phone-local Bots. */
@Composable
fun BotEditorScreen(model: AppViewModel, botId: String?, onDone: () -> Unit) {
    val bots by model.bots.collectAsStateWithLifecycle()
    val original = botId?.let { id -> bots.firstOrNull { it.id == id } }
    if (botId != null && original == null) return
    val scope = rememberCoroutineScope()
    var saving by rememberSaveable { mutableStateOf(false) }
    BotEditor(
        original = original,
        saving = saving,
        onCancel = onDone,
        onSave = { name, persona, look ->
            saving = true
            scope.launch {
                if (model.saveBot(original, name, persona, look) != null) onDone()
                saving = false
            }
        },
        onDelete = { bot ->
            model.deleteBot(bot)
            onDone()
        },
    )
}

@Composable
fun BotEditor(
    original: BotProfile?,
    saving: Boolean,
    onCancel: () -> Unit,
    onSave: (name: String, persona: String, look: Look) -> Unit,
    onDelete: (BotProfile) -> Unit,
) {
    val library = rememberCharacterLibrary()
    val palette = LocalPalette.current
    val haptics = rememberHaptics()
    val editsText = original == null || original.isLocal
    var name by rememberSaveable { mutableStateOf(original?.name.orEmpty()) }
    var persona by rememberSaveable { mutableStateOf(original?.systemPrompt.orEmpty()) }
    var shape by rememberSaveable { mutableStateOf(original?.look?.shape ?: "gumdrop") }
    var color by rememberSaveable { mutableStateOf(original?.look?.color ?: "blue") }
    var confirmDelete by rememberSaveable { mutableStateOf(false) }
    // The octopus is Chief's; its ink is fixed.
    val look = Look(shape, if (shape == Look.OCTOPUS) Look.chief.color else color)
    val valid = !editsText || name.isNotBlank()
    // The octopus is Chief's mascot; other Bots pick from the DS Bot shapes.
    val shapeIds = if (original?.isChief == true) library.shapeIds else library.shapes.keys.toList()

    OctopTheme(accent = accentOf(look)) {
        Column(Modifier.fillMaxSize().imePadding()) {
            TopBar(
                leading = { BackButton(onCancel) },
                trailing = {
                    TextButton(onClick = { onSave(name, persona, look) }, enabled = valid && !saving) {
                        Text(stringResource(R.string.common_save), style = MaterialTheme.typography.titleSmall)
                    }
                },
            ) { TopBarTitle(stringResource(if (original == null) R.string.bot_new else R.string.bot_edit_title)) }
            Column(
                Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 20.dp)
                    .navigationBarsPadding(),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Column(Modifier.fillMaxWidth().padding(top = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                    BotCharacter(look, 132.dp, seed = original?.id ?: "new")
                    Spacer(Modifier.height(12.dp))
                    Row(
                        Modifier
                            .clip(CircleShape)
                            .background(palette.surface)
                            .clickable {
                                haptics.tap()
                                shape = (shapeIds - shape).randomOrNull() ?: shape
                                color = (library.inkIds - color).randomOrNull() ?: color
                            }
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Rounded.Shuffle, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.bot_shuffle), style = MaterialTheme.typography.labelLarge)
                    }
                }
                if (editsText) {
                    EditorField(name, { name = it }, stringResource(R.string.bot_name), stringResource(R.string.bot_name_placeholder))
                    EditorField(
                        persona,
                        { persona = it },
                        stringResource(R.string.bot_persona),
                        stringResource(R.string.bot_persona_placeholder),
                        singleLine = false,
                    )
                } else {
                    Text(original.name, style = MaterialTheme.typography.titleLarge, modifier = Modifier.align(Alignment.CenterHorizontally))
                }
                Section(stringResource(R.string.bot_shape))
                AdaptiveGrid(shapeIds, minCell = 52.dp, spacing = 8.dp) { id, cell ->
                    val choice = Look(id, if (id == Look.OCTOPUS) Look.chief.color else color)
                    val selected = id == shape
                    Box(
                        Modifier
                            .size(cell)
                            .clip(RoundedCornerShape(14.dp))
                            .background(if (selected) palette.raised else Color.Transparent)
                            .border(1.5.dp, if (selected) MaterialTheme.colorScheme.primary else palette.hairline, RoundedCornerShape(14.dp))
                            .clickable { shape = id }
                            .semantics {
                                contentDescription = library.shapes[id]?.label ?: "Octopus"
                                this.selected = selected
                            },
                        contentAlignment = Alignment.Center,
                    ) {
                        BotCharacter(choice, cell * 0.7f, seed = id)
                    }
                }
                if (shape != Look.OCTOPUS) {
                    Section(stringResource(R.string.bot_color))
                    AdaptiveGrid(library.inkIds, minCell = 38.dp, spacing = 8.dp) { ink, cell ->
                        val selected = ink == color
                        val fill = if (ink == "aurora" && library.aurora.isNotEmpty()) {
                            Brush.linearGradient(library.aurora.map { it.second })
                        } else {
                            androidx.compose.ui.graphics.SolidColor(library.ink(ink, isSystemInDarkTheme()))
                        }
                        Box(Modifier.size(cell), contentAlignment = Alignment.Center) {
                            Box(
                                Modifier
                                    .size(36.dp)
                                    .border(2.dp, if (selected) palette.text else Color.Transparent, CircleShape)
                                    .padding(4.dp)
                                    .clip(CircleShape)
                                    .background(fill)
                                    .border(1.dp, palette.hairline, CircleShape)
                                    .clickable { color = ink }
                                    .semantics {
                                        contentDescription = ink
                                        this.selected = selected
                                    },
                            )
                        }
                    }
                }
                if (original?.isLocal == true) {
                    Spacer(Modifier.height(8.dp))
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(16.dp))
                            .background(palette.surface)
                            .clickable { confirmDelete = true }
                            .padding(vertical = 15.dp),
                        horizontalArrangement = Arrangement.Center,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Rounded.Delete, contentDescription = null, tint = MaterialTheme.colorScheme.error, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.bot_delete), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.titleSmall)
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
        if (confirmDelete && original != null) {
            AlertDialog(
                onDismissRequest = { confirmDelete = false },
                text = { Text(stringResource(R.string.bot_delete_confirm, original.name)) },
                confirmButton = {
                    TextButton(onClick = { confirmDelete = false; onDelete(original) }) {
                        Text(stringResource(R.string.common_delete), color = MaterialTheme.colorScheme.error)
                    }
                },
                dismissButton = {
                    TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.common_cancel)) }
                },
            )
        }
    }
}

/** A grid that fills the width with as many columns of at least [minCell] as fit. */
@Composable
private fun <T> AdaptiveGrid(items: List<T>, minCell: Dp, spacing: Dp, cell: @Composable (T, Dp) -> Unit) {
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val columns = max(1, ((maxWidth + spacing) / (minCell + spacing)).toInt())
        val size = (maxWidth - spacing * (columns - 1)) / columns
        Column(verticalArrangement = Arrangement.spacedBy(spacing)) {
            for (row in items.chunked(columns)) {
                Row(horizontalArrangement = Arrangement.spacedBy(spacing)) {
                    for (item in row) cell(item, size)
                }
            }
        }
    }
}

@Composable
private fun Section(title: String) {
    Text(title, style = MaterialTheme.typography.titleSmall, color = LocalPalette.current.secondary, modifier = Modifier.padding(top = 6.dp))
}

@Composable
private fun EditorField(value: String, onChange: (String) -> Unit, label: String, placeholder: String, singleLine: Boolean = true) {
    val palette = LocalPalette.current
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label) },
        placeholder = { Text(placeholder) },
        singleLine = singleLine,
        minLines = if (singleLine) 1 else 3,
        maxLines = if (singleLine) 1 else 8,
        shape = RoundedCornerShape(16.dp),
        colors = OutlinedTextFieldDefaults.colors(
            unfocusedContainerColor = palette.surface,
            focusedContainerColor = palette.surface,
            unfocusedBorderColor = palette.hairline,
        ),
        modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
    )
}

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 900)
@Composable
private fun EditorPreview() {
    OctopTheme(dark = true) {
        BotEditor(
            original = BotProfile("bot-1", "Poet", "Your own Bot", Look("star", "aurora"), systemPrompt = "You write short poems.", isLocal = true),
            saving = false,
            onCancel = {},
            onSave = { _, _, _ -> },
            onDelete = {},
        )
    }
}
