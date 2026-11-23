package io.github.alisonxx.octopbot.character

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class SoftCharactersTest {
    private val library = CharacterLibrary.parse(
        File("src/main/assets/characters.json").readText(),
        File("src/main/assets/soft-characters.json").readText(),
    )

    @Test
    fun softShapesComeFirstThenDsShapes() {
        val soft = listOf("orb", "heart", "sparkle", "drop", "cloud", "bean")
        assertEquals(soft, library.shapes.keys.take(6))
        assertEquals(listOf("octop") + soft, library.shapeIds.take(7))
        // Every DS shape is still there, after the soft ones.
        val ds = CharacterLibrary.parse(File("src/main/assets/characters.json").readText())
        assertEquals(ds.shapes.keys.toList(), library.shapes.keys.drop(6))
        assertEquals("sparkle", library.shape("sparkle")?.id)
    }

    @Test
    fun flatShapesHaveNoShadeOrLight() {
        val drop = library.shapes.getValue("drop")
        assertTrue(drop.flat)
        assertTrue(drop.shade.isEmpty())
        assertNull(drop.light)
        assertTrue(drop.paints.isEmpty())
        assertEquals(2, drop.eyes.size)
        assertFalse(library.shapes.getValue("gumdrop").flat)
    }

    @Test
    fun softInksOverrideAndComeFirst() {
        assertEquals(listOf("red", "orange", "green", "blue", "violet", "black"), library.inkIds.take(6))
        assertEquals(library.inkIds.size, library.inkIds.toSet().size)
        assertEquals(CharacterLibrary.parseHex("#11AF98"), library.ink("green"))
        assertEquals(CharacterLibrary.parseHex("#25C6AE"), library.ink("green", dark = true))
        // The soft black is white in dark mode.
        assertEquals(CharacterLibrary.parseHex("#000000"), library.ink("black"))
        assertEquals(CharacterLibrary.parseHex("#FFFFFF"), library.ink("black", dark = true))
        // DS-only inks are kept after the soft ones.
        assertEquals(CharacterLibrary.parseHex("#082DFF"), library.ink("cobalt"))
        assertEquals(CharacterLibrary.parseHex("#5C78FF"), library.ink("cobalt", dark = true))
    }
}
