package io.github.alisonxx.octopbot.net

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * GitHub star counts for the About section, cached like the website: the last
 * number shows at once, a fresh one is fetched at most every 6 hours, and a
 * built-in number covers the first launch and offline use.
 */
object GitHubStars {
    data class Repo(val name: String, val path: String, val fallback: Int) {
        val url: String get() = "https://github.com/$path"
    }

    val bot = Repo("Octop Bot", "alison-xx/octop-bot", 6)
    val octop = Repo("Octop", "TencentCloud/Octop", 12_400)

    private const val MAX_AGE_MS = 6 * 3600 * 1000L
    private val client by lazy {
        Http.client.newBuilder().callTimeout(5, TimeUnit.SECONDS).build()
    }

    /** `1234` → "1.23k", `12400` → "12.4k", like the website. */
    fun format(n: Int): String {
        if (n < 1000) return n.toString()
        var text = String.format(java.util.Locale.US, if (n >= 10_000) "%.1f" else "%.2f", n / 1000.0)
        text = text.trimEnd('0').trimEnd('.')
        return text + "k"
    }

    fun cached(context: Context, repo: Repo): Int {
        val prefs = context.getSharedPreferences("github_stars", Context.MODE_PRIVATE)
        return prefs.getInt(repo.path, repo.fallback)
    }

    /** A fresh count when the cached one is older than 6 hours; `null` when nothing changed or offline. */
    suspend fun refresh(context: Context, repo: Repo): Int? = withContext(Dispatchers.IO) {
        val prefs = context.getSharedPreferences("github_stars", Context.MODE_PRIVATE)
        val at = prefs.getLong("${repo.path}.at", 0L)
        if (System.currentTimeMillis() - at < MAX_AGE_MS) return@withContext null
        val request = Request.Builder()
            .url("https://api.github.com/repos/${repo.path}")
            .header("Accept", "application/vnd.github+json")
            .build()
        runCatching {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@use null
                val body = response.body.string()
                Http.json.parseToJsonElement(body).jsonObject["stargazers_count"]?.jsonPrimitive?.int
            }
        }.getOrNull()?.also { count ->
            prefs.edit().putInt(repo.path, count).putLong("${repo.path}.at", System.currentTimeMillis()).apply()
        }
    }
}
