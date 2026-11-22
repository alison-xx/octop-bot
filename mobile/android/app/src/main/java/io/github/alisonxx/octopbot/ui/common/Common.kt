package io.github.alisonxx.octopbot.ui.common

import android.text.format.DateUtils
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowBack
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.character.rememberCharacterLibrary
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.ui.theme.DefaultAccent
import io.github.alisonxx.octopbot.ui.theme.LocalPalette

/** "5 min ago", "Yesterday", in the system language. */
fun relativeTime(millis: Long, now: Long = System.currentTimeMillis()): String =
    DateUtils.getRelativeTimeSpanString(millis, now, DateUtils.MINUTE_IN_MILLIS, DateUtils.FORMAT_ABBREV_RELATIVE).toString()

/** The accent for a Bot: its ink; the octopus uses Chief's rose. */
@Composable
fun accentOf(look: Look?): Color {
    if (look == null || look.isOctopus) return DefaultAccent
    return rememberCharacterLibrary().ink(look.color)
}

@Composable
fun BackButton(onClick: () -> Unit) {
    IconButton(onClick = onClick) {
        Icon(Icons.AutoMirrored.Rounded.ArrowBack, contentDescription = stringResource(R.string.common_back))
    }
}

/** A plain top bar: leading action · centered title · trailing actions. */
@Composable
fun TopBar(
    modifier: Modifier = Modifier,
    /** Room kept clear on both sides of the centered title for the actions. */
    titleInset: Dp = 104.dp,
    leading: @Composable () -> Unit = {},
    trailing: @Composable RowScope.() -> Unit = {},
    title: @Composable () -> Unit,
) {
    Box(
        modifier
            .fillMaxWidth()
            .statusBarsPadding()
            .height(56.dp)
            .padding(horizontal = 4.dp),
    ) {
        Box(Modifier.align(Alignment.CenterStart)) { leading() }
        Box(Modifier.align(Alignment.Center).padding(horizontal = titleInset)) { title() }
        Row(
            Modifier.align(Alignment.CenterEnd),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
            content = trailing,
        )
    }
}

@Composable
fun TopBarTitle(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.titleMedium,
        textAlign = TextAlign.Center,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

/** Fades the content scrolling under a floating bottom bar into the background. */
@Composable
fun BottomFade(height: Dp, modifier: Modifier = Modifier) {
    val background = LocalPalette.current.background
    Box(
        modifier
            .fillMaxWidth()
            .height(height)
            .background(Brush.verticalGradient(0f to background.copy(alpha = 0f), 0.35f to background, 1f to background)),
    )
}
