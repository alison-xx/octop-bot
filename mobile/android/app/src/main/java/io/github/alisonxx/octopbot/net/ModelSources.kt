package io.github.alisonxx.octopbot.net

import android.content.Context
import android.content.SharedPreferences
import io.github.alisonxx.octopbot.store.SecretBox
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

// Where a Bot's replies come from (docs/octop-bot-cloud-plan.md §12.9): Lynxce models paid in credits, the user's own
// vendor API keys (billed by the vendor), or a model server on the user's network (Ollama, LM Studio). Signed in to
// Octop Bot cloud the keys live in the account (`/api/octop-bot/model-keys`); otherwise they stay on this phone and the
// phone calls the vendor itself.

/** A model a vendor offers. */
@Serializable
data class KeyModel(val id: String, val name: String = id) {
    val label: String get() = name.ifBlank { id }
}

/** A vendor plan the user can add their own key for (`GET /model-keys/vendors`, or the bundled copy). */
@Serializable
data class KeyVendor(
    val id: String,
    val name: String = id,
    /** Company, e.g. `tencent`, `aliyun`, `volcengine`. */
    val vendor: String = id,
    @SerialName("base_url") val baseUrl: String = "",
    @SerialName("api_key_prefix") val apiKeyPrefix: String = "",
    val docs: String? = null,
    val models: List<KeyModel> = emptyList(),
)

data class VendorCatalog(val vendors: List<KeyVendor>, val customAllowed: Boolean)

/** A company and its plans (Tencent Cloud sells TokenHub, Coding Plan, Token Plan …). */
data class VendorCompany(val id: String, val plans: List<KeyVendor>) {
    val featured: Boolean get() = id in FEATURED

    companion object {
        const val CUSTOM = "custom"
        /** Companies shown first, in this order; the rest sit behind "More vendors" (same as the dashboard). */
        val FEATURED = listOf("tencent", "aliyun", "volcengine", "deepseek", "zhipu", "kimi", "minimax", "siliconflow")
        /** The plan picked first when a company sells several. */
        val PREFERRED_PLAN = mapOf(
            "tencent" to "tencent-tokenhub", "aliyun" to "dashscope", "volcengine" to "volcengine-cn", "zhipu" to "zhipu-cn",
            "kimi" to "kimi-cn", "minimax" to "minimax-cn", "siliconflow" to "siliconflow-cn",
        )

        fun group(vendors: List<KeyVendor>): List<VendorCompany> {
            val byCompany = LinkedHashMap<String, MutableList<KeyVendor>>()
            vendors.forEach { byCompany.getOrPut(it.vendor) { mutableListOf() } += it }
            fun rank(id: String) = FEATURED.indexOf(id).let { if (it < 0) FEATURED.size else it }
            return byCompany.entries
                .map { (id, plans) -> VendorCompany(id, plans.sortedByDescending { it.id == PREFERRED_PLAN[id] }) }
                .sortedBy { rank(it.id) }
        }
    }
}

/** One of the user's own keys. The key itself never comes back, only `****` and its last four. */
data class OwnKey(
    val id: String,
    val vendor: String,
    val name: String,
    val baseUrl: String,
    val keyHint: String,
    val models: List<KeyModel>,
)

data class OwnKeyList(val keys: List<OwnKey>, val inUse: String?, val selectedModel: String?) {
    companion object {
        val Empty = OwnKeyList(emptyList(), null, null)
    }
}

/** What "Add API key" sends. */
data class NewOwnKey(val vendor: String, val apiKey: String, val name: String? = null, val baseUrl: String? = null)

/** Why the phone refused a key or an address before or after asking the vendor; the UI words it. */
class ModelSourceException(val reason: Reason, val status: Int = 0, val detail: String? = null) : IOException(detail) {
    enum class Reason { InvalidKey, Limit, BadUrl, UnknownVendor, Vendor, Unreachable, NoModels, NoModel, KeyRejected, Quota }
}

/** The user's own keys, kept by Octop Bot cloud or on this phone. */
interface ModelKeyStore {
    /** True when keys stay on this phone (not signed in to Octop Bot cloud). */
    val onPhone: Boolean
    suspend fun vendors(): VendorCatalog
    suspend fun list(): OwnKeyList
    /** Checks the key with the vendor's model list before keeping it. */
    suspend fun add(key: NewOwnKey): OwnKey
    suspend fun remove(id: String)
    /** Chat on this key's model from now on. */
    suspend fun use(id: String, model: String): OwnKeyList
}

