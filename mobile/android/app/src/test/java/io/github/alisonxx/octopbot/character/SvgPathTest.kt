package io.github.alisonxx.octopbot.character

import io.github.alisonxx.octopbot.character.SvgPath.Segment
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class SvgPathTest {
    private val tolerance = 0.6f

    private fun bounds(d: String) = SvgPath.bounds(SvgPath.parse(d))

    @Test
    fun compactNumbersAndImplicitLineTos() {
        val segments = SvgPath.parse("M40.1 4.4l1.5-.4 1.9 .1.5.5z")
        assertEquals(
            listOf(
                Segment.MoveTo(40.1f, 4.4f),
                Segment.LineTo(41.6f, 4.0f),
                Segment.LineTo(43.5f, 4.1f),
                Segment.LineTo(44.0f, 4.6f),
                Segment.Close,
            ).toString(),
            segments.map { it.rounded() }.toString(),
        )
    }

    @Test
    fun horizontalVerticalAndRelative() {
        val b = bounds("M0 0H10V10h-10z")
        assertEquals(SvgPath.Bounds(0f, 0f, 10f, 10f), b)
        val segments = SvgPath.parse("M0 0H10V10h-10z")
        assertEquals(Segment.LineTo(0f, 10f), segments[3])
    }

    @Test
    fun arcCircleBounds() {
        val b = bounds("M50 8a42 42 0 1 1 0 84a42 42 0 1 1 0-84z")
        assertEquals(8f, b.minX, tolerance)
        assertEquals(92f, b.maxX, tolerance)
        assertEquals(8f, b.minY, tolerance)
        assertEquals(92f, b.maxY, tolerance)
    }

    @Test
    fun arcFlagsWithoutSeparators() {
        val segments = SvgPath.parse("M0 0a5 5 0 105 5")
        val last = segments.last() as Segment.CubicTo
        assertEquals(5f, last.x, 1e-4f)
        assertEquals(5f, last.y, 1e-4f)
    }

    @Test
    fun cubicHeartBounds() {
        val heart = "M50 90C28 78 8 62 8 40C8 24 20 12 34 12C42 12 47 17 50 22C53 17 58 12 66 12C80 12 92 24 92 40C92 62 72 78 50 90Z"
        val b = bounds(heart)
        assertEquals(8f, b.minX, tolerance)
        assertEquals(90f, b.maxY, tolerance)
        assertEquals(92f, b.maxX, tolerance)
    }

    @Test
    fun smoothCurvesReflectControlPoints() {
        val cubic = SvgPath.parse("M0 0C0 10 10 10 10 0S20 -10 20 0")
        assertEquals(Segment.CubicTo(10f, -10f, 20f, -10f, 20f, 0f), cubic[2])
        val quad = SvgPath.parse("M0 0Q5 10 10 0T20 0")
        assertEquals(Segment.QuadTo(15f, -10f, 20f, 0f), quad[2])
        // S after a non-curve uses the current point as its first control.
        val plain = SvgPath.parse("M0 0L10 0S20 10 30 0")
        assertEquals(Segment.CubicTo(10f, 0f, 20f, 10f, 30f, 0f), plain[2])
    }

    @Test
    fun exponentsAndRelativeMoveTo() {
        val segments = SvgPath.parse("M1e1 0L2E1,1e-1m5 5 1 1")
        assertEquals(Segment.MoveTo(10f, 0f), segments[0])
        assertEquals(Segment.LineTo(20f, 0.1f), segments[1])
        assertEquals(Segment.MoveTo(25f, 5.1f), segments[2].rounded())
        assertEquals(Segment.LineTo(26f, 6.1f), segments[3].rounded())
    }

    @Test
    fun everyCharacterShapeParsesInsideTheBox() {
        val library = CharacterLibrary.parse(File("src/main/assets/characters.json").readText())
        assertTrue("expected the DS Bot shapes", library.shapes.size >= 19)
        for (shape in library.shapes.values) {
            val parts = listOfNotNull(shape.body, shape.shade, shape.light) + shape.paints.map { it.contours }
            for (segments in parts) {
                assertTrue("${shape.id} has an empty path", segments.isNotEmpty())
                val b = SvgPath.bounds(segments)
                assertTrue("${shape.id} out of box: $b", b.minX >= -2 && b.minY >= -2 && b.maxX <= 102 && b.maxY <= 102)
            }
            val body = SvgPath.bounds(shape.body)
            assertTrue("${shape.id} body too small: $body", body.maxX - body.minX > 40 && body.maxY - body.minY > 40)
            assertTrue("${shape.id} has no eyes", shape.eyes.isNotEmpty())
        }
        assertEquals(listOf("octop") + library.shapes.keys, library.shapeIds)
        assertTrue("aurora" in library.inks)
        assertEquals(3, library.aurora.size)
    }

    private fun Segment.rounded(): Segment {
        fun r(v: Float) = Math.round(v * 1000) / 1000f
        return when (this) {
            is Segment.MoveTo -> Segment.MoveTo(r(x), r(y))
            is Segment.LineTo -> Segment.LineTo(r(x), r(y))
            else -> this
        }
    }
}
