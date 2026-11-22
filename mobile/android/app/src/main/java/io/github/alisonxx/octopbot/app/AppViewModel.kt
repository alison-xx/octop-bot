package io.github.alisonxx.octopbot.app

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.net.ApiException
import io.github.alisonxx.octopbot.net.ChatBackend
import io.github.alisonxx.octopbot.net.LynxceBackend
import io.github.alisonxx.octopbot.net.ServerBackend
import androidx.appcompat.app.AppCompatDelegate
import io.github.alisonxx.octopbot.store.Appearance
import io.github.alisonxx.octopbot.store.BotPreview
import io.github.alisonxx.octopbot.store.DirectoryCache
import io.github.alisonxx.octopbot.store.UserSettings
import io.github.alisonxx.octopbot.voice.Speaker
import io.github.alisonxx.octopbot.voice.VoiceInput
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.util.UUID

sealed interface SessionState {
    data object Loading : SessionState
    data class SignedOut(val notice: String? = null) : SessionState
    data class Ready(val backend: ChatBackend) : SessionState
}

/** App-wide state for the single activity: the signed-in backend, the Bot directory and every Bot's chat. */
class AppViewModel(application: Application) : AndroidViewModel(application), ChatHost {
    private val app = application as OctopApplication
    private val store = app.store
    private val resources get() = AppLocale.resources(app)

    val speaker = Speaker(application)
    val voiceInput = VoiceInput(application)

    private val _session = MutableStateFlow<SessionState>(SessionState.Loading)
    val session: StateFlow<SessionState> = _session

    private val _bots = MutableStateFlow<List<BotProfile>>(emptyList())
    val bots: StateFlow<List<BotProfile>> = _bots
    private val _groups = MutableStateFlow<List<GroupSummary>>(emptyList())
    val groups: StateFlow<List<GroupSummary>> = _groups
    private val _replying = MutableStateFlow<Set<String>>(emptySet())
    /** Bots with a reply streaming right now (their directory character works). */
    val replying: StateFlow<Set<String>> = _replying
    private val _models = MutableStateFlow<List<ModelOption>>(emptyList())
    val models: StateFlow<List<ModelOption>> = _models
    private val _balance = MutableStateFlow<String?>(null)
    val balance: StateFlow<String?> = _balance
    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing
    private val _directoryError = MutableStateFlow<String?>(null)
    /** Why the last directory refresh failed while cached Bots are shown; null when fresh. */
    val directoryError: StateFlow<String?> = _directoryError
    private val _lastBotId = MutableStateFlow<String?>(null)
    val lastBotId: StateFlow<String?> = _lastBotId

    val previews: StateFlow<Map<String, BotPreview>> =
        store.previews.stateIn(viewModelScope, SharingStarted.Eagerly, emptyMap())
    val settings: StateFlow<UserSettings> =
        store.settings.stateIn(viewModelScope, SharingStarted.Eagerly, UserSettings(readAloud = false, notifications = true, model = null))

    private val _notices = Channel<String>(Channel.BUFFERED)
    /** One-off messages for a snackbar. */
    val notices: Flow<String> = _notices.receiveAsFlow()

    private val chats = mutableMapOf<String, ChatSession>()

    override val backend: ChatBackend
        get() = (session.value as? SessionState.Ready)?.backend ?: error("Not signed in")

    init {
        viewModelScope.launch {
            val backend = store.lynxceGrant()?.let { LynxceBackend(it, store, app.localBots) }
                ?: store.serverSession()?.let { ServerBackend(it, store) }
            if (backend == null) _session.value = SessionState.SignedOut() else enter(backend)
        }
    }

    // Session

    suspend fun signInLynxce(account: String, password: String) {
        enter(LynxceBackend.signIn(account, password, store, app.localBots))
    }

    /** Called after the server form finished signing in. Replaces whatever account was active. */
    fun useServer(backend: ServerBackend) {
        viewModelScope.launch {
            (session.value as? SessionState.Ready)?.backend?.takeIf { it !== backend && it is LynxceBackend }?.let {
                it.signOut()
                store.clearCaches()
            }
            enter(backend)
        }
    }

    private suspend fun enter(backend: ChatBackend) {
        chats.clear()
        _replying.value = emptySet()
        _directoryError.value = null
        val cached = store.directory()
        _bots.value = cached?.bots.orEmpty()
        _groups.value = cached?.groups.orEmpty()
        _lastBotId.value = store.lastBot()
        _session.value = SessionState.Ready(backend)
        refreshDirectory()
        if (backend.definesBotsLocally) {
            _models.value = runCatching { backend.models() }.getOrDefault(emptyList())
            _balance.value = backend.balance()
        } else {
            _models.value = emptyList()
            _balance.value = null
        }
    }

    fun signOut(notice: String? = null) {
        val backend = (session.value as? SessionState.Ready)?.backend ?: return
        speaker.stop()
        voiceInput.cancel()
        _session.value = SessionState.SignedOut(notice)
        chats.clear()
        viewModelScope.launch {
            backend.signOut()
            store.clearAccount()
        }
    }

    // Directory