/** An OpenAI-compatible chat endpoint the phone calls itself. */
data class ModelEndpoint(val baseUrl: String, val apiKey: String?, val model: String) {
    val completionsUrl: String get() = baseUrl.trimEnd('/') + "/chat/completions"
    val headers: Map<String, String> get() = apiKey?.let { mapOf("Authorization" to "Bearer $it") }.orEmpty()
}

/** A model server on the user's network (Ollama, LM Studio). */
@Serializable
data class LocalServer(val id: String, val name: String, @SerialName("base_url") val baseUrl: String, val models: List<KeyModel>) {
    /** "192.168.1.8:11434" for the row's second line. */
    val host: String get() = baseUrl.toHttpUrlOrNull()?.let { "${it.host}:${it.port}" } ?: baseUrl
}

/** What the phone chats on when it calls a model itself: an own key's model or a local server's. */
@Serializable
data class PhoneSelection(val source: Source, val id: String, val model: String) {
    enum class Source { Key, Local }
}

/** Pure helpers shared by both stores and the chat; unit tested. */
object ModelSourcesProtocol {
    fun catalog(text: String): List<KeyVendor> =
        runCatching { Http.json.decodeFromString(ListSerializer(KeyVendor.serializer()), text) }.getOrDefault(emptyList())

    /** `GET /model-keys/vendors` → catalog; phones show the same "get a key" pages as the bundled list. */
    fun serverCatalog(data: JsonElement, bundled: List<KeyVendor>): VendorCatalog {
        val body = data.asObject()
        val docs = bundled.associate { it.id to it.docs }
        val vendors = body?.arr("vendors")?.objects().orEmpty().mapNotNull { row ->
            runCatching { Http.json.decodeFromJsonElement(KeyVendor.serializer(), row) }.getOrNull()
                ?.let { it.copy(docs = it.docs ?: docs[it.id]) }
        }
        return VendorCatalog(vendors, body?.bool("custom_allowed") ?: false)
    }

    fun ownKey(row: JsonObject): OwnKey? {
        val id = row.str("id") ?: return null
        return OwnKey(
            id = id,
            vendor = row.str("vendor").orEmpty(),
            name = row.str("name").orEmpty(),
            baseUrl = row.str("base_url").orEmpty(),
            keyHint = row.str("key_hint") ?: "****",
            models = row.arr("models")?.objects().orEmpty().mapNotNull { m -> m.str("id")?.let { KeyModel(it, m.str("name") ?: it) } },
        )
    }

    fun ownKeys(data: JsonElement): OwnKeyList {
        val body = data.asObject() ?: return OwnKeyList.Empty
        return OwnKeyList(
            keys = body.arr("keys")?.objects().orEmpty().mapNotNull(::ownKey),
            inUse = body.str("in_use"),
            selectedModel = body.str("selected_model"),
        )
    }

    /** A custom OpenAI-compatible base: http(s), no trailing slash, no `/chat/completions`. */
    fun normalizedBase(text: String): String? {
        var value = text.trim()
        for (suffix in listOf("/chat/completions", "/")) if (value.endsWith(suffix)) value = value.dropLast(suffix.length)
        val url = value.toHttpUrlOrNull() ?: return null
        return if (url.host.isNotEmpty()) value else null
    }

    /** "192.168.1.8" → "http://192.168.1.8:11434/v1"; a typed port or `/v1` is kept. */
    fun localBase(text: String): String? {
        var value = text.trim().trimEnd('/')
        if (value.isEmpty()) return null
        val typedPort = Regex("^(?:[a-zA-Z][a-zA-Z0-9+.-]*://)?[^/:]+:\\d+").containsMatchIn(value)
        if (!value.contains("://")) value = "http://$value"
        val url = value.toHttpUrlOrNull() ?: return null
        val builder = url.newBuilder()
        if (!typedPort) builder.port(11434)
        val path = url.encodedPath.trimEnd('/')
        if (!path.endsWith("/v1")) builder.encodedPath("$path/v1")
        return builder.build().toString().trimEnd('/')
    }

