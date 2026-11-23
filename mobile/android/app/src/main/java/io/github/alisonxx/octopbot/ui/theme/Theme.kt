package io.github.alisonxx.octopbot.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp

/** The README palette: dark-first, Grok-like. */
@Immutable
data class Palette(
    val background: Color,
    val surface: Color,
    val raised: Color,
    val hairline: Color,
    val text: Color,
    val secondary: Color,
    val accent: Color,
    val onAccent: Color,
)

private val DarkBase = Palette(
    background = Color(0xFF000000),
    surface = Color(0xFF141416),
    raised = Color(0xFF1E1E22),
    hairline = Color(0xFF2A2A30),
    text = Color(0xFFF4F4F5),
    secondary = Color(0xFF9A9AA3),
    accent = Color(0xFFEC2F6B),
    onAccent = Color.White,
)

private val LightBase = Palette(
    background = Color(0xFFFFFFFF),
    surface = Color(0xFFF4F4F5),
    raised = Color(0xFFECECEF),
    hairline = Color(0xFFE4E4E7),
    text = Color(0xFF111113),
    secondary = Color(0xFF6B6B73),
    accent = Color(0xFFEC2F6B),
    onAccent = Color.White,
)

val LocalPalette = staticCompositionLocalOf { DarkBase }

/** Chief's rose; screens without a current Bot use it. */
val DefaultAccent = Color(0xFFEC2F6B)

private val AppTypography = Typography().run {
    copy(
        headlineLarge = headlineLarge.copy(fontWeight = FontWeight.Bold, fontSize = 32.sp),
        titleLarge = titleLarge.copy(fontWeight = FontWeight.SemiBold),
        bodyLarge = bodyLarge.copy(fontSize = 16.sp, lineHeight = 24.sp),
    )
}

@Composable
fun OctopTheme(accent: Color = DefaultAccent, dark: Boolean = isSystemInDarkTheme(), content: @Composable () -> Unit) {
    val onAccent = if (accent.luminance() > 0.55f) Color(0xFF111113) else Color.White
    val palette = (if (dark) DarkBase else LightBase).copy(accent = accent, onAccent = onAccent)
    val scheme = if (dark) {
        darkColorScheme(
            primary = accent,
            onPrimary = onAccent,
            background = palette.background,
            onBackground = palette.text,
            surface = palette.background,
            onSurface = palette.text,
            surfaceVariant = palette.surface,
            onSurfaceVariant = palette.secondary,
            surfaceContainerLowest = palette.background,
            surfaceContainerLow = palette.surface,
            surfaceContainer = palette.surface,
            surfaceContainerHigh = palette.raised,
            surfaceContainerHighest = palette.raised,
            outline = palette.hairline,
            outlineVariant = palette.hairline,
            secondaryContainer = palette.raised,
            onSecondaryContainer = palette.text,
        )
    } else {
        lightColorScheme(
            primary = accent,
            onPrimary = onAccent,
            background = palette.background,
            onBackground = palette.text,
            surface = palette.background,
            onSurface = palette.text,
            surfaceVariant = palette.surface,
            onSurfaceVariant = palette.secondary,
            surfaceContainerLowest = palette.background,
            surfaceContainerLow = palette.surface,
            surfaceContainer = palette.surface,
            surfaceContainerHigh = palette.raised,
            surfaceContainerHighest = palette.raised,
            outline = palette.hairline,
            outlineVariant = palette.hairline,
            secondaryContainer = palette.raised,
            onSecondaryContainer = palette.text,
        )
    }
    CompositionLocalProvider(LocalPalette provides palette) {
        MaterialTheme(colorScheme = scheme, typography = AppTypography) {
            // No Surface at the root, so text and icons take the palette's text color explicitly.
            CompositionLocalProvider(LocalContentColor provides palette.text, content = content)
        }
    }
}
