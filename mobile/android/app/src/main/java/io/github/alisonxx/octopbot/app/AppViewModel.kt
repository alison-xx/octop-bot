package io.github.alisonxx.octopbot.app

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.HitlTexts
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.net.ApiException
import io.github.alisonxx.octopbot.net.ChatBackend
import io.github.alisonxx.octopbot.net.CreditAccount
import io.github.alisonxx.octopbot.net.LynxceBackend
import io.github.alisonxx.octopbot.net.LynxceProtocol
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.net.ServerProtocol
import androidx.appcompat.app.AppCompatDelegate
import io.github.alisonxx.octopbot.store.Appearance
import io.github.alisonxx.octopbot.store.BotPreview
import io.github.alisonxx.octopbot.store.DirectoryCache
import io.github.alisonxx.octopbot.store.Previews
import io.github.alisonxx.octopbot.store.SpeechRate
import io.github.alisonxx.octopbot.store.TextSize
import io.github.alisonxx.octopbot.store.UserSettings
import io.github.alisonxx.octopbot.update.UpdateState
import io.github.alisonxx.octopbot.voice.Speaker
import io.github.alisonxx.octopbot.voice.VoiceInput
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
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
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID

sealed interface SessionState {
    data object Loading : SessionState
    /** [reopenServer]: "Switch account or server" from a server; the server form opens with its address. */
    data class SignedOut(val notice: String? = null, val reopenServer: Boolean = false) : SessionState
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
    private val _launchReady = MutableStateFlow(false)
    /** The launch screen can give way: signed out, or the first directory refresh after sign-in finished. */
    val launchReady: StateFlow<Boolean> = _launchReady
    private val _lastBotId = MutableStateFlow<String?>(null)
    val lastBotId: StateFlow<String?> = _lastBotId

    val previews: StateFlow<Map<String, BotPreview>> =
        store.previews.stateIn(viewModelScope, SharingStarted.Eagerly, emptyMap())
    val settings: StateFlow<UserSettings> =
        store.settings.stateIn(viewModelScope, SharingStarted.Eagerly, UserSettings())

    /** In-app updates: the offer and its check/download status. */
    val update: StateFlow<UpdateState> = app.updater.state
    /** The version code whose home banner was closed. */
    val dismissedUpdate: StateFlow<Int?> = store.dismissedUpdate.stateIn(viewModelScope, SharingStarted.Eagerly, null)
    /** Verified APKs to hand to the system installer. */
    val updateInstalls: Flow<File> = app.updater.installs

    private val _speakingMessage = MutableStateFlow<String?>(null)
    /** The message being read aloud, so its read-aloud button turns into stop. */
    val speakingMessage: StateFlow<String?> = _speakingMessage
    private var readJob: Job? = null

