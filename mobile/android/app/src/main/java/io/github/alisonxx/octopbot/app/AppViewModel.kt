package io.github.alisonxx.octopbot.app

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.device.DeviceConnectors
import io.github.alisonxx.octopbot.model.BotProfile
import io.github.alisonxx.octopbot.model.shouldPollBots
import io.github.alisonxx.octopbot.model.FileAttachment
import io.github.alisonxx.octopbot.model.FileCards
import io.github.alisonxx.octopbot.model.GroupSummary
import io.github.alisonxx.octopbot.model.HitlTexts
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.ModelOption
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ProcessLifecycleOwner
import io.github.alisonxx.octopbot.net.ApiException
import io.github.alisonxx.octopbot.net.AccountPhoto
import io.github.alisonxx.octopbot.net.ChatBackend
import io.github.alisonxx.octopbot.net.CheckoutRefused
import io.github.alisonxx.octopbot.net.CreditAccount
import io.github.alisonxx.octopbot.net.DeviceBackend
import io.github.alisonxx.octopbot.net.ModelKeyStore
import io.github.alisonxx.octopbot.net.OwnKeyList
import io.github.alisonxx.octopbot.net.PhoneModels
import io.github.alisonxx.octopbot.net.ServerModelKeys
import io.github.alisonxx.octopbot.net.LynxceBackend
import io.github.alisonxx.octopbot.net.LynxceProtocol
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.net.ServerProtocol
import androidx.appcompat.app.AppCompatDelegate
import io.github.alisonxx.octopbot.store.Appearance
import io.github.alisonxx.octopbot.store.BotPreview
import io.github.alisonxx.octopbot.store.DirectoryCache
import io.github.alisonxx.octopbot.store.Previews
import io.github.alisonxx.octopbot.store.SavedBackend
import io.github.alisonxx.octopbot.store.SpeechRate
import io.github.alisonxx.octopbot.store.TextSize
import io.github.alisonxx.octopbot.store.UserSettings
import io.github.alisonxx.octopbot.update.UpdateState
import io.github.alisonxx.octopbot.voice.Speaker
import io.github.alisonxx.octopbot.voice.VoiceInput
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelChildren
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
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

/** The Lynxce wallet balance as the UI shows it. */
sealed interface BalanceState {
    data object Loading : BalanceState
    /** Couldn't read it: the UI shows "—" and a retry. */
    data object Failed : BalanceState
    data class Value(val credits: Double) : BalanceState {
        val low: Boolean get() = credits < LynxceProtocol.LOW_BALANCE
    }
}

