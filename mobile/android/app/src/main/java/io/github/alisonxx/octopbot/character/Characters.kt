package io.github.alisonxx.octopbot.character

import android.content.res.AssetManager
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathFillType
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * One character in its 100×100 box: a DS Bot shape (geometry and inks: Apache-2.0, see
 * dashboard/public/licenses/ds-bot.txt) or a [flat] soft shape (body plus white capsule eyes, nothing else).
 */
class CharacterShape(
    val id: String,
    val label: String,
    val body: List<SvgPath.Segment>,
    val shade: List<SvgPath.Segment>,
    val light: List<SvgPath.Segment>?,
    val paints: List<Paint>,
    val eyes: List<Eye>,
    val flat: Boolean = false,
) {
    class Paint(val contours: List<SvgPath.Segment>, val color: Color, val opacity: Float)
    class Eye(val x: Float, val y: Float, val w: Float, val h: Float, val angle: Float)
}

/**
 * `characters.json` merged with `soft-characters.json` like the dashboard: soft shapes first, then DS shapes;
 * soft inks override DS inks of the same name and come first. Inks are `[light, dark]` pairs.
 */
class CharacterLibrary(
    val shapes: Map<String, CharacterShape>,
    val inks: Map<String, Pair<Color, Color>>,
    val aurora: List<Pair<Float, Color>>,
) {
    /** Every look a Bot can wear: the octopus first, then the soft and DS shapes. */
    val shapeIds: List<String> get() = listOf("octop") + shapes.keys
    val inkIds: List<String> get() = inks.keys.toList()

    fun shape(id: String): CharacterShape? = shapes[id] ?: shapes["gumdrop"]

    /** The Bot's ink: `inks[color]` (its second color in dark mode), a literal `#RRGGBB`, or blue. */
    fun ink(color: String, dark: Boolean = false): Color {
        val pair = inks[color] ?: parseHex(color)?.let { it to it } ?: inks["blue"] ?: (Color(0xFF2563EB) to Color(0xFF3B82F6))
        return if (dark) pair.second else pair.first
    }

    companion object {
        fun load(assets: AssetManager): CharacterLibrary {
            fun read(name: String) = assets.open(name).bufferedReader().use { it.readText() }
            return parse(read("characters.json"), runCatching { read("soft-characters.json") }.getOrNull())
        }

        /** [ds] is `characters.json`; [soft] is `soft-characters.json`, merged in front of it. */
        fun parse(ds: String, soft: String? = null): CharacterLibrary {
            val base = parseOne(ds)
            val extra = soft?.let(::parseOne) ?: return base
            val shapes = LinkedHashMap(extra.shapes).apply { base.shapes.forEach { (id, shape) -> putIfAbsent(id, shape) } }
            val inks = LinkedHashMap(extra.inks).apply { base.inks.forEach { (id, ink) -> putIfAbsent(id, ink) } }
            return CharacterLibrary(shapes, inks, base.aurora)
        }

        private fun parseOne(text: String): CharacterLibrary {
            val root = Json.parseToJsonElement(text).jsonObject
            val shapes = linkedMapOf<String, CharacterShape>()
            for ((id, element) in root["shapes"]?.jsonObject.orEmpty()) {
                val value = element.jsonObject
                val body = value.string("body") ?: continue
                val flat = (value["flat"] as? JsonPrimitive)?.booleanOrNull == true
                val shade = value.string("shade") ?: if (flat) "" else continue
                shapes[id] = CharacterShape(
                    id = id,
                    label = value.string("label") ?: id,
                    flat = flat,
                    body = SvgPath.parse(body),
                    shade = if (flat) emptyList() else SvgPath.parse(shade),
                    light = value.string("light")?.let(SvgPath::parse),
                    paints = (value["paints"] as? JsonArray).orEmpty().mapNotNull { paint ->
                        val parts = paint.jsonArray
                        val d = parts.getOrNull(0)?.jsonPrimitive?.content ?: return@mapNotNull null
                        val color = parts.getOrNull(1)?.jsonPrimitive?.content?.let(::parseHex) ?: return@mapNotNull null
                        val opacity = parts.getOrNull(2)?.jsonPrimitive?.doubleOrNull?.toFloat() ?: 1f
                        CharacterShape.Paint(SvgPath.parse(d), color, opacity)
                    },
                    eyes = (value["eyes"] as? JsonArray).orEmpty().mapNotNull { eye ->
                        val n = eye.jsonArray.mapNotNull { it.jsonPrimitive.doubleOrNull?.toFloat() }
                        if (n.size < 5) null else CharacterShape.Eye(n[0], n[1], n[2], n[3], n[4])
                    },
                )
            }
            val inks = linkedMapOf<String, Pair<Color, Color>>()
            for ((id, pair) in root["inks"]?.jsonObject.orEmpty()) {
                val colors = pair.jsonArray.mapNotNull { it.jsonPrimitive.content.let(::parseHex) }
                if (colors.size == 2) inks[id] = colors[0] to colors[1]
            }
            val aurora = (root["gradients"]?.jsonObject?.get("aurora") as? JsonArray).orEmpty().mapNotNull { stop ->
                val parts = stop.jsonArray
                val offset = (parts.getOrNull(0) as? JsonPrimitive)?.doubleOrNull?.toFloat() ?: return@mapNotNull null
                val color = parts.getOrNull(1)?.jsonPrimitive?.content?.let(::parseHex) ?: return@mapNotNull null
                offset to color
            }
            return CharacterLibrary(shapes, inks, aurora)
        }

        fun parseHex(text: String): Color? {
            if (!Regex("^#[0-9a-fA-F]{6}$").matches(text)) return null
            return Color(0xFF000000 or text.substring(1).toLong(16))
        }

        private fun JsonObject.string(key: String) = (this[key] as? JsonPrimitive)?.takeIf { it.isString }?.content
    }
}

/** Segments → an even-odd Compose path in the 100×100 box. */
fun List<SvgPath.Segment>.toComposePath(): Path = Path().apply {
    fillType = PathFillType.EvenOdd
    for (segment in this@toComposePath) when (segment) {
        is SvgPath.Segment.MoveTo -> moveTo(segment.x, segment.y)
        is SvgPath.Segment.LineTo -> lineTo(segment.x, segment.y)
        is SvgPath.Segment.QuadTo -> quadraticTo(segment.x1, segment.y1, segment.x, segment.y)
        is SvgPath.Segment.CubicTo -> cubicTo(segment.x1, segment.y1, segment.x2, segment.y2, segment.x, segment.y)
        SvgPath.Segment.Close -> close()
    }
}
