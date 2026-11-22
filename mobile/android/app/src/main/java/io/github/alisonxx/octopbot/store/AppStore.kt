package io.github.alisonxx.octopbot.store

import android.content.Context
import androidx.appcompat.app.AppCompatDelegate
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.net.Http
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "octop")

/** Credentials of a Lynxce account. Stored only encrypted. */
@Serializable
data class LynxceGrant(
    val accountId: String,
    val displayName: String? = null,
    val accessToken: String,
    val refreshToken: String,
)

/** A signed-in self-hosted server. Stored only encrypted. */
@Serializable
data class ServerSession(val baseUrl: String, val token: String, val displayName: String)

data class UserSettings(
    val readAloud: Boolean,
    val notifications: Boolean,
    val model: String?,
    val appearance: Appearance = Appearance.System,
)

enum class Appearance(val nightMode: Int) {
    System(AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM),
    Dark(AppCompatDelegate.MODE_NIGHT_YES),
    Light(AppCompatDelegate.MODE_NIGHT_NO),
}

/** The last Bot directory, shown while offline. */
@Serializable
data class DirectoryCache(val bots: List<BotProfile>, val groups: List<GroupSummary>)

/** The last reply of a Bot, shown under its name in the directory. */
@Serializable
data class BotPreview(val text: String, val at: Long)

/** App preferences in DataStore; tokens are sealed with [SecretBox] before they touch disk. */
class AppStore(context: Context, private val box: SecretBox = SecretBox()) {
    private val store = context.applicationContext.dataStore

    private object Keys {
        val lynxce = stringPreferencesKey("lynxce.grant")
        val server = stringPreferencesKey("server.session")
        val sessionBots = stringPreferencesKey("lynxce.sessionBots")
        val customBots = stringPreferencesKey("localBots.custom")
        val lookOverrides = stringPreferencesKey("localBots.looks")
        val readAloud = booleanPreferencesKey("settings.readAloud")
        val notifications = booleanPreferencesKey("settings.notifications")
        val model = stringPreferencesKey("settings.model")
        val lastBot = stringPreferencesKey("chat.lastBot")
        val previews = stringPreferencesKey("chat.previews")
        val lastServer = stringPreferencesKey("server.lastAddress")
        val appearance = stringPreferencesKey("settings.appearance")
        val directory = stringPreferencesKey("directory.cache")
    }

    private val stringMap = MapSerializer(String.serializer(), String.serializer())
    private val lookMap = MapSerializer(String.serializer(), Look.serializer())
    private val botList = ListSerializer(BotProfile.serializer())
    private val previewMap = MapSerializer(String.serializer(), BotPreview.serializer())

    val previews: Flow<Map<String, BotPreview>> = store.data.map { prefs ->
        prefs[Keys.previews]?.let { runCatching { Http.json.decodeFromString(previewMap, it) }.getOrNull() }.orEmpty()
    }

    suspend fun setPreview(botId: String, preview: BotPreview) = store.edit { prefs ->
        val map = prefs[Keys.previews]?.let { runCatching { Http.json.decodeFromString(previewMap, it) }.getOrNull() }.orEmpty()
        prefs[Keys.previews] = Http.json.encodeToString(previewMap, map + (botId to preview))
    }

    val settings: Flow<UserSettings> = store.data.map {
        UserSettings(
            readAloud = it[Keys.readAloud] ?: false,
            notifications = it[Keys.notifications] ?: true,
            model = it[Keys.model],
            appearance = Appearance.entries.firstOrNull { entry -> entry.name == it[Keys.appearance] } ?: Appearance.System,
        )
    }

    suspend fun lynxceGrant(): LynxceGrant? = sealed(Keys.lynxce)?.let { Http.json.decodeFromString(LynxceGrant.serializer(), it) }
    suspend fun setLynxceGrant(grant: LynxceGrant?) =
        seal(Keys.lynxce, grant?.let { Http.json.encodeToString(LynxceGrant.serializer(), it) })

    suspend fun serverSession(): ServerSession? =
        sealed(Keys.server)?.let { Http.json.decodeFromString(ServerSession.serializer(), it) }
    suspend fun setServerSession(session: ServerSession?) =
        seal(Keys.server, session?.let { Http.json.encodeToString(ServerSession.serializer(), it) })

    suspend fun sessionBots(): Map<String, String> = decode(Keys.sessionBots, stringMap) ?: emptyMap()
    suspend fun updateSessionBots(change: (MutableMap<String, String>) -> Unit) = store.edit { prefs ->
        val map = prefs[Keys.sessionBots]?.let { Http.json.decodeFromString(stringMap, it) }.orEmpty().toMutableMap()
        change(map)
        prefs[Keys.sessionBots] = Http.json.encodeToString(stringMap, map)
    }

    suspend fun customBots(): List<BotProfile> = decode(Keys.customBots, botList) ?: emptyList()
    suspend fun setCustomBots(bots: List<BotProfile>) = store.edit { it[Keys.customBots] = Http.json.encodeToString(botList, bots) }

    suspend fun lookOverrides(): Map<String, Look> = decode(Keys.lookOverrides, lookMap) ?: emptyMap()
    suspend fun setLookOverrides(looks: Map<String, Look>) =
        store.edit { it[Keys.lookOverrides] = Http.json.encodeToString(lookMap, looks) }

    suspend fun setReadAloud(value: Boolean) = store.edit { it[Keys.readAloud] = value }
    suspend fun setNotifications(value: Boolean) = store.edit { it[Keys.notifications] = value }
    suspend fun setAppearance(value: Appearance) = store.edit { it[Keys.appearance] = value.name }
    suspend fun setModel(value: String?) = store.edit { if (value == null) it.remove(Keys.model) else it[Keys.model] = value }

    suspend fun lastBot(): String? = store.data.first()[Keys.lastBot]
    suspend fun setLastBot(id: String) = store.edit { it[Keys.lastBot] = id }

    suspend fun directory(): DirectoryCache? = decode(Keys.directory, DirectoryCache.serializer())
    suspend fun setDirectory(cache: DirectoryCache) =
        store.edit { it[Keys.directory] = Http.json.encodeToString(DirectoryCache.serializer(), cache) }

    /** The address last typed into the server form; kept across sign-outs. */
    suspend fun lastServer(): String? = store.data.first()[Keys.lastServer]
    suspend fun setLastServer(address: String) = store.edit { it[Keys.lastServer] = address }

    /** Forget what belongs to the signed-in account: tokens and caches. Settings toggles stay. */
    suspend fun clearAccount() {
        store.edit {
            it.remove(Keys.lynxce)
            it.remove(Keys.server)
        }
        clearCaches()
    }

    /** Previews, the cached directory and per-account choices; used when switching accounts. */
    suspend fun clearCaches() = store.edit {
        it.remove(Keys.lastBot)
        it.remove(Keys.model)
        it.remove(Keys.previews)
        it.remove(Keys.directory)
    }

    private suspend fun sealed(key: Preferences.Key<String>): String? = store.data.first()[key]?.let(box::open)

    private suspend fun seal(key: Preferences.Key<String>, plain: String?) = store.edit {
        if (plain == null) it.remove(key) else it[key] = box.seal(plain)
    }

    private suspend fun <T> decode(key: Preferences.Key<String>, serializer: kotlinx.serialization.KSerializer<T>): T? =
        store.data.first()[key]?.let { runCatching { Http.json.decodeFromString(serializer, it) }.getOrNull() }
}
