package io.github.alisonxx.octopbot.net

import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/** A user-facing failure from Lynxce or an Octop server. [message] is null when the UI should use generic text. */
class ApiException(val kind: Kind, val status: Int, message: String? = null) : IOException(message) {
    enum class Kind { Unauthorized, Credits, Rejected, Network, Server }

    companion object {
        fun from(status: Int, message: String?): ApiException = when (status) {
            401 -> ApiException(Kind.Unauthorized, status, message)
            402 -> ApiException(Kind.Credits, status, message)
            in 400..499 -> ApiException(Kind.Rejected, status, message)
            else -> ApiException(Kind.Server, status, message)
        }

        fun network() = ApiException(Kind.Network, 0)
        fun badResponse() = ApiException(Kind.Server, 502)
    }
}

/** One multipart form part, in the order the server reads them. */
sealed interface FormPart {
    val name: String

    data class Field(override val name: String, val value: String) : FormPart
    class File(override val name: String, val bytes: ByteArray, val filename: String, val mimeType: String) : FormPart
}

object Http {
    val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(20, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    /** The app's language; the app points this at its in-app language setting. */
    @Volatile var locale: () -> Locale = { Locale.getDefault() }

    fun languageTag(): String = locale().toLanguageTag()

    fun isChinese(): Boolean = locale().language == "zh"

    fun body(json: JsonElement): RequestBody = json.toString().toRequestBody(jsonType)

    fun form(parts: List<FormPart>): RequestBody = MultipartBody.Builder().setType(MultipartBody.FORM).apply {
        for (part in parts) when (part) {
            is FormPart.Field -> addFormDataPart(part.name, part.value)
            is FormPart.File -> addFormDataPart(part.name, part.filename, part.bytes.toRequestBody(part.mimeType.toMediaType()))
        }
    }.build()

    fun request(url: String, headers: Map<String, String> = emptyMap()): Request.Builder =
        Request.Builder().url(url).apply {
            header("Accept", "application/json")
            header("Accept-Language", languageTag())
            headers.forEach { (key, value) -> header(key, value) }
        }

    /** Pull a human message out of either envelope: Lynxce `{code,message}` or Octop `{error:{message}}`. */
    fun errorMessage(text: String): String? {
        val obj = runCatching { json.parseToJsonElement(text) }.getOrNull() as? JsonObject ?: return null
        return when (val error = obj["error"]) {
            is JsonObject -> error.str("message")
            is JsonPrimitive -> error.contentOrNull
            else -> obj.str("detail") ?: obj.str("message")
        }
    }

    fun parse(text: String): JsonElement =
        if (text.isBlank()) JsonNull else runCatching { json.parseToJsonElement(text) }.getOrDefault(JsonNull)
}

/** Await an OkHttp call; cancelling the coroutine cancels the call. Transport failures become [ApiException]. */
suspend fun Call.await(): Response = suspendCancellableCoroutine { continuation ->
    continuation.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onResponse(call: Call, response: Response) = continuation.resume(response)
        override fun onFailure(call: Call, e: IOException) {
            if (!continuation.isCancelled) continuation.resumeWithException(ApiException.network())
        }
    })
}

/** Run a client call with a custom read timeout (long-running group posts, uploads). */
fun OkHttpClient.withReadTimeout(seconds: Long): OkHttpClient =
    newBuilder().readTimeout(seconds, TimeUnit.SECONDS).build()

// Small helpers for walking loosely typed JSON.

fun JsonElement?.asObject(): JsonObject? = this as? JsonObject
fun JsonElement?.asArray(): JsonArray? = this as? JsonArray
fun JsonElement?.asString(): String? = (this as? JsonPrimitive)?.takeIf { it.isString }?.content

fun JsonObject.str(key: String): String? = this[key].asString()
fun JsonObject.obj(key: String): JsonObject? = this[key].asObject()
fun JsonObject.arr(key: String): JsonArray? = this[key].asArray()
fun JsonObject.bool(key: String): Boolean? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.booleanOrNull
fun JsonObject.double(key: String): Double? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.doubleOrNull
fun JsonObject.long(key: String): Long? = (this[key] as? JsonPrimitive)?.takeIf { !it.isString }?.longOrNull

/** Either a JSON string or a JSON number, as text (ids that may be numeric). */
fun JsonObject.idString(key: String): String? =
    (this[key] as? JsonPrimitive)?.takeIf { it !is JsonNull }?.content

fun JsonArray.objects(): List<JsonObject> = mapNotNull { it as? JsonObject }
