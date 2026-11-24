package io.github.alisonxx.octopbot.net

import io.github.alisonxx.octopbot.model.MessageRole
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.file.Files

class ModelSourcesTest {
    private val bundled: List<KeyVendor> = ModelSourcesProtocol.catalog(File("src/main/assets/own-key-vendors.json").readText())

    @Test
    fun bundledCatalogGroupsCompaniesFeaturedFirst() {
        assertTrue(bundled.isNotEmpty())
        // Phones call vendors themselves over the OpenAI-compatible protocol only.
        assertFalse(bundled.any { it.id == "anthropic" })
        assertTrue(bundled.all { it.baseUrl.startsWith("https://") })
        val companies = VendorCompany.group(bundled)
        assertEquals(VendorCompany.FEATURED, companies.take(8).map { it.id })
        assertEquals("tencent-tokenhub", companies.first { it.id == "tencent" }.plans.first().id)
        assertEquals("dashscope", companies.first { it.id == "aliyun" }.plans.first().id)
    }

    @Test
    fun groupKeepsCatalogOrderAfterFeatured() {
        val companies = VendorCompany.group(
            listOf(
                KeyVendor("x-1", "X", "xco", "https://x"),
                KeyVendor("kimi-intl", "Kimi intl", "kimi", "https://k2"),
                KeyVendor("kimi-cn", "Kimi", "kimi", "https://k1"),
                KeyVendor("y-1", "Y", "yco", "https://y"),
            ),
        )
        assertEquals(listOf("kimi", "xco", "yco"), companies.map { it.id })
        assertEquals(listOf("kimi-cn", "kimi-intl"), companies[0].plans.map { it.id })
    }

    @Test
    fun serverShapesParse() {
        val list = ModelSourcesProtocol.ownKeys(
            Http.parse(
                """{"keys":[{"id":"k1","vendor":"deepseek","name":"DeepSeek","base_url":"https://api.deepseek.com/v1",
                "key_hint":"****7f3a","models":[{"id":"deepseek-flash","name":"DeepSeek Flash"}],"created_at":1.0}],
                "in_use":"k1","selected_model":"deepseek-flash"}""",
            ),
        )
        assertEquals("****7f3a", list.keys.single().keyHint)
        assertEquals("DeepSeek Flash", list.keys.single().models.single().label)
        assertEquals("k1", list.inUse)
        assertEquals("deepseek-flash", list.selectedModel)
        assertEquals(OwnKeyList.Empty, ModelSourcesProtocol.ownKeys(Http.parse("""{"keys":[],"in_use":null}""")))

        val catalog = ModelSourcesProtocol.serverCatalog(
            Http.parse(
                """{"vendors":[{"id":"deepseek","name":"DeepSeek","vendor":"deepseek","logo_id":"deepseek",
                "base_url":"https://api.deepseek.com/v1","protocol":"openai","api_key_prefix":"sk-","models":[]}],"custom_allowed":false}""",
            ),
            bundled,
        )
        assertFalse(catalog.customAllowed)
        assertEquals("sk-", catalog.vendors.single().apiKeyPrefix)
        assertEquals("https://platform.deepseek.com/api_keys", catalog.vendors.single().docs)
    }

    @Test
    fun localAddressesAndCustomBases() {
        assertEquals("http://192.168.1.8:11434/v1", ModelSourcesProtocol.localBase("192.168.1.8"))
        assertEquals("http://192.168.1.8:1234/v1", ModelSourcesProtocol.localBase(" 192.168.1.8:1234/ "))
        assertEquals("http://mac.local:11434/v1", ModelSourcesProtocol.localBase("http://mac.local:11434/v1"))
        assertNull(ModelSourcesProtocol.localBase("  "))
        assertEquals("https://api.example.com/v1", ModelSourcesProtocol.normalizedBase("https://api.example.com/v1/chat/completions"))
        assertEquals("https://api.example.com/v1", ModelSourcesProtocol.normalizedBase("https://api.example.com/v1/"))
        assertNull(ModelSourcesProtocol.normalizedBase("ftp://x"))
        assertNull(ModelSourcesProtocol.normalizedBase("not a url"))
        assertEquals("Ollama", ModelSourcesProtocol.localName("http://10.0.2.2:11434/v1"))
        assertEquals("LM Studio", ModelSourcesProtocol.localName("http://10.0.2.2:1234/v1"))
        assertEquals("****7f3a", ModelSourcesProtocol.keyHint("sk-12345677f3a"))
        assertEquals("****", ModelSourcesProtocol.keyHint("short"))
    }

