package io.github.alisonxx.octopbot.store

import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class RestoredAttachmentSessionTest {
    @get:Rule val directory = TemporaryFolder()

    @Test fun concurrentUpgradeIsDurableAndRespectsReplacementAndLogout() = runBlocking {
        val file = File(directory.root, "session.preferences_pb")
        val key = stringPreferencesKey("server")
        val firstRun = SupervisorJob()
        val firstStore = PreferenceDataStoreFactory.create(scope = CoroutineScope(Dispatchers.IO + firstRun)) { file }
        val oldRecord = """{"baseUrl":"https://example.test","token":"fixture","displayName":"A"}"""
        firstStore.edit { it[key] = "sealed:$oldRecord" }
        val open = { value: String -> value.takeIf { it.startsWith("sealed:") }?.removePrefix("sealed:") }
        val seal = { value: String -> "sealed:$value" }
        val ids = try {
            (1..4).map { async { restoreServerSession(firstStore, key, open, seal)?.attachmentCacheId } }.awaitAll()
        } finally {
            firstRun.cancelAndJoin()
        }
        assertNotNull(ids.first())
        assertEquals(1, ids.distinct().size)

        val secondRun = SupervisorJob()
        val secondStore = PreferenceDataStoreFactory.create(scope = CoroutineScope(Dispatchers.IO + secondRun)) { file }
        try {
            assertEquals(ids.first(), restoreServerSession(secondStore, key, open, seal)?.attachmentCacheId)
            val replacement = """{"baseUrl":"https://example.test","token":"fixture-b","displayName":"B","attachmentCacheId":"b"}"""
            secondStore.edit { it[key] = seal(replacement) }
            assertEquals("b", restoreServerSession(secondStore, key, open, seal)?.attachmentCacheId)
            secondStore.edit { it.remove(key) }
            assertNull(restoreServerSession(secondStore, key, open, seal))
        } finally {
            secondRun.cancelAndJoin()
        }
    }
}