    /** An OpenAI `{data:[{id}]}` or Ollama-style `{models:[{name}]}` list, without duplicates. */
    fun models(text: String): List<KeyModel> {
        val body = Http.parse(text).asObject() ?: return emptyList()
        val rows = body.arr("data")?.objects() ?: body.arr("models")?.objects() ?: return emptyList()
        return rows.mapNotNull { it.str("id") ?: it.str("name") ?: it.str("model") }.distinct().map { KeyModel(it) }
    }

    /** The request as a vendor takes it: Lynxce's own fields dropped, the endpoint's model set. */
    fun vendorBody(body: JsonObject, model: String): JsonObject = JsonObject(
        body.toMutableMap().apply {
            listOf("sessionId", "metadata", "stream_options").forEach(::remove)
            put("model", JsonPrimitive(model))
        },
    )

    /** A vendor's failure; a refused key never signs the user out and a vendor quota is not the Lynxce wallet. */
    fun vendorError(status: Int, body: String): IOException {
        val message = Http.errorMessage(body)
        return when (status) {
            401, 403 -> ModelSourceException(ModelSourceException.Reason.KeyRejected, status)
            402, 429 -> ModelSourceException(ModelSourceException.Reason.Quota, status, message)
            in 400..499 -> ApiException(ApiException.Kind.Rejected, status, message)
            else -> ApiException(ApiException.Kind.Server, status, message)
        }
    }

    /** Ollama and some vendors end with `finish_reason` and no `[DONE]`. */
    fun finishReason(data: String): String? =
        Http.parse(data).asObject()?.arr("choices")?.firstOrNull().asObject()?.str("finish_reason")

    fun keyHint(apiKey: String): String = if (apiKey.length > 8) "****" + apiKey.takeLast(4) else "****"

    /** "Ollama" on 11434, "LM Studio" on 1234, else the host. */
    fun localName(base: String): String {
        val url = base.toHttpUrlOrNull() ?: return base
        return when (url.port) {
            11434 -> "Ollama"
            1234 -> "LM Studio"
            else -> url.host
        }
    }
}

/** Octop Bot cloud: `/api/octop-bot/model-keys`. Errors come back localized by the server. */
class ServerModelKeys(private val server: ServerBackend, private val bundled: List<KeyVendor>) : ModelKeyStore {
    override val onPhone = false

    override suspend fun vendors(): VendorCatalog = ModelSourcesProtocol.serverCatalog(server.call("GET", "$BASE/vendors"), bundled)

    override suspend fun list(): OwnKeyList = ModelSourcesProtocol.ownKeys(server.call("GET", BASE))

    override suspend fun add(key: NewOwnKey): OwnKey {
        val body = buildJsonObject {
            put("vendor", key.vendor)
            put("api_key", key.apiKey)
            key.name?.takeIf { it.isNotBlank() }?.let { put("name", it) }
            key.baseUrl?.takeIf { it.isNotBlank() }?.let { put("base_url", it) }
        }
        return server.call("POST", BASE, body).asObject()?.let(ModelSourcesProtocol::ownKey) ?: throw ApiException.badResponse()
    }

    override suspend fun remove(id: String) {
        server.call("DELETE", "$BASE/${escape(id)}")
    }

    override suspend fun use(id: String, model: String): OwnKeyList =
        ModelSourcesProtocol.ownKeys(server.call("PUT", "$BASE/${escape(id)}/model", buildJsonObject { put("model_id", model) }))

    private fun escape(id: String) = java.net.URLEncoder.encode(id, "UTF-8").replace("+", "%20")

    private companion object {
        const val BASE = "/api/octop-bot/model-keys"
    }
}

/**
 * Keys and local servers kept on this phone (not signed in, or signed in to Lynxce directly). Key metadata sits in
 * shared preferences; each API key itself only sealed with the Android Keystore.
 */
class PhoneModels(context: Context, private val box: SecretBox = SecretBox("octop.model-keys")) : ModelKeyStore {
    @Serializable
    private data class StoredKey(
        val id: String,
        val vendor: String,
        val name: String,
        @SerialName("base_url") val baseUrl: String,
        val hint: String,
        val models: List<KeyModel>,
        val sealed: String,
    )

