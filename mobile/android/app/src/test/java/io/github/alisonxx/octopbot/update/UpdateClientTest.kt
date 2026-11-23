package io.github.alisonxx.octopbot.update

import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okio.Buffer
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.Signature
import java.util.Base64

class UpdateClientTest {
    @get:Rule val temp = TemporaryFolder()
    private val server = MockWebServer()
    private val http = OkHttpClient()
    private val keys = KeyPairGenerator.getInstance("Ed25519").generateKeyPair()
    private val publicKey = Base64.getEncoder().encodeToString(keys.public.encoded)
    private val manifest = """{"schema":1,"product":"octop-bot","channels":{"stable":{"version":"1.0.4","assets":{}}}}"""

    @Before fun start() = server.start()
    @After fun stop() = server.close()

    private fun sign(text: String) = Base64.getEncoder().encodeToString(
        Signature.getInstance("Ed25519").run { initSign(keys.private); update(text.toByteArray()); sign() },
    )

    private fun client(verify: Boolean = true) = UpdateClient(http, server.url("/manifest.json").toString(), publicKey, verify)

    private fun body(text: String) = MockResponse.Builder().body(text).build()

    @Test
    fun fetchesAndVerifiesTheManifest() = runTest {
        server.enqueue(body(manifest))
        server.enqueue(body(sign(manifest) + "\n"))
        assertEquals("1.0.4", client().fetchManifest().stable?.version)
        assertEquals("/manifest.json", server.takeRequest().url.encodedPath)
        assertEquals("/manifest.json.sig", server.takeRequest().url.encodedPath)
    }

    @Test
    fun aBadSignatureFailsTheCheck() = runTest {
        server.enqueue(body(manifest))
        server.enqueue(body(sign(manifest.replace("1.0.4", "1.0.5"))))
        try {
            client().fetchManifest()
            fail("expected a signature failure")
        } catch (expected: ManifestException) {
        }
    }

    @Test
    fun belowAndroid13TheSignatureIsSkipped() = runTest {
        server.enqueue(body(manifest))
        assertEquals("1.0.4", client(verify = false).fetchManifest().stable?.version)
        assertEquals(1, server.requestCount)
    }

    private fun offer(bytes: ByteArray, sha: String = hex(bytes)) =
        UpdateOffer("0.2.0", 2, server.url("/app.apk").toString(), sha, bytes.size.toLong(), urgent = false)

    private fun hex(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

    @Test
    fun downloadsWithProgressAndChecksTheHash() = runTest {
        val apk = ByteArray(300_000) { (it % 251).toByte() }
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        val progress = mutableListOf<Int>()
        val target = temp.root.resolve("updates/app.apk")
        val file = client().download(offer(apk), target) { progress += it }
        assertArrayEquals(apk, file.readBytes())
        assertEquals(100, progress.last())
        assertTrue(progress.zipWithNext().all { (a, b) -> b > a })
        // A finished file with the right hash is reused without downloading again.
        client().download(offer(apk), target) {}
        assertEquals(1, server.requestCount)
    }

    @Test
    fun aHashMismatchDeletesTheDownload() = runTest {
        val apk = ByteArray(1000) { 7 }
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        val target = temp.root.resolve("app.apk")
        try {
            client().download(offer(apk, sha = "0".repeat(64)), target) {}
            fail("expected a hash mismatch")
        } catch (expected: UpdateException) {
            assertTrue(expected.integrity)
        }
        assertFalse(target.exists())
        assertFalse(temp.root.resolve("app.apk.part").exists())
    }

    @Test
    fun aFailedResponseCanBeRetried() = runTest {
        val apk = ByteArray(1000) { 3 }
        server.enqueue(MockResponse.Builder().code(503).build())
        server.enqueue(MockResponse.Builder().body(Buffer().write(apk)).build())
        val target = temp.root.resolve("app.apk")
        try {
            client().download(offer(apk), target) {}
            fail("expected an HTTP failure")
        } catch (expected: UpdateException) {
            assertFalse(expected.integrity)
        }
        assertArrayEquals(apk, client().download(offer(apk), target) {}.readBytes())
    }
}
