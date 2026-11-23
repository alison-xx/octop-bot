package io.github.alisonxx.octopbot.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class ManifestParserTest {
    private val sha = "AB".repeat(32)

    private fun android(fields: String = "") =
        """{"name":"octop-bot-0.2.0.apk","url":"https://dl.lynxce.cn/releases/octop-bot/1.0.4/octop-bot-0.2.0.apk",
            "sha256":"$sha","size":123,"version":"0.2.0","version_code":2$fields}"""

    private fun manifest(stable: String, beta: String? = null, root: String = "\"schema\":1,\"product\":\"octop-bot\"") =
        """{$root,"channels":{"stable":$stable${beta?.let { ",\"beta\":$it" }.orEmpty()}}}"""

    private fun channel(android: String? = android(), extra: String = "") =
        """{"version":"1.0.4","rollout":100$extra,"assets":{"win_x64":{"url":"x"}${android?.let { ",\"android\":$it" }.orEmpty()}}}"""

    @Test
    fun parsesStableAndBetaAndroidAssets() {
        val parsed = ManifestParser.parse(
            manifest(channel(android(",\"min_version_code\":1,\"extra\":true")), channel(extra = ",\"notes\":{\"zh\":\"x\"}")),
        )
        val asset = parsed.stable!!.android!!
        assertEquals("1.0.4", parsed.stable!!.version)
        assertEquals(100, parsed.stable!!.rollout)
        assertEquals(2, asset.versionCode)
        assertEquals("0.2.0", asset.version)
        assertEquals(1, asset.minVersionCode)
        assertEquals(123L, asset.size)
        assertEquals("ab".repeat(32), asset.sha256)
        assertEquals("octop-bot-0.2.0.apk", asset.name)
        assertNull(parsed.beta!!.android!!.minVersionCode)
    }

    @Test
    fun missingOptionalPartsAreFine() {
        val parsed = ManifestParser.parse(
            """{"schema":1,"product":"octop-bot","channels":{"stable":{"version":"1.0.4","assets":{}}}}""",
        )
        assertEquals(100, parsed.stable!!.rollout)
        assertNull(parsed.stable!!.android)
        assertNull(parsed.beta)
        val noSize = ManifestParser.parse(manifest(channel(android().replace("\"size\":123,", ""))))
        assertNull(noSize.stable!!.android!!.size)
    }

    @Test
    fun rejectsWrongEnvelope() {
        listOf(
            "not json",
            "[]",
            manifest(channel(), root = "\"schema\":2,\"product\":\"octop-bot\""),
            manifest(channel(), root = "\"schema\":1,\"product\":\"octop\""),
            manifest(channel(), root = "\"product\":\"octop-bot\""),
            """{"schema":1,"product":"octop-bot"}""",
        ).forEach { text -> assertThrows(text, ManifestException::class.java) { ManifestParser.parse(text) } }
    }

    @Test
    fun rejectsBadChannelFields() {
        listOf(
            """{"rollout":100,"assets":{}}""",
            """{"version":"","assets":{}}""",
            """{"version":"1.0.4","rollout":101,"assets":{}}""",
            """{"version":"1.0.4","rollout":"50","assets":{}}""",
            """{"version":"1.0.4"}""",
            """{"version":"1.0.4","assets":{"android":"x"}}""",
            "\"1.0.4\"",
        ).forEach { stable -> assertThrows(stable, ManifestException::class.java) { ManifestParser.parse(manifest(stable)) } }
    }

    @Test
    fun rejectsBadAndroidFields() {
        listOf(
            android().replace("\"version_code\":2", "\"version_code\":\"2\""),
            android().replace(",\"version_code\":2", ""),
            android().replace("\"version_code\":2", "\"version_code\":0"),
            android().replace("\"sha256\":\"$sha\",", ""),
            android().replace(sha, "abc"),
            android().replace(sha, "z".repeat(64)),
            android().replace("\"url\":\"https://dl.lynxce.cn/releases/octop-bot/1.0.4/octop-bot-0.2.0.apk\",", ""),
            android().replace("\"version\":\"0.2.0\",", ""),
            android().replace("\"size\":123", "\"size\":-1"),
            android(",\"min_version_code\":\"1\""),
        ).forEach { asset -> assertThrows(asset, ManifestException::class.java) { ManifestParser.parse(manifest(channel(asset))) } }
    }
}
