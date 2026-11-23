package io.github.alisonxx.octopbot.character

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

/**
 * SVG path data → absolute segments, with no Android dependency (unit-testable): every command
 * (M L H V C S Q T A Z, absolute and relative), compact numbers (`-.4`, `1.5-.4`, `1e-3`), implicit
 * repeated commands, and arc flags without separators (`a5 5 0 105 5`). Arcs become cubic Béziers.
 */
object SvgPath {
    sealed interface Segment {
        data class MoveTo(val x: Float, val y: Float) : Segment
        data class LineTo(val x: Float, val y: Float) : Segment
        data class QuadTo(val x1: Float, val y1: Float, val x: Float, val y: Float) : Segment
        data class CubicTo(val x1: Float, val y1: Float, val x2: Float, val y2: Float, val x: Float, val y: Float) : Segment
        data object Close : Segment
    }

    data class Bounds(val minX: Float, val minY: Float, val maxX: Float, val maxY: Float)

    fun parse(data: String): List<Segment> {
        val out = mutableListOf<Segment>()
        val scanner = Scanner(data)
        var command = 'M'
        var x = 0f
        var y = 0f
        var startX = 0f
        var startY = 0f
        // Control points of the previous C/S (for S) or Q/T (for T) command.
        var lastCubic: Pair<Float, Float>? = null
        var lastQuad: Pair<Float, Float>? = null

        while (true) {
            val next = scanner.peek() ?: break
            if (next.isLetter()) {
                command = next
                scanner.skip()
            } else if (command == 'Z' || command == 'z') {
                throw IllegalArgumentException("Number after 'z' at ${scanner.index}")
            }
            val relative = command.isLowerCase()
            fun px(value: Float) = if (relative) x + value else value
            fun py(value: Float) = if (relative) y + value else value
            var cubic: Pair<Float, Float>? = null
            var quad: Pair<Float, Float>? = null
            when (command.uppercaseChar()) {
                'M' -> {
                    val nx = px(scanner.number())
                    val ny = py(scanner.number())
                    x = nx; y = ny; startX = nx; startY = ny
                    out += Segment.MoveTo(x, y)
                    // Extra pairs after a moveto are implicit linetos.
                    command = if (relative) 'l' else 'L'
                }
                'L' -> {
                    val nx = px(scanner.number())
                    val ny = py(scanner.number())
                    x = nx; y = ny
                    out += Segment.LineTo(x, y)
                }
                'H' -> {
                    x = px(scanner.number())
                    out += Segment.LineTo(x, y)
                }
                'V' -> {
                    y = py(scanner.number())
                    out += Segment.LineTo(x, y)
                }
                'C' -> {
                    val x1 = px(scanner.number()); val y1 = py(scanner.number())
                    val x2 = px(scanner.number()); val y2 = py(scanner.number())
                    val ex = px(scanner.number()); val ey = py(scanner.number())
                    out += Segment.CubicTo(x1, y1, x2, y2, ex, ey)
                    cubic = x2 to y2
                    x = ex; y = ey
                }
                'S' -> {
                    val x1 = lastCubic?.let { 2 * x - it.first } ?: x
                    val y1 = lastCubic?.let { 2 * y - it.second } ?: y
                    val x2 = px(scanner.number()); val y2 = py(scanner.number())
                    val ex = px(scanner.number()); val ey = py(scanner.number())
                    out += Segment.CubicTo(x1, y1, x2, y2, ex, ey)
                    cubic = x2 to y2
                    x = ex; y = ey
                }
                'Q' -> {
                    val x1 = px(scanner.number()); val y1 = py(scanner.number())
                    val ex = px(scanner.number()); val ey = py(scanner.number())
                    out += Segment.QuadTo(x1, y1, ex, ey)
                    quad = x1 to y1
                    x = ex; y = ey
                }
                'T' -> {
                    val x1 = lastQuad?.let { 2 * x - it.first } ?: x
                    val y1 = lastQuad?.let { 2 * y - it.second } ?: y
                    val ex = px(scanner.number()); val ey = py(scanner.number())
                    out += Segment.QuadTo(x1, y1, ex, ey)
                    quad = x1 to y1
                    x = ex; y = ey
                }
                'A' -> {
                    val rx = scanner.number()
                    val ry = scanner.number()
                    val angle = scanner.number()
                    val large = scanner.flag()
                    val sweep = scanner.flag()
                    val ex = px(scanner.number())
                    val ey = py(scanner.number())
                    arc(out, x, y, ex, ey, rx, ry, angle, large, sweep)
                    x = ex; y = ey
                }
                'Z' -> {
                    out += Segment.Close
                    x = startX; y = startY
                }
                else -> throw IllegalArgumentException("Unknown path command '$command'")
            }
            lastCubic = cubic
            lastQuad = quad
        }
        return out
    }

