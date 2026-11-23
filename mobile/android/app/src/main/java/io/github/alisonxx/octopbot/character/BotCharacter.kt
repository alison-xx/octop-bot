package io.github.alisonxx.octopbot.character

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.StartOffset
import androidx.compose.animation.core.animateFloat
import androidx.compose.runtime.State
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.TransformOrigin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.withTransform
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.Look

private val EyeWhite = Color(0xFFFFFCF5)
private val Pupil = Color(0xFF2D2833)

private object CharacterCache {
    @Volatile var library: CharacterLibrary? = null
}

/** `characters.json`, parsed once per process. */
@Composable
fun rememberCharacterLibrary(): CharacterLibrary {
    val context = LocalContext.current
    return remember {
        CharacterCache.library ?: CharacterLibrary.load(context.assets).also { CharacterCache.library = it }
    }
}

private class ShapePaths(shape: CharacterShape) {
    val body: Path = shape.body.toComposePath()
    val shade: Path = shape.shade.toComposePath()
    val light: Path? = shape.light?.toComposePath()
    val paints: List<Triple<Path, Color, Float>> = shape.paints.map { Triple(it.contours.toComposePath(), it.color, it.opacity) }
    val eyes = shape.eyes
    val flat = shape.flat
}

/**
 * A Bot's animated character: a DS Bot vector shape in its ink, or the Chief octopus bitmap with the same
 * transforms. [seed] (the Bot id) offsets the animation phase.
 */
@Composable
fun BotCharacter(
    look: Look,
    size: Dp,
    modifier: Modifier = Modifier,
    motion: BotMotion = BotMotion.Idle,
    seed: String = look.shape + look.color,
) {
    val phase = remember(seed) { CharacterPose.phaseMillis(seed) }
    val period = CharacterPose.periodMillis(motion, phase)
    val transition = rememberInfiniteTransition(label = "character")
    val progress = transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(period, easing = LinearEasing), initialStartOffset = StartOffset(phase % period)),
        label = "motion",
    )
    val blink = transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            tween(CharacterPose.BLINK_PERIOD_MS, easing = LinearEasing),
            initialStartOffset = StartOffset(phase),
        ),
        label = "blink",
    )
    CharacterFrame(look, size, motion, progress, blink, modifier)
}

@Composable
private fun CharacterFrame(
    look: Look,
    size: Dp,
    motion: BotMotion,
    progress: State<Float>,
    blink: State<Float>,
    modifier: Modifier,
) {
    // Animated values are read only in the layer/draw lambdas, so frames don't recompose.
    fun pose() = CharacterPose.at(motion, progress.value, blink.value)
    val layer = Modifier.graphicsLayer {
        val pose = pose()
        transformOrigin = TransformOrigin(0.5f, 0.84f)
        scaleX = pose.scaleX
        scaleY = pose.scaleY
        rotationZ = pose.rotation
        translationX = pose.offsetX * this.size.width
        translationY = pose.offsetY * this.size.height
    }
    Box(modifier.size(size)) {
        if (look.isOctopus) {
            Image(
                painter = painterResource(R.drawable.octop_mascot),
                contentDescription = null,
                contentScale = ContentScale.Fit,
                modifier = Modifier.fillMaxSize().then(layer),
            )
        } else {
            val library = rememberCharacterLibrary()
            val shape = library.shape(look.shape) ?: return@Box
            val paths = remember(shape) { ShapePaths(shape) }
            // Every ink uses its second color in dark mode (the soft black turns white).
            val dark = isSystemInDarkTheme()
            val fill: Brush = remember(look.color, library, dark) {
                if (look.color == "aurora" && library.aurora.isNotEmpty()) {
                    Brush.linearGradient(
                        colorStops = library.aurora.toTypedArray(),
                        start = Offset(18f, 10f),
                        end = Offset(78f, 92f),
                    )
                } else {
                    androidx.compose.ui.graphics.SolidColor(library.ink(look.color, dark))
                }
            }
            val pupils = size >= 24.dp && !shape.flat
            Canvas(Modifier.fillMaxSize().then(layer)) {
                val pose = pose()
                drawCharacter(paths, fill, pupils, pose.blink, pose.look)
            }
        }
    }
}

private fun DrawScope.drawCharacter(paths: ShapePaths, fill: Brush, pupils: Boolean, blink: Float, look: Float) {
    val unit = size.minDimension / 100f
    scale(unit, unit, pivot = Offset.Zero) {
        drawPath(paths.body, fill)
        if (!paths.flat) {
            for ((path, color, opacity) in paths.paints) drawPath(path, color, alpha = opacity)
            drawPath(paths.shade, Color.Black, alpha = 0.07f)
            paths.light?.let { drawPath(it, Color.White, alpha = 0.36f) }
        }
        for (eye in paths.eyes) {
            withTransform({
                translate(eye.x, eye.y)
                rotate(eye.angle, pivot = Offset.Zero)
                scale(1f, blink, pivot = Offset.Zero)
            }) {
                drawRoundRect(
                    color = if (paths.flat) Color.White else EyeWhite,
                    topLeft = Offset(-eye.w / 2, -eye.h / 2),
                    size = Size(eye.w, eye.h),
                    cornerRadius = CornerRadius(eye.w / 2),
                )
                if (pupils) {
                    val cx = eye.w * (0.07f + look)
                    val cy = eye.h * 0.05f
                    drawOval(
                        color = Pupil,
                        topLeft = Offset(cx - eye.w * 0.28f, cy - eye.h * 0.22f),
                        size = Size(eye.w * 0.56f, eye.h * 0.44f),
                    )
                }
            }
        }
    }
}

/** Several members' characters in one square, like the dashboard's GroupCharacter. */
@Composable
fun GroupCharacter(members: List<Pair<String, Look>>, size: Dp, modifier: Modifier = Modifier) {
    val shown = members.take(4)
    val side = when (shown.size) {
        0, 1 -> size
        2 -> size * 2 / 3
        3 -> size * 5 / 9
        else -> size / 2
    }
    val rest = size - side
    val seats = when (shown.size) {
        0, 1 -> listOf(0.dp to 0.dp)
        2 -> listOf(0.dp to 0.dp, rest to rest)
        3 -> listOf(rest / 2 to 0.dp, 0.dp to rest, rest to rest)
        else -> listOf(0.dp to 0.dp, rest to 0.dp, 0.dp to rest, rest to rest)
    }
    Box(modifier.size(size)) {
        shown.forEachIndexed { index, (id, look) ->
            val (x, y) = seats[index]
            BotCharacter(look, side, Modifier.offset(x, y), seed = id)
        }
    }
}
