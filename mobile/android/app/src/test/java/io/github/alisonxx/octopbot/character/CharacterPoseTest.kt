package io.github.alisonxx.octopbot.character

import io.github.alisonxx.octopbot.model.BotMotion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CharacterPoseTest {
    @Test
    fun blinkClosesBrieflyOncePerCycle() {
        assertEquals(1f, CharacterPose.at(BotMotion.Idle, 0f, 0.2f).blink, 0f)
        assertEquals(0.12f, CharacterPose.at(BotMotion.Idle, 0f, 0.67f).blink, 1e-3f)
        assertEquals(1f, CharacterPose.at(BotMotion.Idle, 0f, 0.7f).blink, 0f)
    }

    @Test
    fun motionsMoveTheFigure() {
        assertEquals(-0.02f, CharacterPose.at(BotMotion.Idle, 0.5f, 0f).offsetY, 1e-4f)
        assertEquals(-0.04f, CharacterPose.at(BotMotion.Working, 0.5f, 0f).offsetY, 1e-4f)
        assertEquals(-4f, CharacterPose.at(BotMotion.Thinking, 0.5f, 0f).rotation, 1e-3f)
        assertTrue(CharacterPose.at(BotMotion.Searching, 0.25f, 0f).look > 0.1f)
        assertTrue(CharacterPose.at(BotMotion.Waiting, 0.2f, 0f).rotation < 0f)
        assertEquals(0f, CharacterPose.at(BotMotion.Waiting, 0.8f, 0f).rotation, 1e-6f)
    }

    @Test
    fun phaseIsStablePerSeed() {
        assertEquals(CharacterPose.phaseMillis("chief"), CharacterPose.phaseMillis("chief"))
        assertNotEquals(CharacterPose.phaseMillis("chief"), CharacterPose.phaseMillis("researcher"))
        val breath = CharacterPose.periodMillis(BotMotion.Idle, CharacterPose.phaseMillis("chief"))
        assertTrue(breath in 3800..4899)
    }
}
