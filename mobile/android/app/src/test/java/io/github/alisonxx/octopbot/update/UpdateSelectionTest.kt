package io.github.alisonxx.octopbot.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UpdateSelectionTest {
    private fun asset(code: Int, min: Int? = null, url: String = "https://dl.lynxce.cn/releases/octop-bot/x/app-$code.apk") =
        AndroidAsset("app-$code.apk", url, "ab".repeat(32), 10, "0.$code.0", code, min)

    private fun channel(version: String, code: Int?, rollout: Int = 100, min: Int? = null) =
        ReleaseChannel(version, rollout, code?.let { asset(it, min) })

    @Test
    fun bucketMatchesTheDesktopFormula() {
        // sha256("install-a:1.0.4")[0..4] big-endian % 100, as in desktop/src/main/update/bot-feed.ts.
        assertEquals(7, UpdateSelection.bucket("install-a", "1.0.4"))
        assertEquals(9, UpdateSelection.bucket("abc", "1.0.4b1"))
        repeat(200) { assertTrue(UpdateSelection.bucket("id-$it", "1.0.4") in 0..99) }
    }

    @Test
    fun rolloutSharesFollowTheBucket() {
        val bucket = UpdateSelection.bucket("install-a", "1.0.4") // 7
        assertTrue(UpdateSelection.inRollout(channel("1.0.4", 2, rollout = 100), "install-a"))
        assertFalse(UpdateSelection.inRollout(channel("1.0.4", 2, rollout = 0), "install-a"))
        assertTrue(UpdateSelection.inRollout(channel("1.0.4", 2, rollout = bucket + 1), "install-a"))
        assertFalse(UpdateSelection.inRollout(channel("1.0.4", 2, rollout = bucket), "install-a"))
    }

    @Test
    fun stableOnlyUnlessBetaIsOn() {
        val manifest = UpdateManifest(stable = channel("1.0.4", 2), beta = channel("1.0.5b1", 3))
        assertEquals(2, UpdateSelection.offer(manifest, receiveBeta = false, installId = "a", currentVersionCode = 1)?.versionCode)
        assertEquals(3, UpdateSelection.offer(manifest, receiveBeta = true, installId = "a", currentVersionCode = 1)?.versionCode)
        // An older beta does not win over stable.
        val olderBeta = manifest.copy(beta = channel("1.0.3b1", 1))
        assertEquals(2, UpdateSelection.offer(olderBeta, receiveBeta = true, installId = "a", currentVersionCode = 1)?.versionCode)
        // Beta alone, without the setting, offers nothing.
        assertNull(UpdateSelection.offer(UpdateManifest(null, channel("1.0.5b1", 3)), false, "a", 1))
    }

    @Test
    fun channelsOutsideTheirRolloutAreSkipped() {
        val manifest = UpdateManifest(stable = channel("1.0.4", 2), beta = channel("1.0.5b1", 3, rollout = 0))
        assertEquals(2, UpdateSelection.offer(manifest, true, "a", 1)?.versionCode)
        assertNull(UpdateSelection.offer(manifest.copy(stable = channel("1.0.4", 2, rollout = 0)), false, "a", 1))
    }

    @Test
    fun onlyNewerVersionCodes() {
        val manifest = UpdateManifest(stable = channel("1.0.4", 2), beta = null)
        assertNull(UpdateSelection.offer(manifest, false, "a", 2))
        assertNull(UpdateSelection.offer(manifest, false, "a", 3))
        assertNull(UpdateSelection.offer(UpdateManifest(channel("1.0.4", null), null), false, "a", 1))
        val offer = UpdateSelection.offer(manifest, false, "a", 1)!!
        assertEquals("0.2.0", offer.version)
        assertEquals("ab".repeat(32), offer.sha256)
    }

    @Test
    fun urgentBelowTheMinimum() {
        val manifest = UpdateManifest(stable = channel("1.0.4", 5, min = 3), beta = null)
        assertTrue(UpdateSelection.offer(manifest, false, "a", 2)!!.urgent)
        assertFalse(UpdateSelection.offer(manifest, false, "a", 3)!!.urgent)
        assertFalse(UpdateSelection.offer(manifest, false, "a", 4)!!.urgent)
        assertFalse(UpdateSelection.offer(UpdateManifest(channel("1.0.4", 5), null), false, "a", 1)!!.urgent)
    }

    @Test
    fun downloadsOnlyFromTheReleaseHost() {
        assertTrue(UpdateSelection.isAllowedUrl("https://dl.lynxce.cn/releases/octop-bot/1.0.4/a.apk"))
        assertTrue(UpdateSelection.isAllowedUrl("https://DL.lynxce.cn:443/a.apk"))
        assertFalse(UpdateSelection.isAllowedUrl("http://dl.lynxce.cn/a.apk"))
        assertFalse(UpdateSelection.isAllowedUrl("https://dl.lynxce.cn:8443/a.apk"))
        assertFalse(UpdateSelection.isAllowedUrl("https://evil.example/a.apk"))
        assertFalse(UpdateSelection.isAllowedUrl("https://dl.lynxce.cn.evil.example/a.apk"))
        assertFalse(UpdateSelection.isAllowedUrl("not a url"))
        // The debug-only origin of a local test manifest.
        assertFalse(UpdateSelection.isAllowedUrl("http://10.0.2.2:8765/a.apk"))
        assertTrue(UpdateSelection.isAllowedUrl("http://10.0.2.2:8765/a.apk", "http://10.0.2.2:8765"))
        assertFalse(UpdateSelection.isAllowedUrl("http://10.0.2.2:9999/a.apk", "http://10.0.2.2:8765"))
        assertFalse(UpdateSelection.isAllowedUrl("https://10.0.2.2:8765/a.apk", "http://10.0.2.2:8765"))
    }

    @Test
    fun aDisallowedUrlFallsBackToTheOtherChannel() {
        val bad = ReleaseChannel("1.0.5b1", 100, asset(3, url = "https://evil.example/a.apk"))
        val manifest = UpdateManifest(stable = channel("1.0.4", 2), beta = bad)
        assertEquals(2, UpdateSelection.offer(manifest, true, "a", 1)?.versionCode)
    }

    @Test
    fun dismissedBannerStaysHiddenForThatVersionOnly() {
        val offer = UpdateSelection.offer(UpdateManifest(channel("1.0.4", 2), null), false, "a", 1)
        assertTrue(UpdateSelection.showBanner(offer, dismissedVersionCode = null))
        assertFalse(UpdateSelection.showBanner(offer, dismissedVersionCode = 2))
        val newer = UpdateSelection.offer(UpdateManifest(channel("1.0.5", 3), null), false, "a", 1)
        assertTrue(UpdateSelection.showBanner(newer, dismissedVersionCode = 2))
        assertFalse(UpdateSelection.showBanner(null, dismissedVersionCode = null))
    }

    @Test
    fun foregroundChecksAfter24Hours() {
        val day = 24 * 3600 * 1000L
        assertTrue(UpdateSelection.checkDue(null, 0))
        assertFalse(UpdateSelection.checkDue(1_000, 1_000 + day))
        assertTrue(UpdateSelection.checkDue(1_000, 1_000 + day + 1))
    }

    @Test
    fun signersMustMatchExactly() {
        val a = byteArrayOf(1, 2, 3)
        val b = byteArrayOf(4, 5, 6)
        assertTrue(ApkInstaller.signersMatch(listOf(a), listOf(a.copyOf())))
        assertFalse(ApkInstaller.signersMatch(listOf(a), listOf(b)))
        assertFalse(ApkInstaller.signersMatch(listOf(a), listOf(a, b)))
        assertFalse(ApkInstaller.signersMatch(emptyList(), emptyList()))
    }
}
