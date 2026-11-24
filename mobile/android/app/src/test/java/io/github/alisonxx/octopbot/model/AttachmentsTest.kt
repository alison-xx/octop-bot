package io.github.alisonxx.octopbot.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class AttachmentsTest {
    @Test
    fun kindFollowsExtensionThenMime() {
        assertEquals(FileKind.Pdf, FileCards.kind("Report.PDF"))
        assertEquals(FileKind.Word, FileCards.kind("notes.docx"))
        assertEquals(FileKind.Excel, FileCards.kind("dec2026.csv"))
        assertEquals(FileKind.Excel, FileCards.kind("budget.xlsx"))
        assertEquals(FileKind.PowerPoint, FileCards.kind("deck.pptx"))
        assertEquals(FileKind.Archive, FileCards.kind("logs.tar.gz"))
        assertEquals(FileKind.Other, FileCards.kind("photo.png"))
        assertEquals(FileKind.Other, FileCards.kind("README"))
        assertEquals(FileKind.Pdf, FileCards.kind("download", "application/pdf"))
        assertEquals(FileKind.Word, FileCards.kind("x", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        assertEquals(FileKind.Archive, FileCards.kind("x", "application/zip"))
    }

    @Test
    fun typeLabelIsShortUppercaseExtension() {
        assertEquals("PDF", FileCards.typeLabel("a.pdf"))
        assertEquals("DOCX", FileCards.typeLabel("a.docx"))
        assertNull(FileCards.typeLabel("README"))
        assertNull(FileCards.typeLabel(".env"))
        assertNull(FileCards.typeLabel("a.numbers"))
    }

    @Test
    fun previewKinds() {
        assertEquals(FilePreview.Image, FileCards.preview("a.JPG"))
        assertEquals(FilePreview.Pdf, FileCards.preview("a.pdf"))
        assertEquals(FilePreview.Text, FileCards.preview("a.csv"))
        assertEquals(FilePreview.Text, FileCards.preview("notes.md"))
        assertEquals(FilePreview.None, FileCards.preview("a.docx"))
        assertEquals(FilePreview.Image, FileCards.preview("shot", "image/png"))
        assertTrue(FileAttachment("/api/x", "a.webp").isImage)
        assertFalse(FileAttachment("/api/x", "a.svg").isImage)
    }

    @Test
    fun middleEllipsisKeepsTheExtension() {
        assertEquals("short.pdf", FileCards.middleEllipsis("short.pdf"))
        val long = "Quarterly-report-final-v2.pdf"
        val cut = FileCards.middleEllipsis(long)
        assertEquals("Quarterly-report-…l-v2.pdf", cut)
        assertEquals(26, cut.length)
        assertTrue(FileCards.middleEllipsis("Octop-Bot-annual-planning-meeting-notes.pdf", 20).endsWith(".pdf"))
        assertEquals(20, FileCards.middleEllipsis("Octop-Bot-annual-planning-meeting-notes.pdf", 20).length)
        // Code-point safe: emoji and CJK are never split.
        val cjk = FileCards.middleEllipsis("二〇二六年十二月销售数据汇总表格最终版本😀😀😀😀.xlsx", 16)
        assertTrue(cjk.endsWith("😀😀.xlsx") || cjk.endsWith(".xlsx"))
        assertEquals(16, cjk.codePointCount(0, cjk.length))
        // No extension: still bounded.
        assertEquals(10, FileCards.middleEllipsis("abcdefghijklmnopqrstuvwxyz", 10).length)
    }

    @Test
    fun fileSizes() {
        assertEquals("0 B", FileCards.formatFileSize(0))
        assertEquals("512 B", FileCards.formatFileSize(512))
        assertEquals("1 KB", FileCards.formatFileSize(1024))
        assertEquals("1.5 KB", FileCards.formatFileSize(1536))
        assertEquals("2 MB", FileCards.formatFileSize(2L * 1024 * 1024))
        assertEquals("2.4 MB", FileCards.formatFileSize((2.4 * 1024 * 1024).toLong()))
        assertEquals("12 MB", FileCards.formatFileSize(12L * 1024 * 1024 + 300))
        assertEquals("1 MB", FileCards.formatFileSize(1024L * 1024 - 1))
        assertEquals("3 GB", FileCards.formatFileSize(3L * 1024 * 1024 * 1024))
    }

    @Test
    fun linksInMarkdownBecomeCards() {
        val text = """
            Here is the [report](/api/agents/A1/workspace/download?path=outbound%2FQ4%20report.pdf) and
            [again](/api/agents/A1/workspace/download?path=outbound%2FQ4%20report.pdf), plus
            [site](https://example.com/a.pdf) and [data](/api/agents/A1/workspace/download?path=%2FUsers%2Fme%2Fdec2026.csv).
        """.trimIndent()
        val links = FileCards.linksIn(text)
        assertEquals(listOf("Q4 report.pdf", "dec2026.csv"), links.map { it.name })
        assertEquals("/api/agents/A1/workspace/download?path=outbound%2FQ4%20report.pdf", links[0].url)
        assertTrue(FileCards.linksIn("no links here").isEmpty())
    }

    @Test
    fun mergeKeepsOrderAndDropsDuplicateUrls() {
        val a = FileAttachment("/api/a", "a.pdf")
        val b = FileAttachment("/api/b", "b.pdf")
        assertEquals(listOf(a, b), FileCards.merge(listOf(a), listOf(a.copy(name = "other"), b)))
    }
}
