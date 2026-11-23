package io.github.alisonxx.octopbot.update

import java.math.BigInteger
import java.security.MessageDigest
import java.util.Base64

/**
 * Ed25519 check of the detached manifest signature (`manifest.json.sig`, base64) over the manifest's exact bytes.
 *
 * Android's `Signature.getInstance("Ed25519")` only serves Android Keystore keys: no platform provider takes an
 * outside public key (checked on API 36), so this is RFC 8032 verification in plain Kotlin. It runs once per
 * check on one small manifest, so BigInteger arithmetic is fast enough.
 */
object ManifestSignature {
    /** DER prefix of an Ed25519 SubjectPublicKeyInfo (OID 1.3.101.112); the 32-byte key follows. */
    private val SPKI_PREFIX = byteArrayOf(0x30, 0x2a, 0x30, 0x05, 0x06, 0x03, 0x2b, 0x65, 0x70, 0x03, 0x21, 0x00)

    /** [publicKey] is a base64 X.509 SubjectPublicKeyInfo (the body of the PEM). Any error is a failed check. */
    fun verify(body: ByteArray, signature: String, publicKey: String): Boolean = runCatching {
        val spki = Base64.getMimeDecoder().decode(publicKey.trim())
        if (spki.size != SPKI_PREFIX.size + 32 || !spki.copyOf(SPKI_PREFIX.size).contentEquals(SPKI_PREFIX)) return false
        Ed25519.verify(spki.copyOfRange(SPKI_PREFIX.size, spki.size), body, Base64.getMimeDecoder().decode(signature.trim()))
    }.getOrDefault(false)
}

/** RFC 8032 §5.1.7 verification: the reference algorithm in extended coordinates. */
internal object Ed25519 {
    // BigInteger.TWO needs API 33.
    private val TWO: BigInteger = BigInteger.valueOf(2)
    private val p: BigInteger = TWO.pow(255) - BigInteger.valueOf(19)
    private val q: BigInteger = TWO.pow(252) + BigInteger("27742317777372353535851937790883648493")
    private val d: BigInteger = BigInteger.valueOf(-121665).mod(p) * BigInteger.valueOf(121666).modInverse(p) % p
    private val sqrtM1: BigInteger = TWO.modPow((p - BigInteger.ONE) / BigInteger.valueOf(4), p)
    private val identity = Point(BigInteger.ZERO, BigInteger.ONE, BigInteger.ONE, BigInteger.ZERO)
    private val base: Point = run {
        val y = BigInteger.valueOf(4) * BigInteger.valueOf(5).modInverse(p) % p
        val x = recoverX(y, sign = false)!!
        Point(x, y, BigInteger.ONE, x * y % p)
    }

    private class Point(val x: BigInteger, val y: BigInteger, val z: BigInteger, val t: BigInteger)

    fun verify(publicKey: ByteArray, message: ByteArray, signature: ByteArray): Boolean {
        if (publicKey.size != 32 || signature.size != 64) return false
        val a = decompress(publicKey) ?: return false
        val rBytes = signature.copyOfRange(0, 32)
        val r = decompress(rBytes) ?: return false
        val s = littleEndian(signature.copyOfRange(32, 64))
        if (s >= q) return false
        val digest = MessageDigest.getInstance("SHA-512").run {
            update(rBytes)
            update(publicKey)
            update(message)
            digest()
        }
        val h = littleEndian(digest) % q
        return equal(multiply(s, base), add(r, multiply(h, a)))
    }

    private fun add(a: Point, b: Point): Point {
        val pa = (a.y - a.x) * (b.y - b.x) % p
        val pb = (a.y + a.x) * (b.y + b.x) % p
        val pc = TWO * a.t * b.t * d % p
        val pd = TWO * a.z * b.z % p
        val e = pb - pa
        val f = pd - pc
        val g = pd + pc
        val h = pb + pa
        return Point((e * f).mod(p), (g * h).mod(p), (f * g).mod(p), (e * h).mod(p))
    }

    private fun multiply(scalar: BigInteger, point: Point): Point {
        var result = identity
        var addend = point
        for (i in 0 until scalar.bitLength()) {
            if (scalar.testBit(i)) result = add(result, addend)
            addend = add(addend, addend)
        }
        return result
    }

    private fun equal(a: Point, b: Point): Boolean =
        (a.x * b.z - b.x * a.z).mod(p).signum() == 0 && (a.y * b.z - b.y * a.z).mod(p).signum() == 0

    private fun recoverX(y: BigInteger, sign: Boolean): BigInteger? {
        if (y >= p) return null
        val x2 = ((y * y - BigInteger.ONE) * (d * y * y + BigInteger.ONE).modInverse(p)).mod(p)
        if (x2.signum() == 0) return if (sign) null else BigInteger.ZERO
        var x = x2.modPow((p + BigInteger.valueOf(3)) / BigInteger.valueOf(8), p)
        if ((x * x - x2).mod(p).signum() != 0) x = x * sqrtM1 % p
        if ((x * x - x2).mod(p).signum() != 0) return null
        if (x.testBit(0) != sign) x = p - x
        return x
    }

    private fun decompress(bytes: ByteArray): Point? {
        val value = littleEndian(bytes)
        val y = value.clearBit(255)
        val x = recoverX(y, sign = value.testBit(255)) ?: return null
        return Point(x, y, BigInteger.ONE, x * y % p)
    }

    private fun littleEndian(bytes: ByteArray): BigInteger = BigInteger(1, bytes.reversedArray())
}
