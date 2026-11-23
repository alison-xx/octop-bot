package io.github.alisonxx.octopbot.ui.common

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.remember
import androidx.compose.ui.hapticfeedback.HapticFeedback
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.isSpecified
import io.github.alisonxx.octopbot.store.UserSettings

/** The Settings choices every screen reads, so a change applies everywhere at once. */
data class UiPrefs(
    /** Chat text size (0.9 / 1.0 / 1.15 × body). */
    val textScale: Float = 1f,
    val haptics: Boolean = true,
    val expandReasoning: Boolean = false,
)

val LocalUiPrefs = compositionLocalOf { UiPrefs() }

/** Provides [UiPrefs] from [settings]; with haptics off, the platform feedback is silenced too. */
@Composable
fun ProvideUiPrefs(settings: UserSettings, content: @Composable () -> Unit) {
    val prefs = UiPrefs(settings.textSize.scale, settings.haptics, settings.expandReasoning)
    val platform = LocalHapticFeedback.current
    val feedback = remember(platform, prefs.haptics) { if (prefs.haptics) platform else Silent }
    CompositionLocalProvider(LocalUiPrefs provides prefs, LocalHapticFeedback provides feedback, content = content)
}

private object Silent : HapticFeedback {
    override fun performHapticFeedback(hapticFeedbackType: HapticFeedbackType) = Unit
}

/**
 * Haptics that respect Settings → Haptics. Use this rather than [LocalHapticFeedback]: dialogs and sheets
 * get their own platform feedback, but this setting still reaches them.
 */
class Haptics(private val feedback: HapticFeedback, private val enabled: Boolean) {
    fun longPress() = perform(HapticFeedbackType.LongPress)
    /** Send, copy. */
    fun tap() = perform(HapticFeedbackType.Confirm)
    /** A reply finished. */
    fun done() = perform(HapticFeedbackType.GestureEnd)

    private fun perform(type: HapticFeedbackType) {
        if (enabled) feedback.performHapticFeedback(type)
    }
}

@Composable
fun rememberHaptics(): Haptics {
    val feedback = LocalHapticFeedback.current
    val enabled = LocalUiPrefs.current.haptics
    return remember(feedback, enabled) { Haptics(feedback, enabled) }
}

/** [style] at the chat text size. */
@Composable
fun chatText(style: TextStyle): TextStyle {
    val scale = LocalUiPrefs.current.textScale
    if (scale == 1f) return style
    return style.copy(
        fontSize = if (style.fontSize.isSpecified) style.fontSize * scale else style.fontSize,
        lineHeight = if (style.lineHeight.isSpecified) style.lineHeight * scale else style.lineHeight,
    )
}
