package io.github.alisonxx.octopbot.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.ArrowUpward
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.Mic
import androidx.compose.material.icons.rounded.PhotoCamera
import androidx.compose.material.icons.rounded.PhotoLibrary
import androidx.compose.material.icons.rounded.Stop
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
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.ImageAttachment
import io.github.alisonxx.octopbot.ui.common.chatText
import io.github.alisonxx.octopbot.ui.theme.LocalPalette

/** The floating pill: `+` · multiline field · mic / send / stop, with picked photos above the field. */
@Composable
fun Composer(
    text: String,
    onTextChange: (String) -> Unit,
    images: List<ImageAttachment>,
    onRemoveImage: (ImageAttachment) -> Unit,
    streaming: Boolean,
    dictating: Boolean,
    placeholder: String,
    onPickPhotos: () -> Unit,
    onTakePhoto: () -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
    onDictate: () -> Unit,
    modifier: Modifier = Modifier,
    allowPhotos: Boolean = true,
    enabled: Boolean = true,
) {
    val palette = LocalPalette.current
    var attachMenu by remember { mutableStateOf(false) }
    // Text set from outside (a suggestion, a dictation, an @mention) puts the caret at the end.
    var field by remember { mutableStateOf(TextFieldValue(text, TextRange(text.length))) }
    if (field.text != text) field = TextFieldValue(text, TextRange(text.length))
    Column(
        modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(28.dp))
            .background(palette.raised)
            .border(1.dp, palette.hairline, RoundedCornerShape(28.dp))
            .padding(6.dp),
    ) {
        if (images.isNotEmpty()) {
            LazyRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.padding(start = 8.dp, top = 6.dp, bottom = 4.dp),
            ) {
                items(images, key = { it.uri }) { image ->
                    Box {
                        AsyncImage(
                            model = image.uri,
                            contentDescription = null,
                            contentScale = ContentScale.Crop,
                            modifier = Modifier.size(64.dp).clip(RoundedCornerShape(14.dp)),
                        )
                        Box(
                            Modifier
                                .align(Alignment.TopEnd)
                                .padding(3.dp)
                                .size(22.dp)
                                .clip(CircleShape)
                                .background(palette.background.copy(alpha = 0.7f)),
                            contentAlignment = Alignment.Center,
                        ) {
                            IconButton(onClick = { onRemoveImage(image) }, modifier = Modifier.size(22.dp)) {
                                Icon(
                                    Icons.Rounded.Close,
                                    contentDescription = stringResource(R.string.chat_remove_photo),
                                    tint = palette.text,
                                    modifier = Modifier.size(14.dp),
                                )
                            }
                        }
                    }
                }
            }
        }
        Row(verticalAlignment = Alignment.Bottom) {
            if (allowPhotos) {
                Box {
                    IconButton(onClick = { attachMenu = true }, enabled = enabled) {
                        Icon(Icons.Rounded.Add, contentDescription = stringResource(R.string.chat_attach))
                    }
                    DropdownMenu(expanded = attachMenu, onDismissRequest = { attachMenu = false }) {
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.chat_photo_library)) },
                            leadingIcon = { Icon(Icons.Rounded.PhotoLibrary, null) },
                            onClick = { attachMenu = false; onPickPhotos() },
                        )
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.chat_take_photo)) },
                            leadingIcon = { Icon(Icons.Rounded.PhotoCamera, null) },
                            onClick = { attachMenu = false; onTakePhoto() },
                        )
                    }
                }
            }
            Box(
                Modifier
                    .weight(1f)
                    .heightIn(min = 48.dp)
                    .padding(start = if (allowPhotos) 0.dp else 14.dp, end = 4.dp),
                contentAlignment = Alignment.CenterStart,
            ) {
                if (text.isEmpty()) {
                    Text(
                        if (dictating) stringResource(R.string.chat_listening) else placeholder,
                        style = chatText(MaterialTheme.typography.bodyLarge),
                        color = palette.secondary,
                    )
                }
                BasicTextField(
                    value = field,
                    enabled = enabled,
                    onValueChange = {
                        field = it
                        if (it.text != text) onTextChange(it.text)
                    },
                    textStyle = chatText(MaterialTheme.typography.bodyLarge).copy(color = palette.text),
                    cursorBrush = SolidColor(MaterialTheme.colorScheme.primary),
                    maxLines = 6,
                    keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                )
            }
            val hasContent = text.isNotBlank() || images.isNotEmpty()
            if (enabled && streaming && hasContent && !dictating) {
                RoundAction(Icons.Rounded.Stop, stringResource(R.string.chat_stop), filled = false, onClick = onStop)
            }
            when {
                !enabled -> RoundAction(Icons.Rounded.Mic, stringResource(R.string.chat_dictate), filled = false, enabled = false, onClick = {})
                hasContent && !dictating -> RoundAction(Icons.Rounded.ArrowUpward, stringResource(R.string.chat_send), filled = true, onClick = onSend)
                streaming -> RoundAction(Icons.Rounded.Stop, stringResource(R.string.chat_stop), filled = true, onClick = onStop)
                else -> RoundAction(Icons.Rounded.Mic, stringResource(R.string.chat_dictate), filled = dictating, onClick = onDictate)
            }
        }
    }
}

@Composable
private fun RoundAction(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, filled: Boolean, enabled: Boolean = true, onClick: () -> Unit) {
    val palette = LocalPalette.current
    IconButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier
            .padding(2.dp)
            .size(44.dp)
            .clip(CircleShape)
            .background(if (filled) palette.text else palette.raised),
    ) {
        Icon(icon, contentDescription = label, tint = if (filled) palette.background else palette.text)
    }
}