    /** The Bot whose chat is on screen (resumed), if any; replies finishing elsewhere are marked unread. */
    private var chatOnScreen: String? = null

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
            if (backend == null) {
                _session.value = SessionState.SignedOut()
                _launchReady.value = true
            } else {
                enter(backend)
            }
        }
        viewModelScope.launch { settings.collect { speaker.rate = it.speechRate.rate } }
    }

    // Session

    /** Octop Bot cloud answered: Lynxce sign-in lands there. Until it is up, it goes to Lynxce directly. */
    private var cloudAvailable: Boolean? = null

    private suspend fun useCloud(): Boolean =
        cloudAvailable ?: ServerBackend.lynxceCloudAvailable().also { cloudAvailable = it }

    suspend fun signInLynxce(account: String, password: String) {
        if (useCloud()) {
            enter(ServerBackend.signInWithLynxce(ServerProtocol.LYNXCE_CLOUD, account, password, store))
        } else {
            enter(LynxceBackend.signIn(account, password, store, app.localBots))
        }
    }

    suspend fun requestLynxceCode(target: LynxceProtocol.Target) {
        if (useCloud()) {
            ServerBackend.requestLynxceCode(ServerProtocol.LYNXCE_CLOUD, target.value)
        } else {
            LynxceBackend.requestCode(target)
        }
    }

    suspend fun signInLynxceCode(target: LynxceProtocol.Target, code: String) {
        if (useCloud()) {
            enter(ServerBackend.signInWithLynxceCode(ServerProtocol.LYNXCE_CLOUD, target.value, code, store))
        } else {
            enter(LynxceBackend.signIn(target, code, store, app.localBots))
        }
    }

    /** Signed in to a server (self-hosted or Octop Bot cloud). */
    val server: ServerBackend?
        get() = (session.value as? SessionState.Ready)?.backend as? ServerBackend

    /** Signed in to Octop Bot cloud. */
    val cloudServer: ServerBackend?
        get() = ((session.value as? SessionState.Ready)?.backend as? ServerBackend)?.takeIf { it.isCloud }

    /** The Lynxce wallet: direct with Lynxce, or kept by Octop Bot cloud. */
    val creditAccount: CreditAccount?
        get() = when (val backend = (session.value as? SessionState.Ready)?.backend) {
            is LynxceBackend -> backend
            is ServerBackend -> backend.takeIf { it.isCloud }
            else -> null
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
        _models.value = if (backend.definesBotsLocally) runCatching { backend.models() }.getOrDefault(emptyList()) else emptyList()
        _balance.value = creditAccount?.balance()
    }

    fun signOut(notice: String? = null, reopenServer: Boolean = false) {
        val backend = (session.value as? SessionState.Ready)?.backend ?: return
        stopReading()
        voiceInput.cancel()
        chats.clear()
        val reopen = reopenServer && backend is ServerBackend
        if (!reopen) _session.value = SessionState.SignedOut(notice)
        viewModelScope.launch {
            if (reopen) {
                // "Switch account or server": the server form opens with this server's full address.
                store.setLastServer(backend.baseUrl)
                _session.value = SessionState.SignedOut(notice, reopenServer = true)
            }
            backend.signOut()
            store.clearAccount()
        }
    }

    /** Sign out and return to the first screen; from a server, straight to the server form. */
    fun switchAccount() {
        signOut(reopenServer = (session.value as? SessionState.Ready)?.backend is ServerBackend)
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
            _launchReady.value = true
        }
    }

    fun refreshBalance() {
        val backend = (session.value as? SessionState.Ready)?.backend ?: return
        viewModelScope.launch { _balance.value = backend.balance() }
    }

    /** A file a Bot linked to: Octop Bot cloud hands out a short-lived object-store link. */
    fun openWorkspaceFile(uri: String, open: (String) -> Unit) {
        val server = (session.value as? SessionState.Ready)?.backend as? ServerBackend
        if (server == null || !server.isCloud) {
            notice(resources.getString(R.string.file_open_unsupported))
            return
        }
        viewModelScope.launch {
            runCatching { server.downloadLink(uri) }
                .onSuccess(open)
                .onFailure { notice(resources.describe(it)) }
        }
    }

    /** Open Lynxce's recharge page signed in as this account (a 15-minute ticket, as on the desktop). */
    fun recharge(open: (String) -> Unit) {
        val account = creditAccount ?: return
        viewModelScope.launch {
            runCatching { account.checkoutUrl() }
                .onSuccess(open)
                .onFailure { notice(resources.describe(it)) }
        }
    }

    /** Settings → Delete account: Lynxce starts its cooling-off period, then this phone signs out. */
    fun deleteAccount() {
        val account = creditAccount ?: return
        viewModelScope.launch {
            runCatching { account.requestDeletion() }
                .onSuccess {
                    store.setCustomBots(emptyList())
                    signOut(notice = resources.getString(R.string.settings_delete_account_done))
                }
                .onFailure { notice(resources.describe(it)) }
        }
    }

    override fun bot(id: String): BotProfile? = _bots.value.firstOrNull { it.id == id }

    fun chat(botId: String): ChatSession = chats.getOrPut(botId) { ChatSession(botId, viewModelScope, this) }

    fun noteBotOpened(botId: String) {
        _lastBotId.value = botId
        viewModelScope.launch { store.setLastBot(botId) }
    }

    /** The chat screen of [botId] is resumed (or not); opening it clears its unread mark. */
    fun chatOnScreen(botId: String, visible: Boolean) {
        if (visible) {
            chatOnScreen = botId
            viewModelScope.launch { store.updatePreviews { Previews.markRead(it, botId) } }
        } else if (chatOnScreen == botId) {
            chatOnScreen = null
        }
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
    fun setTextSize(value: TextSize) = viewModelScope.launch { store.setTextSize(value) }
    fun setHaptics(value: Boolean) = viewModelScope.launch { store.setHaptics(value) }
    fun setExpandReasoning(value: Boolean) = viewModelScope.launch { store.setExpandReasoning(value) }
    fun setSpeechRate(value: SpeechRate) = viewModelScope.launch { store.setSpeechRate(value) }

    /** Settings → Storage: previews, unread marks, and temporary voice and image files. Sign-in stays. */
    fun clearLocalCache(done: String) {
        viewModelScope.launch {
            stopReading()
            store.clearPreviews()
            withContext(Dispatchers.IO) { app.cacheDir.listFiles()?.forEach { it.deleteRecursively() } }
            notice(done)
        }
    }
    fun setNotifications(value: Boolean) = viewModelScope.launch { store.setNotifications(value) }

    // Updates

    /** Settings → About → Check for updates; only this check reports a failure. */
    fun checkForUpdates() {
        viewModelScope.launch {
            if (!app.updater.check(manual = true)) notice(resources.getString(R.string.update_check_failed))
        }
    }

    fun startUpdate() = app.updater.update()
    fun cancelUpdateDownload() = app.updater.cancelDownload()
    fun dismissUpdate(versionCode: Int) = viewModelScope.launch { store.setDismissedUpdate(versionCode) }

    /** Turning the beta channel on or off re-evaluates the manifest right away. */
    fun setReceiveBeta(value: Boolean) = viewModelScope.launch {
        store.setReceiveBeta(value)
        app.updater.check(manual = false)
    }
    fun setModel(value: String?) = viewModelScope.launch { store.setModel(value) }

    // ChatHost

    override suspend fun model(): String? = if (backend.definesBotsLocally) settings.first().model else null

    override fun replyStarted(botId: String) {
        _replying.update { it + botId }
    }

    override fun replyEnded(bot: BotProfile, messageId: String, text: String?) {
        _replying.update { it - bot.id }
        if (text == null) return
        val onScreen = chatOnScreen == bot.id
        viewModelScope.launch {
            store.updatePreviews { Previews.replyFinished(it, bot.id, text, System.currentTimeMillis(), onScreen) }
            val settings = settings.first()
            if (settings.notifications) app.notifier.replyFinished(bot.id, bot.name, text)
            if (creditAccount != null) refreshBalance()
            // Voice mode reads its own replies.
            if (settings.readAloud && voiceBotId != bot.id && app.notifier.isInForeground) readAloud(messageId, text)
        }
    }

    /** Read one message aloud; any other reading stops first. */
    fun readAloud(messageId: String, text: String) {
        readJob?.cancel()
        _speakingMessage.value = messageId
        readJob = viewModelScope.launch {
            try {
                speaker.speak(text, backend)
            } finally {
                if (_speakingMessage.value == messageId) _speakingMessage.value = null
            }
        }
    }

    fun stopReading() {
        readJob?.cancel()
        readJob = null
        speaker.stop()
        _speakingMessage.value = null
    }

    /** The Bot whose voice mode is open, if any. */
    var voiceBotId: String? = null

    override val hitlTexts: HitlTexts
        get() = resources.let { res ->
            HitlTexts(
                youDecide = res.getString(R.string.hitl_reply_you_decide),
                closed = res.getString(R.string.hitl_reply_closed),
                approved = { res.getString(R.string.hitl_note_approved, it) },
                declined = { res.getString(R.string.hitl_note_declined, it) },
            )
        }

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