/** Token use over the last 30 days on an Octop server (Settings → Credits). */
data class UsageState(
    val loading: Boolean = true,
    val failed: Boolean = false,
    val byBot: ServerProtocol.UsageSummary? = null,
    val byModel: ServerProtocol.UsageSummary? = null,
)

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
    private val _accountPhoto = MutableStateFlow<AccountPhoto?>(null)
    val accountPhoto: StateFlow<AccountPhoto?> = _accountPhoto
    private var photoJob: Job? = null
    private val _balance = MutableStateFlow<BalanceState?>(null)
    /** null when the account has no Lynxce wallet (a self-hosted server). */
    val balance: StateFlow<BalanceState?> = _balance
    private var balanceJob: Job? = null
    private val _walletKey = MutableStateFlow<String?>(null)
    /** The low balance the chat banner warns about, or null (enough credits, or the banner was closed). */
    val lowBalance: StateFlow<Double?> =
        combine(_balance, _walletKey, store.lowBalanceDismissed) { balance, wallet, dismissed ->
            (balance as? BalanceState.Value)?.takeIf { it.low && wallet != null && !lowBalanceIsDismissed(dismissed[wallet], System.currentTimeMillis()) }?.credits
        }.stateIn(viewModelScope, SharingStarted.Eagerly, null)
    private val _usage = MutableStateFlow<UsageState?>(null)
    /** Usage on an Octop server; null in direct-Lynxce mode, which has no Octop server to ask. */
    val usage: StateFlow<UsageState?> = _usage
    private val _creditsRefreshing = MutableStateFlow(false)
    val creditsRefreshing: StateFlow<Boolean> = _creditsRefreshing
    private val _recharging = MutableStateFlow(false)
    /** A recharge link is being fetched; the button ignores further taps. */
    val recharging: StateFlow<Boolean> = _recharging
    /** The recharge page was opened; coming back refreshes the balance. */
    private var pendingRecharge: Pair<CreditAccount, Double?>? = null
    /** The app comes back to the foreground: the balance may have changed on the website or another device. */
    private var pollJob: Job? = null
    private val foreground = LifecycleEventObserver { _, event ->
        if (event == Lifecycle.Event.ON_START && session.value is SessionState.Ready) {
            refreshAccountPhoto()
            refreshBalance()
            if (shouldPollBots(_bots.value)) refreshDirectory()
        }
        if (event == Lifecycle.Event.ON_STOP) { pollJob?.cancel(); pollJob = null }
    }
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

    private val conversationScope = CoroutineScope(viewModelScope.coroutineContext + SupervisorJob(viewModelScope.coroutineContext[Job]))

    private fun detachChats() {
        chats.values.forEach { it.detach() }
        conversationScope.coroutineContext.cancelChildren()
        chats.clear()
    }

    private val chats = mutableMapOf<String, ChatSession>()

    override val backend: ChatBackend
        get() = (session.value as? SessionState.Ready)?.backend ?: error("Not signed in")

    init {
        viewModelScope.launch {
            val legacy = store.lynxceGrant()
            val server = store.serverSession()?.let { ServerBackend(it, store) }
            val selected = store.selectedBackend()
            val backend = when (SavedBackend.restore(selected, legacy != null, server != null, server?.isOfficialCloud == true)) {
                SavedBackend.Server -> server
                SavedBackend.Device -> if (app.phoneModels.phoneOnly) deviceBackend() else null
                SavedBackend.SignedOut -> null
            }
            if (backend == null) {
                val legacyUpgrade = selected == null && legacy != null
                if (legacyUpgrade) store.archiveLegacyPreviews()
                _session.value = SessionState.SignedOut(if (legacyUpgrade) resources.getString(R.string.history_reauthenticate) else null)
                _launchReady.value = true
            } else {
                enter(backend, rememberSelection = false)
            }
        }
        viewModelScope.launch { settings.collect { speaker.rate = it.speechRate.rate } }
        ProcessLifecycleOwner.get().lifecycle.addObserver(foreground)
    }

    private var historyRecoveryJob: Job? = null
    private val _recoveringHistory = MutableStateFlow(false)
    val recoveringHistory: StateFlow<Boolean> = _recoveringHistory
    private val _historyRecoveryMessage = MutableStateFlow<String?>(null)
    val historyRecoveryMessage: StateFlow<String?> = _historyRecoveryMessage

    fun recoverLegacyHistory(force: Boolean = false) {
        val server = cloudServer?.takeIf { it.isOfficialCloud } ?: return
        if (historyRecoveryJob?.isActive == true) return
        _recoveringHistory.value = true
        historyRecoveryJob = viewModelScope.launch {
            try {
                val owner = server.legacyHistoryOwner()
                if (cloudServer !== server || !force && store.legacyHistoryComplete(owner)) return@launch
                val complete = server.restoreLegacyHistory()
                if (cloudServer !== server) return@launch
                store.setLegacyHistoryComplete(owner, complete)
                if (cloudServer !== server) return@launch
                _historyRecoveryMessage.value = resources.getString(if (complete) R.string.history_restored else R.string.history_restore_incomplete)
                chats.values.toList().forEach { it.refreshConversations() }
            } catch (error: CancellationException) {
                throw error
            } catch (_: Exception) {
                if (cloudServer === server) _historyRecoveryMessage.value = resources.getString(R.string.history_restore_retry)
            } finally {
                if (cloudServer === server) _recoveringHistory.value = false
            }
        }
    }

    private fun stopHistoryRecovery() {
        historyRecoveryJob?.cancel()
        historyRecoveryJob = null
        _recoveringHistory.value = false
        _historyRecoveryMessage.value = null
    }

    // Session

    suspend fun signInLynxce(account: String, password: String) {
        enter(ServerBackend.signInWithLynxce(ServerProtocol.LYNXCE_CLOUD, account, password, store))
    }

    suspend fun requestLynxceCode(target: LynxceProtocol.Target) {
        ServerBackend.requestLynxceCode(ServerProtocol.LYNXCE_CLOUD, target.value)
    }

    suspend fun signInLynxceCode(target: LynxceProtocol.Target, code: String) {
        enter(ServerBackend.signInWithLynxceCode(ServerProtocol.LYNXCE_CLOUD, target.value, code, store))
    }

    /** Model keys and local model servers on this phone. */
    val phoneModels: PhoneModels get() = app.phoneModels

    private fun deviceBackend() = DeviceBackend(
        app.localBots, app.phoneModels, app.deviceConversations, resources.getString(R.string.account_device),
    )

    /** "Use without signing in": the phone calls the model set up on it. */
    fun usePhoneOnly() {
        app.phoneModels.phoneOnly = true
        viewModelScope.launch { enter(deviceBackend()) }
    }

    /** Where "My API keys" live: the Octop server signed in to (cloud or self-hosted), or this phone. */
    val modelKeys: ModelKeyStore?
        get() = when (val backend = (session.value as? SessionState.Ready)?.backend) {
            is ServerBackend -> ServerModelKeys(backend, app.phoneModels.bundled)
            null -> null
            else -> app.phoneModels
        }

    private val _serverKeys = MutableStateFlow<OwnKeyList?>(null)
    /** The server account's own keys and the one in use, for the Settings row. */
    val serverKeys: StateFlow<OwnKeyList?> = _serverKeys

    fun setServerKeys(list: OwnKeyList?) {
        _serverKeys.value = list
    }

    private fun refreshServerKeys() {
        val store = modelKeys?.takeUnless { it.onPhone } ?: return
        viewModelScope.launch { runCatching { store.list() }.onSuccess { _serverKeys.value = it } }
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
        viewModelScope.launch { enter(backend) }
    }

    private suspend fun enter(backend: ChatBackend, rememberSelection: Boolean = true) {
        if (rememberSelection) {
            when (backend) {
                is ServerBackend -> store.selectBackend(SavedBackend.Server)
                is DeviceBackend -> store.selectBackend(SavedBackend.Device)
            }
        }
        stopHistoryRecovery()
        detachChats()
        val previous = (session.value as? SessionState.Ready)?.backend
        if (previous != null && previous !== backend) store.clearCaches()
        clearWallet()
        _replying.value = emptySet()
        _directoryError.value = null
        val cached = store.directory()
        _bots.value = cached?.bots.orEmpty()
        _groups.value = cached?.groups.orEmpty()
        _lastBotId.value = store.lastBot()
        _session.value = SessionState.Ready(backend)
        refreshAccountPhoto()
        recoverLegacyHistory()
        (backend as? CreditAccount)?.let { account ->
            account.signupCredits?.let {
                val amount = LynxceProtocol.formatCredits(it)
                val expiry = account.signupExpiryDay
                notice(if (expiry == null) resources.getString(R.string.signup_credit_notice, amount)
                    else resources.getString(R.string.signup_credit_notice_until, amount, expiry))
            }
            account.signupCredits = null
        }
        refreshDirectory()
        _models.value = if (backend.definesBotsLocally) runCatching { backend.models() }.getOrDefault(emptyList()) else emptyList()
        _serverKeys.value = null
        refreshServerKeys()
        refreshBalance()
    }

    private fun refreshAccountPhoto() {
        val backend = (session.value as? SessionState.Ready)?.backend ?: return
        photoJob?.cancel()
        photoJob = viewModelScope.launch {
            val photo = runCatching { backend.accountPhoto() }.getOrNull() ?: return@launch
            if ((session.value as? SessionState.Ready)?.backend === backend) _accountPhoto.value = photo
        }
    }

    private fun clearWallet() {
        photoJob?.cancel()
        _accountPhoto.value = null
        balanceJob?.cancel()
        balanceJob = null
        _balance.value = null
        _walletKey.value = null
        _usage.value = null
        pendingRecharge = null
    }

    fun signOut(notice: String? = null, reopenServer: Boolean = false) {
        val backend = (session.value as? SessionState.Ready)?.backend ?: return
        stopHistoryRecovery()
        pollJob?.cancel()
        pollJob = null
        stopReading()
        voiceInput.cancel()
        detachChats()
        clearWallet()
        // Leaving phone-only use keeps its keys and chats for next time.
        if (backend is DeviceBackend) app.phoneModels.phoneOnly = false
        // Octop Bot cloud is a Lynxce sign-in, not a server the user typed: it goes back to the sign-in screen.
        val reopen = reopenServer && backend is ServerBackend && !backend.isCloud
        // Expose the next login only after this account has finished clearing its own credentials.
        _session.value = SessionState.Loading
        viewModelScope.launch {
            if (reopen) {
                // "Switch account or server": the server form opens with this server's full address.
                store.setLastServer(backend.baseUrl)
            }
            store.selectBackend(SavedBackend.SignedOut)
            backend.signOut()
            store.clearCaches()
            _session.value = SessionState.SignedOut(notice, reopenServer = reopen)
        }
    }

    /** Sign out and return to the first screen; from a self-hosted server, straight to the server form. */
    fun switchAccount() {
        val backend = (session.value as? SessionState.Ready)?.backend
        signOut(reopenServer = backend is ServerBackend && !backend.isCloud)
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
            scheduleBotPolling()
            _launchReady.value = true
        }
    }

    private fun scheduleBotPolling() {
        if (!shouldPollBots(_bots.value) || !ProcessLifecycleOwner.get().lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) {
            pollJob?.cancel()
            pollJob = null
            return
        }
        if (pollJob?.isActive == true) return
        pollJob = viewModelScope.launch {
            while (shouldPollBots(_bots.value)) {
                delay(1500)
                val server = (session.value as? SessionState.Ready)?.backend as? ServerBackend ?: break
                try {
                    val bots = server.bots()
                    _bots.value = bots
                    _directoryError.value = null
                    store.setDirectory(DirectoryCache(bots, _groups.value))
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    if (error is ApiException && error.kind == ApiException.Kind.Unauthorized) {
                        failed(error)
                        break
                    }
                    _directoryError.value = resources.describe(error)
                }
            }
        }
    }

    fun retryBot(bot: BotProfile) {
        val server = (session.value as? SessionState.Ready)?.backend as? ServerBackend ?: return
        viewModelScope.launch {
            runCatching { server.startBot(bot) }
                .onSuccess { refreshDirectory() }
                .onFailure { _directoryError.value = resources.describe(it) }
        }
    }

    /** Re-read the Lynxce balance (foreground, after a reply, back from recharge). Keeps the value shown meanwhile. */
    fun refreshBalance() {
        val account = creditAccount
        if (account == null) {
            _balance.value = null
            return
        }
        if (balanceJob?.isActive == true) return
        balanceJob = viewModelScope.launch { loadBalance(account) }
    }

    private suspend fun loadBalance(account: CreditAccount) {
        if (_balance.value !is BalanceState.Value) _balance.value = BalanceState.Loading
        val result = runCatching { account.balance() }
        (result.exceptionOrNull() as? CancellationException)?.let { throw it }
        if (creditAccount !== account) return
        result.onSuccess { credits ->
            _balance.value = BalanceState.Value(credits)
            val wallet = account.walletKey
            _walletKey.value = wallet
            if (wallet != null) scheduleLowBalanceReset(wallet)
        }.onFailure { error ->
            // Signed out elsewhere: the session ends (and the wallet with it).
            if (error is ApiException && error.kind == ApiException.Kind.Unauthorized) failed(error) else _balance.value = BalanceState.Failed
        }
    }

    /** Settings → Credits, and its pull-to-refresh: the balance and, on an Octop server, the last 30 days of usage. */
    fun refreshCredits() {
        val account = creditAccount ?: return
        if (_creditsRefreshing.value) return
        val server = (session.value as? SessionState.Ready)?.backend as? ServerBackend
        _creditsRefreshing.value = true
        viewModelScope.launch {
            balanceJob?.cancel()
            val balance = async { loadBalance(account) }
            if (server != null) {
                _usage.value = (_usage.value ?: UsageState()).copy(loading = true, failed = false)
                val byBot = async { runCatching { server.usage("by_agent") } }
                val byModel = async { runCatching { server.usage("by_model") } }
                val bots = byBot.await()
                val models = byModel.await()
                if (creditAccount === account) {
                    _usage.value = UsageState(
                        loading = false,
                        failed = bots.isFailure || models.isFailure,
                        byBot = bots.getOrNull(),
                        byModel = models.getOrNull(),
                    )
                }
            } else {
                _usage.value = null
            }
            balance.await()
            _creditsRefreshing.value = false
        }
    }

    /** The chat banner stays hidden for 24 hours after closing. */
    fun dismissLowBalance() {
        val wallet = _walletKey.value ?: return
        store.dismissLowBalance(wallet)
        scheduleLowBalanceReset(wallet)
    }

    private fun scheduleLowBalanceReset(wallet: String) {
        val dismissedAt = store.lowBalanceDismissed.value[wallet] ?: return
        val remaining = dismissedAt + LOW_BALANCE_DISMISSAL_MS - System.currentTimeMillis()
        if (remaining <= 0) return
        viewModelScope.launch {
            delay(remaining)
            if (store.lowBalanceDismissed.value[wallet] == dismissedAt) {
                store.lowBalanceDismissed.value = store.lowBalanceDismissed.value - wallet
            }
        }
    }

    /** The activity resumed; back from the recharge page, the new balance shows. */
    fun appResumed(explicitReturn: Boolean = false) {
        val checkout = pendingRecharge
        if (checkout == null) {
            if (explicitReturn) refreshBalance()
            return
        }
        pendingRecharge = null
        val (account, before) = checkout
        if (creditAccount !== account) return
        balanceJob?.cancel()
        balanceJob = viewModelScope.launch {
            loadBalance(account)
            val after = (_balance.value as? BalanceState.Value)?.credits
            if (creditAccount === account && before != null && after != null && after > before) {
                notice(resources.getString(R.string.checkout_balance_increased, LynxceProtocol.formatCredits(after - before), LynxceProtocol.formatCredits(after)))
            }
        }
    }

    private val attachmentFiles = AttachmentFiles(application.cacheDir)

    private val fileServer: ServerBackend? get() = (session.value as? SessionState.Ready)?.backend as? ServerBackend

    /** A file's size for its card; null while unknown. */
    suspend fun attachmentSize(server: ServerBackend, file: FileAttachment): Long? {
        if (server !== fileServer) return null
        return attachmentFiles.size(server.attachmentScope, file, server::fileSize).takeIf { server === fileServer }
    }

    /** The local copy of a file for a card's preview; null when it can't be fetched (the card stays plain). */
    suspend fun attachmentPreviewFile(server: ServerBackend, file: FileAttachment): File? {
        if (server !== fileServer) return null
        return runCatching { attachmentFiles.local(server.attachmentScope, file, server::downloadFile) }
            .getOrNull()?.takeIf { server === fileServer }
    }

    /** Fetches a file a Bot sent (once) and hands the local copy to [use]; failures show in the snackbar. */
    fun withAttachment(server: ServerBackend?, file: FileAttachment, use: (File) -> Unit) {
        if (server !== fileServer) return
        if (server == null) {
            notice(resources.getString(R.string.file_open_unsupported))
            return
        }
        viewModelScope.launch {
            val result = runCatching { attachmentFiles.local(server.attachmentScope, file, server::downloadFile) }
            if (server === fileServer) result.onSuccess(use).onFailure { notice(resources.describe(it)) }
        }
    }

    /** Android 10+: a copy in Downloads. */
    fun saveAttachment(server: ServerBackend, file: FileAttachment) = withAttachment(server, file) { local ->
        viewModelScope.launch {
            if (server !== fileServer) return@launch
            val result = runCatching {
                withContext(Dispatchers.IO) { AttachmentFiles.saveToDownloads(app, local, local.name, AttachmentFiles.mimeOf(file)) }
            }
            if (server === fileServer) result
                .onSuccess { notice(resources.getString(R.string.file_saved)) }
                .onFailure { notice(resources.getString(R.string.file_save_failed)) }
        }
    }

    /** Android 8–9: write a file into the document the user picked with "Save to…". */
    fun copyAttachment(server: ServerBackend, file: FileAttachment, target: android.net.Uri) = withAttachment(server, file) { local ->
        viewModelScope.launch {
            if (server !== fileServer) return@launch
            val result = runCatching { withContext(Dispatchers.IO) { AttachmentFiles.copyTo(app, local, target) } }
            if (server === fileServer) result
                .onSuccess { notice(resources.getString(R.string.file_saved_to)) }
                .onFailure { notice(resources.getString(R.string.file_save_failed)) }
        }
    }

    /** A file a Bot linked to in a reply: fetched with this account (via the object store on Octop Bot cloud). */
    fun openWorkspaceFile(server: ServerBackend?, uri: String, open: (File, String) -> Unit) {
        val name = FileCards.queryValue(uri, "path")?.let(FileCards::baseName)?.takeIf { it.isNotEmpty() } ?: "file"
        val file = FileAttachment(uri, name)
        withAttachment(server, file) { open(it, AttachmentFiles.mimeOf(file)) }
    }

    /**
     * Open Lynxce's recharge page signed in as this account (a 15-minute ticket, as on the desktop). Taps while
     * the link is being fetched are ignored.
     */
    fun recharge(scenario: io.github.alisonxx.octopbot.net.CreditScenario? = null, open: (String) -> Unit) {
        val account = creditAccount ?: return
        if (_recharging.value) return
        _recharging.value = true
        viewModelScope.launch {
            runCatching { account.checkoutUrl(scenario) }
                .onSuccess {
                    if (creditAccount !== account) return@onSuccess
                    pendingRecharge = account to (_balance.value as? BalanceState.Value)?.credits
                    open(it)
                }
                .onFailure { notice(rechargeFailure(it)) }
            _recharging.value = false
        }
    }

    private fun rechargeFailure(error: Throwable): String = when {
        error is CheckoutRefused -> resources.getString(R.string.recharge_link_refused)
        error is ApiException && error.kind == ApiException.Kind.Unauthorized -> resources.describe(error)
        error is ApiException && error.kind == ApiException.Kind.Network -> resources.describe(error)
        error is ApiException && (error.kind == ApiException.Kind.Credits || error.kind == ApiException.Kind.DailyLimit) ->
            resources.describe(error)
        error is ApiException && !error.message.isNullOrBlank() -> error.message.orEmpty()
        else -> resources.getString(R.string.recharge_unavailable)
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

    suspend fun openNotification(botId: String, threadId: String?): Boolean {
        val current = (session.value as? SessionState.Ready)?.backend ?: return false
        val bot = _bots.value.firstOrNull { it.id == botId } ?: return false
        if (threadId != null) {
            val target = current.conversations(bot).firstOrNull { it.id == threadId } ?: return false
            if ((session.value as? SessionState.Ready)?.backend !== current) return false
            chat(botId).open(target)
        }
        return true
    }

    fun chat(botId: String): ChatSession = chats.getOrPut(botId) { ChatSession(botId, conversationScope, this) }

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
    fun setDeviceHealth(value: Boolean) = viewModelScope.launch { store.setDeviceHealth(value) }
    fun setDeviceCalendar(value: Boolean) = viewModelScope.launch { store.setDeviceCalendar(value) }

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
        // Every finished reply (even a failed one) may have spent credits.
        if (creditAccount != null) refreshBalance()
        if (text == null) return
        val onScreen = chatOnScreen == bot.id
        val thread = chats[bot.id]?.state?.value?.conversationId
        viewModelScope.launch {
            store.updatePreviews { Previews.replyFinished(it, bot.id, text, System.currentTimeMillis(), onScreen) }
            val settings = settings.first()
            if (settings.notifications) app.notifier.replyFinished(bot.id, thread, bot.name, text)
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

    override val device: DeviceConnectors get() = app.device

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
        ProcessLifecycleOwner.get().lifecycle.removeObserver(foreground)
        speaker.release()
        voiceInput.cancel()
    }
}

internal const val LOW_BALANCE_DISMISSAL_MS = 24 * 60 * 60 * 1000L
internal fun lowBalanceIsDismissed(at: Long?, now: Long): Boolean =
    at != null && at > 0 && now - at < LOW_BALANCE_DISMISSAL_MS
