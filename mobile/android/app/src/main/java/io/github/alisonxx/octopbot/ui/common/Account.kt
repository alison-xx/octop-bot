package io.github.alisonxx.octopbot.ui.common

import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import androidx.browser.customtabs.CustomTabsIntent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.sp
import coil3.compose.SubcomposeAsyncImage
import java.text.BreakIterator
import androidx.compose.foundation.layout.size
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.BalanceState
import io.github.alisonxx.octopbot.net.ChatBackend
import io.github.alisonxx.octopbot.net.DeviceBackend
import io.github.alisonxx.octopbot.net.LynxceBackend
import io.github.alisonxx.octopbot.net.LynxceProtocol
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.ui.theme.LocalPalette

internal fun accountInitial(name: String): String {
    val trimmed = name.trim()
    if (trimmed.isEmpty()) return ""
    val boundary = BreakIterator.getCharacterInstance().apply { setText(trimmed) }.next()
    return trimmed.substring(0, boundary)
}

@Composable
fun AccountAvatar(name: String, url: String?, size: Dp) {
    val initial = @Composable {
        Box(Modifier.size(size).background(Color(0xFFCF3753)), contentAlignment = Alignment.Center) {
            Text(accountInitial(name), color = Color.White, fontSize = (size.value * 0.42f).sp)
        }
    }
    Box(Modifier.size(size).clip(CircleShape)) {
        if (url == null) initial() else SubcomposeAsyncImage(
            model = url,
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = Modifier.size(size),
            loading = { initial() },
            error = { initial() },
        )
    }
}

/** Balance text under 100 credits. */
val LowBalanceColor = Color(0xFFFF9F0A)

/** The person's name, or "Lynxce user" when the account has no display name. Never a username or id. */
@Composable
fun accountName(backend: ChatBackend): String = backend.accountName ?: stringResource(R.string.account_generic_name)

/** "Lynxce cloud", "Lynxce account" (direct), "Not signed in", or a self-hosted server's host. */
@Composable
fun modeLabel(backend: ChatBackend): String = when {
    backend is LynxceBackend -> stringResource(R.string.mode_lynxce)
    backend is DeviceBackend -> stringResource(R.string.mode_device)
    backend is ServerBackend && backend.isCloud -> stringResource(R.string.mode_cloud)
    else -> backend.connectionLabel
}

/** "12,800" — see [LynxceProtocol.formatCredits]. */
fun credits(value: Double): String = LynxceProtocol.formatCredits(value)

/**
 * A balance in one line: a small spinner while loading, "—" when it failed, else [format] of the number
 * (in the warning colour below 100).
 */
@Composable
fun BalanceText(
    state: BalanceState,
    style: TextStyle,
    color: Color = LocalPalette.current.text,
    format: @Composable (String) -> String = { stringResource(R.string.credits_amount, it) },
    modifier: Modifier = Modifier,
) {
    when (state) {
        BalanceState.Loading -> CircularProgressIndicator(
            modifier.size(with(LocalDensity.current) { style.fontSize.toDp() }),
            strokeWidth = 1.5.dp,
            color = LocalPalette.current.secondary,
        )
        BalanceState.Failed -> Text("—", style = style, color = LocalPalette.current.secondary, modifier = modifier)
        is BalanceState.Value -> Text(
            format(credits(state.credits)),
            style = style,
            color = if (state.low) LowBalanceColor else color,
            maxLines = 1,
            modifier = modifier,
        )
    }
}

/** Lynxce's recharge page in a Custom Tab, so coming back lands in the app; a plain browser if there is none. */
fun openCheckout(context: Context, url: String) {
    val uri = url.toUri()
    try {
        CustomTabsIntent.Builder().setShowTitle(true).build().launchUrl(context, uri)
    } catch (_: ActivityNotFoundException) {
        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, uri)) }
    }
}
