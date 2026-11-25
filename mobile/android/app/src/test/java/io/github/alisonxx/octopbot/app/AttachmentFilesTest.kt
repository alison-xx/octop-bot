package io.github.alisonxx.octopbot.app

import io.github.alisonxx.octopbot.model.FileAttachment
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class AttachmentFilesTest {
    @get:Rule val cache = TemporaryFolder()
    private val report = FileAttachment("/reports/daily", "daily.txt")

    @Test fun ownersKeepTheirOwnSizeAndFileAcrossRestart() = runBlocking {
        val files = AttachmentFiles(cache.root)
        val ownerA = "test-host/account-a"
        val ownerB = "test-host/account-b"
        assertEquals(3L, files.size(ownerA, report) { 3L })
        assertEquals(6L, files.size(ownerB, report) { 6L })
        val a = files.local(ownerA, report) { _, target -> target.writeText("one") }
        val b = files.local(ownerB, report) { _, target -> target.writeText("second") }
        assertNotEquals(a, b)
        val restored = AttachmentFiles(cache.root)
        assertEquals("one", restored.local(ownerA, report) { _, _ -> error("expected cache hit") }.readText())
        assertEquals("second", restored.local(ownerB, report) { _, _ -> error("expected cache hit") }.readText())
        assertEquals("attachment-sessions", a.parentFile!!.parentFile!!.name)
    }

    @Test fun lateDownloadRemainsInOriginalNamespace() = runBlocking {
        val files = AttachmentFiles(cache.root)
        val started = CompletableDeferred<Unit>()
        val finish = CompletableDeferred<Unit>()
        val a = async {
            files.local("a", report) { _, target ->
                started.complete(Unit)
                finish.await()
                target.writeText("first")
            }
        }
        started.await()
        val b = files.local("b", report) { _, target -> target.writeText("second") }
        finish.complete(Unit)
        assertNotEquals(a.await(), b)
        assertEquals("second", b.readText())
        assertEquals(6L, files.size("b", report) { error("expected owner B's cached size") })
    }

    @Test fun unownedLegacyFilesRemainOutsideTheNewCache() = runBlocking {
        val old = File(cache.root, "attachments/old-entry/daily.txt")
        old.parentFile!!.mkdirs()
        old.writeText("unowned local copy")
        val files = AttachmentFiles(cache.root)
        val owned = files.local("current", report) { _, target -> target.writeText("owned") }
        assertEquals("owned", owned.readText())
        assertEquals("unowned local copy", old.readText())
    }
}