    private val prefs: SharedPreferences = context.getSharedPreferences("model-sources", Context.MODE_PRIVATE)
    val bundled: List<KeyVendor> = runCatching {
        context.assets.open("own-key-vendors.json").bufferedReader().use { ModelSourcesProtocol.catalog(it.readText()) }
    }.getOrDefault(emptyList())
    private val keyList = ListSerializer(StoredKey.serializer())
    private val localList = ListSerializer(LocalServer.serializer())
    private var stored: List<StoredKey> = decode(KEYS, keyList).orEmpty()

    private val _local = MutableStateFlow(decode(LOCAL, localList).orEmpty())
    val local: StateFlow<List<LocalServer>> = _local
    private val _selection = MutableStateFlow(decode(SELECTION, PhoneSelection.serializer()))
    /** null: Lynxce's model when signed in to Lynxce; no model at all otherwise. */
    val selection: StateFlow<PhoneSelection?> = _selection
    private val _keys = MutableStateFlow(keys())
    val ownKeys: StateFlow<List<OwnKey>> = _keys

    override val onPhone = true

    /** The app was last used without signing in. */
    var phoneOnly: Boolean
        get() = prefs.getBoolean(PHONE_ONLY, false)
        set(value) = prefs.edit().putBoolean(PHONE_ONLY, value).apply()

    private fun keys() = stored.map { OwnKey(it.id, it.vendor, it.name, it.baseUrl, it.hint, it.models) }

    /** Something to chat on without a Lynxce account. */
    val hasModel: Boolean get() = endpoint() != null

    override suspend fun vendors() = VendorCatalog(bundled, customAllowed = true)

    override suspend fun list(): OwnKeyList = snapshot()

    fun snapshot(): OwnKeyList {
        val selection = _selection.value?.takeIf { it.source == PhoneSelection.Source.Key }
        return OwnKeyList(keys(), selection?.id, selection?.model)
    }

    /** The model in use and where it runs, for the Settings row: ("deepseek-flash", "DeepSeek"). */
    fun current(companyName: (OwnKey) -> String): Pair<String, String>? {
        val selection = _selection.value ?: return null
        return when (selection.source) {
            PhoneSelection.Source.Key -> keys().firstOrNull { it.id == selection.id }?.let { selection.model to companyName(it) }
            PhoneSelection.Source.Local -> _local.value.firstOrNull { it.id == selection.id }?.let { selection.model to it.name }
        }
    }

    fun company(key: OwnKey): String =
        if (key.vendor == VendorCompany.CUSTOM) VendorCompany.CUSTOM else bundled.firstOrNull { it.id == key.vendor }?.vendor ?: key.vendor

    override suspend fun add(key: NewOwnKey): OwnKey {
        if (stored.size >= MAX_KEYS) throw ModelSourceException(ModelSourceException.Reason.Limit)
        val apiKey = key.apiKey.trim()
        val vendor = if (key.vendor == VendorCompany.CUSTOM) {
            val base = ModelSourcesProtocol.normalizedBase(key.baseUrl.orEmpty()) ?: throw ModelSourceException(ModelSourceException.Reason.BadUrl)
            val label = key.name?.trim().orEmpty().ifEmpty { base.toHttpUrlOrNull()?.host ?: base }
            KeyVendor(VendorCompany.CUSTOM, label, VendorCompany.CUSTOM, base)
        } else {
            bundled.firstOrNull { it.id == key.vendor } ?: throw ModelSourceException(ModelSourceException.Reason.UnknownVendor)
        }
        val models = listModels(vendor.baseUrl, apiKey).ifEmpty { vendor.models }
        val saved = StoredKey(
            UUID.randomUUID().toString(), vendor.id, vendor.name, vendor.baseUrl, ModelSourcesProtocol.keyHint(apiKey), models,
            box.seal(apiKey),
        )
        stored = stored + saved
        save()
        return keys().last()
    }

    override suspend fun remove(id: String) {
        stored = stored.filterNot { it.id == id }
        _selection.value?.takeIf { it.source == PhoneSelection.Source.Key && it.id == id }?.let { setSelection(null) }
        save()
    }

