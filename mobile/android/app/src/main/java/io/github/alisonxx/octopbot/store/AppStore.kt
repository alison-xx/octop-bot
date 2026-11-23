package io.github.alisonxx.octopbot.store

import android.content.Context
import androidx.appcompat.app.AppCompatDelegate
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.intPreferencesKey
import androidx.datastore.preferences.core.longPreferencesKey
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
import java.util.UUID

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
    val readAloud: Boolean = false,
    val notifications: Boolean = true,
    val model: String? = null,
    val appearance: Appearance = Appearance.System,
    val textSize: TextSize = TextSize.Standard,
    val haptics: Boolean = true,
    val expandReasoning: Boolean = false,
    val speechRate: SpeechRate = SpeechRate.Normal,
    /** Settings → About: also follow the `beta` update channel. */
    val receiveBeta: Boolean = false,
    /** Settings → Device connectors (off by default; also needs the system permission). */
    val deviceHealth: Boolean = false,
    val deviceCalendar: Boolean = false,
)

/** Chat text size, as a multiple of the body style. */
enum class TextSize(val scale: Float) { Small(0.9f), Standard(1f), Large(1.15f) }

/** Speaking speed for the backend voice and the system voice. */
enum class SpeechRate(val rate: Float) { Slow(0.85f), Normal(1f), Fast(1.2f) }

enum class Appearance(val nightMode: Int) {
    System(AppCompatDelegate.MODE_NIGHT_FOLLOW_SYSTEM),
    Dark(AppCompatDelegate.MODE_NIGHT_YES),
    Light(AppCompatDelegate.MODE_NIGHT_NO),
}

/** The last Bot directory, shown while offline. */
@Serializable
data class DirectoryCache(val bots: List<BotProfile>, val groups: List<GroupSummary>)

/** The last reply of a Bot, shown under its name in the directory; [unread] until its chat is opened. */
@Serializable
data class BotPreview(val text: String, val at: Long, val unread: Boolean = false)

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
        val textSize = stringPreferencesKey("settings.textSize")
        val haptics = booleanPreferencesKey("settings.haptics")
        val expandReasoning = booleanPreferencesKey("settings.expandReasoning")
        val speechRate = stringPreferencesKey("settings.speechRate")
        val receiveBeta = booleanPreferencesKey("settings.receiveBeta")
        val deviceHealth = booleanPreferencesKey("settings.device.health")
        val deviceCalendar = booleanPreferencesKey("settings.device.calendar")
        val installId = stringPreferencesKey("update.installId")
        val lastUpdateCheck = longPreferencesKey("update.lastCheck")
        val dismissedUpdate = intPreferencesKey("update.dismissedVersionCode")
    }

    private val stringMap = MapSerializer(String.serializer(), String.serializer())
    private val lookMap = MapSerializer(String.serializer(), Look.serializer())
    private val botList = ListSerializer(BotProfile.serializer())
    private val previewMap = MapSerializer(String.serializer(), BotPreview.serializer())

    val previews: Flow<Map<String, BotPreview>> = store.data.map { prefs ->
        prefs[Keys.previews]?.let { runCatching { Http.json.decodeFromString(previewMap, it) }.getOrNull() }.orEmpty()
    }

    /** Read-modify-write of the previews (and their unread marks) in one transaction. */
    suspend fun updatePreviews(change: (Map<String, BotPreview>) -> Map<String, BotPreview>) = store.edit { prefs ->
        val map = prefs[Keys.previews]?.let { runCatching { Http.json.decodeFromString(previewMap, it) }.getOrNull() }.orEmpty()
        val next = change(map)
        if (next != map) prefs[Keys.previews] = Http.json.encodeToString(previewMap, next)
    }

    val settings: Flow<UserSettings> = store.data.map {
        UserSettings(
            readAloud = it[Keys.readAloud] ?: false,
            notifications = it[Keys.notifications] ?: true,
            model = it[Keys.model],
            appearance = Appearance.entries.firstOrNull { entry -> entry.name == it[Keys.appearance] } ?: Appearance.System,
            textSize = TextSize.entries.firstOrNull { entry -> entry.name == it[Keys.textSize] } ?: TextSize.Standard,
            haptics = it[Keys.haptics] ?: true,
            expandReasoning = it[Keys.expandReasoning] ?: false,
            speechRate = SpeechRate.entries.firstOrNull { entry -> entry.name == it[Keys.speechRate] } ?: SpeechRate.Normal,
            receiveBeta = it[Keys.receiveBeta] ?: false,
            deviceHealth = it[Keys.deviceHealth] ?: false,
            deviceCalendar = it[Keys.deviceCalendar] ?: false,
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
    suspend fun setTextSize(value: TextSize) = store.edit { it[Keys.textSize] = value.name }
    suspend fun setHaptics(value: Boolean) = store.edit { it[Keys.haptics] = value }
    suspend fun setExpandReasoning(value: Boolean) = store.edit { it[Keys.expandReasoning] = value }
    suspend fun setSpeechRate(value: SpeechRate) = store.edit { it[Keys.speechRate] = value.name }
    suspend fun setReceiveBeta(value: Boolean) = store.edit { it[Keys.receiveBeta] = value }
    suspend fun setDeviceHealth(value: Boolean) = store.edit { it[Keys.deviceHealth] = value }
    suspend fun setDeviceCalendar(value: Boolean) = store.edit { it[Keys.deviceCalendar] = value }
    suspend fun setModel(value: String?) = store.edit { if (value == null) it.remove(Keys.model) else it[Keys.model] = value }

    suspend fun lastBot(): String? = store.data.first()[Keys.lastBot]
    suspend fun setLastBot(id: String) = store.edit { it[Keys.lastBot] = id }

    suspend fun directory(): DirectoryCache? = decode(Keys.directory, DirectoryCache.serializer())
    suspend fun setDirectory(cache: DirectoryCache) =
        store.edit { it[Keys.directory] = Http.json.encodeToString(DirectoryCache.serializer(), cache) }

    /** The address last typed into the server form; kept across sign-outs. */
    suspend fun lastServer(): String? = store.data.first()[Keys.lastServer]
    suspend fun setLastServer(address: String) = store.edit { it[Keys.lastServer] = address }

    /** A random id made once per install; keeps this install in the same staged-rollout bucket. */
    suspend fun installId(): String {
        store.data.first()[Keys.installId]?.let { return it }
        var id = ""
        store.edit { id = it[Keys.installId] ?: UUID.randomUUID().toString().also { new -> it[Keys.installId] = new } }
        return id
    }

    suspend fun lastUpdateCheck(): Long? = store.data.first()[Keys.lastUpdateCheck]
    suspend fun setLastUpdateCheck(at: Long) = store.edit { it[Keys.lastUpdateCheck] = at }

    /** The version code whose home banner was closed; that version never shows it again. */
    val dismissedUpdate: Flow<Int?> = store.data.map { it[Keys.dismissedUpdate] }
    suspend fun setDismissedUpdate(versionCode: Int) = store.edit { it[Keys.dismissedUpdate] = versionCode }

    /** Forget what belongs to the signed-in account: tokens and caches. Settings toggles stay. */
    suspend fun clearAccount() {
        store.edit {
            it.remove(Keys.lynxce)
            it.remove(Keys.server)
        }
        clearCaches()
    }

    /** Settings → Storage: reply previews and unread marks. Sign-in, the directory and the last server stay. */
    suspend fun clearPreviews() = store.edit { it.remove(Keys.previews) }

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