    fun refreshDirectory() {
        val backend = (session.value as? SessionState.Ready)?.backend ?: return
        viewModelScope.launch {
            _refreshing.value = true
            runCatching {
                val bots = backend.bots()
                val groups = if (backend is ServerBackend) backend.groups() else emptyList()
                _bots.value = bots
                _groups.value = groups
                _directoryError.value = null
                store.setDirectory(DirectoryCache(bots, groups))
            }.onFailure { error ->
                if (error is ApiException && error.kind == ApiException.Kind.Unauthorized) {
                    failed(error)
                } else {
                    _directoryError.value = resources.describe(error)
                }
            }
            _refreshing.value = false
        }
    }

    fun refreshBalance() {
        val backend = (session.value as? SessionState.Ready)?.backend ?: return
        viewModelScope.launch { _balance.value = backend.balance() }
    }

    override fun bot(id: String): BotProfile? = _bots.value.firstOrNull { it.id == id }

    fun chat(botId: String): ChatSession = chats.getOrPut(botId) { ChatSession(botId, viewModelScope, this) }

    fun noteBotOpened(botId: String) {
        _lastBotId.value = botId
        viewModelScope.launch { store.setLastBot(botId) }
    }

    /**
     * Create a Bot (phone-local in Lynxce mode, `POST /api/agents` on a server) or save an edit: name and
     * persona for phone-local Bots, the look for every Bot. Returns the saved Bot's id.
     */
    suspend fun saveBot(original: BotProfile?, name: String, persona: String, look: Look): String? {
        val backend = backend
        return runCatching {
            val id = when {
                original == null && backend is ServerBackend -> backend.createBot(name.trim(), persona.trim(), look)
                original == null -> BotProfile(
                    id = "bot-" + UUID.randomUUID().toString().lowercase(),
                    name = name.trim(),
                    subtitle = resources.getString(R.string.bot_custom_subtitle),
                    look = look,
                    systemPrompt = persona.trim(),
                    isLocal = true,
                ).also { app.localBots.save(it) }.id
                original.isLocal -> original.copy(name = name.trim(), systemPrompt = persona.trim(), look = look)
                    .also { app.localBots.save(it) }.id
                else -> original.id.also { backend.setLook(original, look) }
            }
            _bots.value = backend.bots()
            id
        }.onFailure(::failed).getOrNull()
    }

    /** Server mode: a group of at least two Bots. Returns true once it exists and the directory is refreshed. */
    suspend fun createGroup(name: String, members: List<BotProfile>): Boolean {
        val server = (session.value as? SessionState.Ready)?.backend as? ServerBackend ?: return false
        return runCatching { server.createGroup(name, members) }
            .onSuccess { refreshDirectory() }
            .onFailure(::failed)
            .isSuccess
    }

    fun deleteBot(bot: BotProfile) {
        if (!bot.isLocal) return
        viewModelScope.launch {
            app.localBots.delete(bot.id)
            chats.remove(bot.id)
            _bots.value = backend.bots()
        }
    }

    // Settings

    fun setAppearance(value: Appearance) {
        AppCompatDelegate.setDefaultNightMode(value.nightMode)
        viewModelScope.launch { store.setAppearance(value) }
    }

    /** Switch the in-app language; built-in Bot names follow. */
    fun setLanguage(tag: String) {
        AppLocale.set(tag)
        (session.value as? SessionState.Ready)?.backend?.let { (it as? ServerBackend)?.forgetToolLabels() }
        app.notifier.updateChannel()
        refreshDirectory()
    }

    /** Show a one-off message in the snackbar. */
    fun notice(message: String) {
        _notices.trySend(message)
    }

    fun setReadAloud(value: Boolean) = viewModelScope.launch { store.setReadAloud(value) }
    fun setNotifications(value: Boolean) = viewModelScope.launch { store.setNotifications(value) }
    fun setModel(value: String?) = viewModelScope.launch { store.setModel(value) }

    // ChatHost

    override suspend fun model(): String? = if (backend.definesBotsLocally) settings.first().model else null

    override fun replyStarted(botId: String) {
        _replying.update { it + botId }
    }

    override fun replyEnded(bot: BotProfile, text: String?) {
        _replying.update { it - bot.id }
        if (text == null) return
        val preview = text.lineSequence().map { it.trim() }.firstOrNull { it.isNotEmpty() }.orEmpty().take(200)
        viewModelScope.launch {
            store.setPreview(bot.id, BotPreview(preview, System.currentTimeMillis()))
            val settings = settings.first()
            if (settings.notifications) app.notifier.replyFinished(bot.id, bot.name, text)
            if (backend.definesBotsLocally) refreshBalance()
            // Voice mode reads its own replies.
            if (settings.readAloud && voiceBotId != bot.id && app.notifier.isInForeground) speaker.speak(text, backend)
        }
    }

    fun readAloud(text: String) {
        viewModelScope.launch { speaker.speak(text, backend) }
    }

    /** The Bot whose voice mode is open, if any. */
    var voiceBotId: String? = null

    override fun failed(error: Throwable) {
        if (error is ApiException && error.kind == ApiException.Kind.Unauthorized) {
            signOut(resources.describe(error))
            return
        }
        _notices.trySend(resources.describe(error))
    }

    override fun onCleared() {
        speaker.release()
        voiceInput.cancel()
    }
}
