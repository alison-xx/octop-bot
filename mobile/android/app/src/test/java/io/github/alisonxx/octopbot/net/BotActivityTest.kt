package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.net.BotActivity.FileKind
import io.github.alisonxx.octopbot.net.BotActivity.Period
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BotActivityTest {
    @Test
    fun upcomingKeepsServerOrderAndSkipsRowsWithoutId() {
        val jobs = BotActivity.upcoming(
            Http.parse(
                """{"timezone":"Asia/Shanghai","jobs":[
                  {"id":"a","name":"Morning brief","enabled":true,"schedule":"工作日 8:50","next_run_at":1,"can_toggle":true},
                  {"id":"b","name":"Script","enabled":false,"schedule":"自定义","next_run_at":null,"can_toggle":false},
                  {"name":"no id"}
                ]}""",
            ),
        )
        assertEquals(listOf("a", "b"), jobs.map { it.id })
        assertEquals("工作日 8:50", jobs[0].schedule)
        assertTrue(jobs[0].enabled && jobs[0].canToggle)
        assertFalse(jobs[1].enabled || jobs[1].canToggle)
        assertEquals(emptyList<BotActivity.UpcomingJob>(), BotActivity.upcoming(Http.parse("[]")))
    }

    @Test
    fun libraryGroupsByRecencyInServerOrder() {
        fun row(name: String, period: String) =
            """{"name":"$name","path":"outbound/$name","mime":null,"period":"$period","url":"/api/agents/A/workspace/download?path=outbound%2F$name"}"""
        val files = BotActivity.library(
            Http.parse("""{"files":[${row("new.pdf", "today")},${row("old.xlsx", "older")},${row("mid.md", "week")},${row("b.png", "today")}]}"""),
        )
        val groups = BotActivity.grouped(files)
        assertEquals(listOf(Period.Today, Period.Week, Period.Older), groups.map { it.first })
        assertEquals(listOf("new.pdf", "b.png"), groups[0].second.map { it.name })
        assertTrue(ServerProtocol.isWorkspaceDownload(files[0].url))
        assertTrue(BotActivity.grouped(emptyList()).isEmpty())
    }

    @Test
    fun fileKindsFromTypeOrExtension() {
        fun kind(name: String, mime: String? = null) =
            BotActivity.kind(BotActivity.LibraryFile(name, name, mime, Period.Today, ""))
        assertEquals(FileKind.Image, kind("a.png", "image/png"))
        assertEquals(FileKind.Slides, kind("deck.KEY"))
        assertEquals(FileKind.Sheet, kind("sheet.csv"))
        assertEquals(FileKind.Other, kind("blob.bin"))
    }
}
