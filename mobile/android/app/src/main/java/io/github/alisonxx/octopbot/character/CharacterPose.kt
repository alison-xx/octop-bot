package io.github.alisonxx.octopbot.character

import io.github.alisonxx.octopbot.model.BotMotion
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

/**
 * The character's transform at one moment, mirroring the dashboard's CSS keyframes. Offsets are fractions
 * of the character size; transforms pivot at 50 % / 84 %.
 */
data class CharacterPose(
    val scaleX: Float = 1f,
    val scaleY: Float = 1f,
    val rotation: Float = 0f,
    val offsetX: Float = 0f,
    val offsetY: Float = 0f,
    /** Eye openness, 1 = open. */
    val blink: Float = 1f,
    /** Pupil shift as a fraction of eye width. */
    val look: Float = 0f,
) {
    companion object {
        const val BLINK_PERIOD_MS = 5800
        private const val BLINK_AT = 0.67f
        /** ~60 ms either side of fully closed. */
        private const val BLINK_HALF = 0.0104f

        /** A stable phase so a row of Bots doesn't move in lockstep. */
        fun phaseMillis(seed: String): Int {
            var hash = 0u
            for (c in seed) hash = hash * 31u + c.code.toUInt()
            return (hash % 5039u).toInt()
        }

        fun periodMillis(motion: BotMotion, phase: Int): Int = when (motion) {
            BotMotion.Idle -> 3800 + phase % 1100
            BotMotion.Working -> 1050
            BotMotion.Thinking -> 2800
            BotMotion.Searching -> 2200
            BotMotion.Waiting -> 3800
        }

        /** [t] is progress through the motion's period, [blinkT] through the blink period, both in 0..1. */
        fun at(motion: BotMotion, t: Float, blinkT: Float): CharacterPose {
            val wave = ((1 - cos(2 * PI * t)) / 2).toFloat()
            val blink = abs(blinkT - BLINK_AT).let { if (it < BLINK_HALF) 0.12f + 0.88f * it / BLINK_HALF else 1f }
            return when (motion) {
                BotMotion.Idle -> CharacterPose(1 + 0.012f * wave, 1 + 0.027f * wave, offsetY = -0.02f * wave, blink = blink)
                BotMotion.Working -> CharacterPose(1 - 0.01f * wave, 1 + 0.025f * wave, offsetY = -0.04f * wave, blink = blink)
                BotMotion.Thinking -> {
                    val lean = keyframes(t, 0f to 0f, 0.42f to 1f, 0.6f to 1f, 1f to 0f)
                    CharacterPose(rotation = -4f * lean, offsetY = -0.01f * lean, blink = blink)
                }
                BotMotion.Searching -> {
                    val swing = sin(2 * PI * t).toFloat()
                    CharacterPose(offsetX = 0.03f * swing, rotation = 3f * swing, look = 0.14f * swing, blink = blink)
                }
                BotMotion.Waiting -> {
                    val nod = keyframes(t, 0f to 0f, 0.14f to 1f, 0.32f to 1f, 0.44f to 0f, 1f to 0f)
                    CharacterPose(scaleY = 1 - 0.024f * nod, rotation = -3f * nod, offsetY = 0.02f * nod, blink = blink)
                }
            }
        }

        /** Ease-in-out between (time, value) frames, like CSS keyframes with `ease-in-out`. */
        private fun keyframes(t: Float, vararg frames: Pair<Float, Float>): Float {
            for (i in 1 until frames.size) {
                val (t0, v0) = frames[i - 1]
                val (t1, v1) = frames[i]
                if (t <= t1) {
                    val x = if (t1 > t0) ((t - t0) / (t1 - t0)).coerceIn(0f, 1f) else 1f
                    val eased = x * x * (3 - 2 * x)
                    return v0 + (v1 - v0) * eased
                }
            }
            return frames.last().second
        }
    }
}
