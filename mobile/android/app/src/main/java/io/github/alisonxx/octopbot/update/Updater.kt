package io.github.alisonxx.octopbot.update

import android.content.Context
import android.util.Log
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.ProcessLifecycleOwner
import io.github.alisonxx.octopbot.BuildConfig
import io.github.alisonxx.octopbot.net.Http
import io.github.alisonxx.octopbot.store.AppStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.io.File

sealed interface UpdatePhase {
    data object Idle : UpdatePhase
    data object Checking : UpdatePhase
    data object UpToDate : UpdatePhase
    data object CheckFailed : UpdatePhase
    /** [percent] is -1 when the size is unknown. */
    data class Downloading(val percent: Int) : UpdatePhase
    /** [integrity]: the SHA-256 or the signing certificate did not match. */
    data class DownloadFailed(val integrity: Boolean) : UpdatePhase
    data class Ready(val apk: File) : UpdatePhase
}

data class UpdateState(val offer: UpdateOffer? = null, val phase: UpdatePhase = UpdatePhase.Idle)

/**
 * App-wide update checks and downloads. Checks run 10 s after launch, on returning to the foreground when the
 * last check is over 24 h old, and from Settings. Nothing here blocks the UI or installs on its own: a verified
 * APK goes out on [installs] and the UI hands it to the system installer.
 */
class Updater(context: Context, private val store: AppStore, private val scope: CoroutineScope) {
    private val app = context.applicationContext
    private val client = UpdateClient(
        client = Http.client,
        manifestUrl = BuildConfig.UPDATE_MANIFEST_URL,
        publicKey = BuildConfig.UPDATE_PUBLIC_KEY,
        // Pure-Kotlin Ed25519 (ManifestSignature), so every Android version checks the signature.
        verifySignature = true,
    )
    private val checks = Mutex()
    private var downloadJob: Job? = null
    private var launched = false

    private val _state = MutableStateFlow(UpdateState())
    val state: StateFlow<UpdateState> = _state

    private val _installs = Channel<File>(Channel.CONFLATED)
    /** A downloaded and verified APK, ready for the system installer. */
    val installs: Flow<File> = _installs.receiveAsFlow()

    fun watchForeground() {
        ProcessLifecycleOwner.get().lifecycle.addObserver(
            LifecycleEventObserver { _, event ->
                if (event != Lifecycle.Event.ON_START) return@LifecycleEventObserver
                if (!launched) {
                    launched = true
                    scope.launch {
                        delay(LAUNCH_DELAY_MS)
                        check(manual = false)
                    }
                } else {
                    scope.launch {
                        if (UpdateSelection.checkDue(store.lastUpdateCheck(), System.currentTimeMillis())) check(manual = false)
                    }
                }
            },
        )
    }

    /** Fetch, verify and evaluate the manifest. Returns false when it failed. Skipped while a download runs. */
    suspend fun check(manual: Boolean): Boolean = checks.withLock {
        if (downloadJob?.isActive == true) return@withLock true
        val before = _state.value
        // An automatic check keeps the status line quiet until it has an answer.
        if (manual || before.offer == null) _state.update { it.copy(phase = UpdatePhase.Checking) }
        runCatching {
            val manifest = client.fetchManifest()
            UpdateSelection.offer(
                manifest = manifest,
                receiveBeta = store.settings.first().receiveBeta,
                installId = store.installId(),
                currentVersionCode = BuildConfig.VERSION_CODE,
                debugOrigin = BuildConfig.UPDATE_DEBUG_ORIGIN,
            )
        }.fold(
            onSuccess = { offer ->
                store.setLastUpdateCheck(System.currentTimeMillis())
                val keep = offer != null && offer.versionCode == before.offer?.versionCode &&
                    (before.phase is UpdatePhase.Ready || before.phase is UpdatePhase.DownloadFailed)
                _state.value = UpdateState(
                    offer = offer,
                    phase = when {
                        keep -> before.phase
                        offer == null -> UpdatePhase.UpToDate
                        else -> UpdatePhase.Idle
                    },
                )
                true
            },
            onFailure = { error ->
                if (error is CancellationException) throw error
                Log.w(TAG, "update check failed", error)
                // A known offer stays usable; otherwise the status line says the check failed.
                _state.update { it.copy(phase = if (it.offer != null && !manual) before.phase else UpdatePhase.CheckFailed) }
                false
            },
        )
    }

    /** "Update": install a downloaded APK, or download (again) and verify it first. */
    fun update() {
        val state = _state.value
        val offer = state.offer ?: return
        val phase = state.phase
        if (phase is UpdatePhase.Ready && phase.apk.isFile) {
            _installs.trySend(phase.apk)
            return
        }
        if (downloadJob?.isActive == true) return
        downloadJob = scope.launch {
            _state.update { it.copy(phase = UpdatePhase.Downloading(0)) }
            try {
                val dir = File(app.cacheDir, "updates")
                val target = File(dir, "octop-bot-${offer.versionCode}.apk")
                withContext(Dispatchers.IO) { dir.listFiles()?.filter { it.name != target.name }?.forEach { it.delete() } }
                val apk = client.download(offer, target) { percent ->
                    _state.update { if (it.phase is UpdatePhase.Downloading) it.copy(phase = UpdatePhase.Downloading(percent)) else it }
                }
                if (!withContext(Dispatchers.IO) { ApkInstaller.matchesInstalled(app, apk) }) {
                    apk.delete()
                    throw UpdateException(integrity = true, message = "signing certificate differs")
                }
                _state.update { it.copy(phase = UpdatePhase.Ready(apk)) }
                _installs.trySend(apk)
            } catch (cancelled: CancellationException) {
                _state.update { it.copy(phase = UpdatePhase.Idle) }
                throw cancelled
            } catch (error: Exception) {
                _state.update { it.copy(phase = UpdatePhase.DownloadFailed(integrity = (error as? UpdateException)?.integrity == true)) }
            }
        }
    }

    fun cancelDownload() {
        downloadJob?.cancel()
    }

    private companion object {
        const val LAUNCH_DELAY_MS = 10_000L
        const val TAG = "OctopUpdate"
    }
}