    override suspend fun use(id: String, model: String): OwnKeyList {
        if (stored.none { it.id == id }) throw ApiException(ApiException.Kind.Rejected, 404)
        setSelection(PhoneSelection(PhoneSelection.Source.Key, id, model))
        return snapshot()
    }

    /** Back to Lynxce's models (signed in to Lynxce), or no model. */
    fun useLynxce() = setSelection(null)

    fun useLocal(id: String, model: String) = setSelection(PhoneSelection(PhoneSelection.Source.Local, id, model))

    /** Find the models of an Ollama / LM Studio server at this address and keep it. */
    suspend fun addLocal(address: String): LocalServer {
        val base = ModelSourcesProtocol.localBase(address) ?: throw ModelSourceException(ModelSourceException.Reason.BadUrl)
        val models = try {
            listModels(base, null, timeoutSeconds = 8)
        } catch (error: ApiException) {
            if (error.kind == ApiException.Kind.Network) throw ModelSourceException(ModelSourceException.Reason.Unreachable)
            throw error
        }
        if (models.isEmpty()) throw ModelSourceException(ModelSourceException.Reason.NoModels)
        val server = LocalServer(UUID.randomUUID().toString(), ModelSourcesProtocol.localName(base), base, models)
        _local.value = _local.value.filterNot { it.baseUrl == base } + server
        save()
        return server
    }

    fun removeLocal(id: String) {
        _local.value = _local.value.filterNot { it.id == id }
        _selection.value?.takeIf { it.source == PhoneSelection.Source.Local && it.id == id }?.let { setSelection(null) }
        save()
    }

    /** Where the phone sends a chat when it calls the model itself; null means Lynxce (or nothing). */
    fun endpoint(): ModelEndpoint? {
        val selection = _selection.value ?: return null
        return when (selection.source) {
            PhoneSelection.Source.Key -> stored.firstOrNull { it.id == selection.id }?.let { key ->
                box.open(key.sealed)?.let { ModelEndpoint(key.baseUrl, it, selection.model) }
            }
            PhoneSelection.Source.Local -> _local.value.firstOrNull { it.id == selection.id }?.let { ModelEndpoint(it.baseUrl, null, selection.model) }
        }
    }

    private fun setSelection(next: PhoneSelection?) {
        _selection.value = next
        prefs.edit().apply {
            if (next == null) remove(SELECTION) else putString(SELECTION, Http.json.encodeToString(PhoneSelection.serializer(), next))
        }.apply()
        _keys.value = keys()
    }

    private fun save() {
        prefs.edit()
            .putString(KEYS, Http.json.encodeToString(keyList, stored))
            .putString(LOCAL, Http.json.encodeToString(localList, _local.value))
            .apply()
        _keys.value = keys()
    }

    private fun <T> decode(key: String, serializer: kotlinx.serialization.KSerializer<T>): T? =
        prefs.getString(key, null)?.let { runCatching { Http.json.decodeFromString(serializer, it) }.getOrNull() }

    /** `GET {base}/models`. A vendor that refuses the key (401/403) means the key is wrong. */
    private suspend fun listModels(base: String, apiKey: String?, timeoutSeconds: Long = 20): List<KeyModel> {
        val client = Http.client.newBuilder().callTimeout(timeoutSeconds, TimeUnit.SECONDS).build()
        val headers = apiKey?.let { mapOf("Authorization" to "Bearer $it") }.orEmpty()
        val request = Http.request(base.trimEnd('/') + "/models", headers).get().build()
        return client.newCall(request).await().use { response ->
            val text = withContext(Dispatchers.IO) { response.body.string() }
            when (response.code) {
                in 200..299 -> ModelSourcesProtocol.models(text)
                401, 403 -> throw ModelSourceException(ModelSourceException.Reason.InvalidKey, response.code)
                // Some vendors have no model list; the catalog's suggestions stand in.
                404, 405 -> emptyList()
                else -> throw ModelSourceException(ModelSourceException.Reason.Vendor, response.code)
            }
        }
    }

    private companion object {
        const val MAX_KEYS = 20
        const val KEYS = "keys"
        const val LOCAL = "local"
        const val SELECTION = "selection"
        const val PHONE_ONLY = "phone_only"
    }
}