    @Test
    fun modelListsFromVendorsAndOllama() {
        assertEquals(listOf("a", "b"), ModelSourcesProtocol.models("""{"object":"list","data":[{"id":"a"},{"id":"b"},{"id":"a"}]}""").map { it.id })
        assertEquals(listOf("qwen3:14b"), ModelSourcesProtocol.models("""{"models":[{"name":"qwen3:14b"}]}""").map { it.id })
        assertTrue(ModelSourcesProtocol.models("nope").isEmpty())
    }

    @Test
    fun vendorBodyDropsLynxceFields() {
        val body = buildJsonObject {
            put("stream", true)
            put("sessionId", "s")
            putJsonObject("metadata") { put("client", "octop-bot-android") }
            putJsonObject("stream_options") { put("include_usage", true) }
            put("model", "tencent/auto")
        }
        val vendor = ModelSourcesProtocol.vendorBody(body, "deepseek-flash")
        assertEquals(JsonPrimitive("deepseek-flash"), vendor["model"])
        assertNull(vendor["sessionId"])
        assertNull(vendor["metadata"])
        assertNull(vendor["stream_options"])
        assertEquals(JsonPrimitive(true), vendor["stream"])
    }

    @Test
    fun vendorErrorsNeverSignOutOrAskForCredits() {
        val refused = ModelSourcesProtocol.vendorError(401, "") as ModelSourceException
        assertEquals(ModelSourceException.Reason.KeyRejected, refused.reason)
        val quota = ModelSourcesProtocol.vendorError(402, """{"error":{"message":"Insufficient Balance"}}""") as ModelSourceException
        assertEquals(ModelSourceException.Reason.Quota, quota.reason)
        assertEquals("Insufficient Balance", quota.detail)
        assertEquals(ApiException.Kind.Server, (ModelSourcesProtocol.vendorError(500, "") as ApiException).kind)
        assertEquals("stop", ModelSourcesProtocol.finishReason("""{"choices":[{"delta":{},"finish_reason":"stop"}]}"""))
        assertNull(ModelSourcesProtocol.finishReason("""{"choices":[{"delta":{"content":"x"}}]}"""))
        val endpoint = ModelEndpoint("http://10.0.2.2:11434/v1/", null, "qwen3:14b")
        assertEquals("http://10.0.2.2:11434/v1/chat/completions", endpoint.completionsUrl)
        assertTrue(endpoint.headers.isEmpty())
        assertEquals("Bearer k", ModelEndpoint("https://x/v1", "k", "m").headers["Authorization"])
    }

    @Test
    fun deviceConversationsKeepTurnsPerBot() {
        val file = Files.createTempDirectory("device-conv").resolve("c.json").toFile()
        val store = DeviceConversations(file)
        store.create("c1", "chief", "  第一行\n第二行")
        store.append("c1", "第一行\n第二行", 1L, "好的", "想一下")
        store.create("c2", "writer", "draft")
        assertEquals(listOf("第一行"), store.conversations("chief").map { it.title })
        val reloaded = DeviceConversations(file)
        val messages = reloaded.messages("c1")
        assertEquals(listOf(MessageRole.User, MessageRole.Assistant), messages.map { it.role })
        assertEquals("想一下", messages.last().thinking)
        reloaded.delete("c1")
        assertTrue(reloaded.conversations("chief").isEmpty())
        assertEquals(1, reloaded.conversations("writer").size)
        assertTrue(Http.parse(file.readText()).toString().contains("writer"))
    }
}