    /** SVG elliptical arc (endpoint form) as cubic Béziers of at most 90° each. */
    private fun arc(
        out: MutableList<Segment>, x0: Float, y0: Float, x1: Float, y1: Float,
        radiusX: Float, radiusY: Float, angle: Float, large: Boolean, sweep: Boolean,
    ) {
        var rx = abs(radiusX.toDouble())
        var ry = abs(radiusY.toDouble())
        if (rx == 0.0 || ry == 0.0 || (x0 == x1 && y0 == y1)) {
            out += Segment.LineTo(x1, y1)
            return
        }
        val phi = angle * PI / 180
        val cosPhi = cos(phi)
        val sinPhi = sin(phi)
        val dx = (x0 - x1) / 2.0
        val dy = (y0 - y1) / 2.0
        val xp = cosPhi * dx + sinPhi * dy
        val yp = -sinPhi * dx + cosPhi * dy
        val lambda = xp * xp / (rx * rx) + yp * yp / (ry * ry)
        if (lambda > 1) {
            rx *= sqrt(lambda)
            ry *= sqrt(lambda)
        }
        val num = rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp
        val den = rx * rx * yp * yp + ry * ry * xp * xp
        var coef = sqrt(max(0.0, num / den))
        if (large == sweep) coef = -coef
        val cxp = coef * rx * yp / ry
        val cyp = -coef * ry * xp / rx
        val cx = cosPhi * cxp - sinPhi * cyp + (x0 + x1) / 2.0
        val cy = sinPhi * cxp + cosPhi * cyp + (y0 + y1) / 2.0
        val theta1 = atan2((yp - cyp) / ry, (xp - cxp) / rx)
        var delta = atan2((-yp - cyp) / ry, (-xp - cxp) / rx) - theta1
        if (!sweep && delta > 0) delta -= 2 * PI
        if (sweep && delta < 0) delta += 2 * PI
        val segments = max(1, ceil(abs(delta) / (PI / 2)).toInt())
        val step = delta / segments
        val k = 4.0 / 3.0 * tan(step / 4)
        fun pointX(t: Double) = cx + rx * cos(t) * cosPhi - ry * sin(t) * sinPhi
        fun pointY(t: Double) = cy + rx * cos(t) * sinPhi + ry * sin(t) * cosPhi
        fun slopeX(t: Double) = -rx * sin(t) * cosPhi - ry * cos(t) * sinPhi
        fun slopeY(t: Double) = -rx * sin(t) * sinPhi + ry * cos(t) * cosPhi
        var t = theta1
        for (index in 0 until segments) {
            val t2 = t + step
            val last = index == segments - 1
            val ax = pointX(t); val ay = pointY(t)
            val bx = if (last) x1.toDouble() else pointX(t2)
            val by = if (last) y1.toDouble() else pointY(t2)
            out += Segment.CubicTo(
                (ax + k * slopeX(t)).toFloat(), (ay + k * slopeY(t)).toFloat(),
                (bx - k * slopeX(t2)).toFloat(), (by - k * slopeY(t2)).toFloat(),
                bx.toFloat(), by.toFloat(),
            )
            t = t2
        }
    }

    /** Tight-enough bounds of the drawn outline (curves sampled), for tests and sanity checks. */
    fun bounds(segments: List<Segment>): Bounds {
        var minX = Float.MAX_VALUE
        var minY = Float.MAX_VALUE
        var maxX = -Float.MAX_VALUE
        var maxY = -Float.MAX_VALUE
        fun add(px: Float, py: Float) {
            minX = min(minX, px); minY = min(minY, py); maxX = max(maxX, px); maxY = max(maxY, py)
        }
        var x = 0f
        var y = 0f
        var startX = 0f
        var startY = 0f
        for (segment in segments) when (segment) {
            is Segment.MoveTo -> { x = segment.x; y = segment.y; startX = x; startY = y; add(x, y) }
            is Segment.LineTo -> { x = segment.x; y = segment.y; add(x, y) }
            is Segment.QuadTo -> {
                for (i in 1..16) {
                    val t = i / 16f; val u = 1 - t
                    add(u * u * x + 2 * u * t * segment.x1 + t * t * segment.x, u * u * y + 2 * u * t * segment.y1 + t * t * segment.y)
                }
                x = segment.x; y = segment.y
            }
            is Segment.CubicTo -> {
                for (i in 1..24) {
                    val t = i / 24f; val u = 1 - t
                    add(
                        u * u * u * x + 3 * u * u * t * segment.x1 + 3 * u * t * t * segment.x2 + t * t * t * segment.x,
                        u * u * u * y + 3 * u * u * t * segment.y1 + 3 * u * t * t * segment.y2 + t * t * t * segment.y,
                    )
                }
                x = segment.x; y = segment.y
            }
            Segment.Close -> { x = startX; y = startY }
        }
        return Bounds(minX, minY, maxX, maxY)
    }

    private class Scanner(private val text: String) {
        var index = 0
            private set

        private fun skipSeparators() {
            while (index < text.length && (text[index].isWhitespace() || text[index] == ',')) index++
        }

        /** The next command letter or number start, or null at the end. */
        fun peek(): Char? {
            skipSeparators()
            return text.getOrNull(index)
        }

        fun skip() {
            index++
        }

        /** Arc flags may be written without separators ("a5 5 0 105 5"). */
        fun flag(): Boolean {
            skipSeparators()
            return when (text.getOrNull(index)) {
                '0' -> { index++; false }
                '1' -> { index++; true }
                else -> throw IllegalArgumentException("Expected arc flag at $index")
            }
        }

        fun number(): Float {
            skipSeparators()
            val begin = index
            if (index < text.length && (text[index] == '-' || text[index] == '+')) index++
            var dot = false
            var digits = false
            while (index < text.length) {
                val c = text[index]
                when {
                    c.isDigit() -> { digits = true; index++ }
                    c == '.' && !dot -> { dot = true; index++ }
                    (c == 'e' || c == 'E') && digits -> {
                        index++
                        if (index < text.length && (text[index] == '-' || text[index] == '+')) index++
                        while (index < text.length && text[index].isDigit()) index++
                        break
                    }
                    else -> break
                }
            }
            require(digits) { "Expected a number at $begin" }
            return text.substring(begin, index).toFloat()
        }
    }
}
