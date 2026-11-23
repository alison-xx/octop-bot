package io.github.alisonxx.octopbot.update

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.Signature
import java.util.Base64

class ManifestSignatureTest {
    private val body = """{"schema":1,"product":"octop-bot","channels":{}}""".toByteArray()

    private fun keyPair(): KeyPair = KeyPairGenerator.getInstance("Ed25519").generateKeyPair()

    private fun sign(pair: KeyPair, bytes: ByteArray): String =
        Base64.getEncoder().encodeToString(Signature.getInstance("Ed25519").run { initSign(pair.private); update(bytes); sign() })

    private fun spki(pair: KeyPair) = Base64.getEncoder().encodeToString(pair.public.encoded)

    @Test
    fun acceptsTheExactSignedBytes() {
        val pair = keyPair()
        assertTrue(ManifestSignature.verify(body, sign(pair, body), spki(pair)))
        // A trailing newline in the .sig file is fine.
        assertTrue(ManifestSignature.verify(body, sign(pair, body) + "\n", spki(pair)))
    }

    @Test
    fun rejectsChangedBytesOtherKeysAndGarbage() {
        val pair = keyPair()
        val signature = sign(pair, body)
        assertFalse(ManifestSignature.verify(body + ' '.code.toByte(), signature, spki(pair)))
        assertFalse(ManifestSignature.verify(body, signature, spki(keyPair())))
        assertFalse(ManifestSignature.verify(body, "not base64!", spki(pair)))
        assertFalse(ManifestSignature.verify(body, "", spki(pair)))
        assertFalse(ManifestSignature.verify(body, signature, "AAAA"))
    }

    private fun hex(text: String) = text.chunked(2).map { it.toInt(16).toByte() }.toByteArray()

    @Test
    fun rfc8032TestVectors() {
        // RFC 8032 §7.1, tests 1 and 2.
        assertTrue(
            Ed25519.verify(
                hex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"),
                ByteArray(0),
                hex(
                    "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
                ),
            ),
        )
        val key2 = hex("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
        val sig2 = hex(
            "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
        )
        assertTrue(Ed25519.verify(key2, byteArrayOf(0x72), sig2))
        assertFalse(Ed25519.verify(key2, byteArrayOf(0x73), sig2))
        assertFalse(Ed25519.verify(key2, byteArrayOf(0x72), sig2.copyOf(63)))
    }

    @Test
    fun agreesWithTheJdkOnRandomKeysAndMessages() {
        val random = java.util.Random(7)
        repeat(30) {
            val pair = keyPair()
            val message = ByteArray(random.nextInt(2000)).also(random::nextBytes)
            val signature = sign(pair, message)
            assertTrue(ManifestSignature.verify(message, signature, spki(pair)))
            val flipped = Base64.getDecoder().decode(signature).also {
                val i = random.nextInt(64)
                it[i] = (it[i].toInt() xor (1 shl random.nextInt(8))).toByte()
            }
            assertFalse(ManifestSignature.verify(message, Base64.getEncoder().encodeToString(flipped), spki(pair)))
        }
    }

    @Test
    fun rejectsNonCanonicalScalarsAndForeignKeys() {
        val pair = keyPair()
        val signature = Base64.getDecoder().decode(sign(pair, body))
        // s + q (the group order) verifies mathematically but is not canonical: RFC 8032 requires s < q.
        val q = java.math.BigInteger.TWO.pow(252) + java.math.BigInteger("27742317777372353535851937790883648493")
        val s = java.math.BigInteger(1, signature.copyOfRange(32, 64).reversedArray()) + q
        val bigS = s.toByteArray().reversedArray().copyOf(32)
        val malleated = signature.copyOf(32) + bigS
        assertFalse(ManifestSignature.verify(body, Base64.getEncoder().encodeToString(malleated), spki(pair)))
        // An Ed448 or EC key is not an Ed25519 SubjectPublicKeyInfo.
        val ec = KeyPairGenerator.getInstance("EC").generateKeyPair().public.encoded
        assertFalse(ManifestSignature.verify(body, sign(pair, body), Base64.getEncoder().encodeToString(ec)))
    }

    @Test
    fun theReleaseKeyParses() {
        // A wrong signature, but the built-in key must load and fail cleanly rather than throw.
        val releaseKey = "MCowBQYDK2VwAyEAjfzS5kpiVxqx/79rU5tYno7Js31ezDt05RmrmXnRTa0="
        assertFalse(ManifestSignature.verify(body, sign(keyPair(), body), releaseKey))
        val der = Base64.getDecoder().decode(releaseKey)
        assertTrue(der.size == 44)
    }
}
