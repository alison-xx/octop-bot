package io.github.alisonxx.octopbot.ui.settings

import io.github.alisonxx.octopbot.net.GitHubStars
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.material.icons.rounded.Star
import android.Manifest
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.ui.graphics.Color
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.ClipEntry
import androidx.compose.ui.platform.LocalClipboard
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import androidx.core.net.toUri
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.BuildConfig
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppLocale
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.BalanceState
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.net.DeviceBackend
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.store.Appearance
import io.github.alisonxx.octopbot.store.SpeechRate
import io.github.alisonxx.octopbot.store.TextSize
import io.github.alisonxx.octopbot.store.UserSettings
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.BalanceText
import io.github.alisonxx.octopbot.ui.common.LowBalanceColor
import io.github.alisonxx.octopbot.ui.common.accountName
import io.github.alisonxx.octopbot.ui.common.credits
import io.github.alisonxx.octopbot.ui.common.modeLabel
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.TopBarTitle
import io.github.alisonxx.octopbot.ui.common.rememberHaptics
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import io.github.alisonxx.octopbot.update.UpdatePhase
import io.github.alisonxx.octopbot.update.UpdateState
import kotlinx.coroutines.launch

private const val ISSUE_URL = "https://github.com/alison-xx/octop-bot/issues/new"
private const val LYNXCE_URL = "https://www.lynxce.cn"

/** Everything the settings page shows, separate from the ViewModel for previews. */
data class SettingsState(
    /** A display name, or "Lynxce user"; never a username or account id. */
    val accountName: String,
    /** null without a Lynxce wallet (a self-hosted server). */
    val balance: BalanceState?,
    val lynxce: Boolean,
    /** A Lynxce wallet to show, recharge and delete: Lynxce mode, or Octop Bot cloud. */
    val wallet: Boolean = lynxce,
    /** "Lynxce cloud", "Lynxce account", or host[:port] of a self-hosted server. */
    val host: String,
    /** The full address of a self-hosted server (tap to copy); null in Lynxce mode and on Octop Bot cloud. */
    val serverAddress: String?,
    val models: List<ModelOption>,
    val settings: UserSettings,
    /** [AppLocale] tag; empty follows the system. */
    val language: String,
    /** The system blocks this app's notifications (permission denied or turned off). */
    val notificationsBlocked: Boolean,
    val update: UpdateState = UpdateState(),
    /** Device connectors: on in Settings and permitted by the system. */
    val deviceHealth: Boolean = false,
    val deviceCalendar: Boolean = false,
    val deviceNotice: DeviceNotice? = null,
    /** Settings → Models is offered (phone Bots or Octop Bot cloud); [modelSummary] is the model in use. */
    val showModels: Boolean = lynxce,
    val modelSummary: String? = null,
    /** The card-style Lynxce account (tier, balance split) when there is a Lynxce wallet. */
    val account: AccountSummary? = null,
    /** Used without signing in: no account to sign out of, a way to sign in instead. */
    val phoneOnly: Boolean = false,
)

/** Why a device connector switch stayed off. */
enum class DeviceNotice { CalendarDenied, HealthDenied, HealthUnavailable, HealthUpdate }

/** What the settings page can change. */
class SettingsActions(
    val onBack: () -> Unit,
    val onModels: () -> Unit,
    val onLanguage: (String) -> Unit,
    val onAppearance: (Appearance) -> Unit,
    val onTextSize: (TextSize) -> Unit,
    val onHaptics: (Boolean) -> Unit,
    val onExpandReasoning: (Boolean) -> Unit,
    val onReadAloud: (Boolean) -> Unit,
    val onSpeechRate: (SpeechRate) -> Unit,
    val onNotifications: (Boolean) -> Unit,
    val onOpenNotificationSettings: () -> Unit,
    val onClearCache: () -> Unit,
    val onCopyAddress: (String) -> Unit,
    val onSwitchAccount: () -> Unit,
    val onSignOut: () -> Unit,
    val onOpenUrl: (String) -> Unit,
    /** Settings → Credits & top-up. */
    val onCredits: () -> Unit = {},
    val onRetryBalance: () -> Unit = {},
    val onDeleteAccount: () -> Unit = {},
    val onCheckUpdates: () -> Unit = {},
    val onUpdate: () -> Unit = {},
    val onCancelUpdate: () -> Unit = {},
    val onReceiveBeta: (Boolean) -> Unit = {},
    val onDeviceHealth: (Boolean) -> Unit = {},
    val onDeviceCalendar: (Boolean) -> Unit = {},
    /** Opens where the [DeviceNotice] can be fixed: app permissions, Health Connect, or the store. */
    val onFixDevice: () -> Unit = {},
)

@Composable
fun SettingsScreen(model: AppViewModel, onBack: () -> Unit, onModels: () -> Unit, onCredits: () -> Unit) {
    val session by model.session.collectAsStateWithLifecycle()
    val backend = (session as? SessionState.Ready)?.backend ?: return
    val balance by model.balance.collectAsStateWithLifecycle()
    val models by model.models.collectAsStateWithLifecycle()
    val settings by model.settings.collectAsStateWithLifecycle()
    val update by model.update.collectAsStateWithLifecycle()
    val serverKeys by model.serverKeys.collectAsStateWithLifecycle()
    val phoneSelection by model.phoneModels.selection.collectAsStateWithLifecycle()
    val phoneKeys by model.phoneModels.ownKeys.collectAsStateWithLifecycle()
    val phoneLocal by model.phoneModels.local.collectAsStateWithLifecycle()
    val cloud = (backend as? ServerBackend)?.isCloud == true
    val phoneModel = remember(phoneSelection, phoneKeys, phoneLocal) { model.phoneModels.current { it.name }?.first }
    val modelSummary = when {
        cloud -> serverKeys?.takeIf { it.inUse != null }?.selectedModel ?: stringResource(R.string.models_lynxce_auto)
        backend is ServerBackend -> serverKeys?.takeIf { it.inUse != null }?.selectedModel ?: stringResource(R.string.models_server_default)
        backend is DeviceBackend -> phoneModel ?: stringResource(R.string.models_none)
        else -> phoneModel ?: models.firstOrNull { it.id == settings.model }?.name ?: stringResource(R.string.settings_model_auto)
    }
    val context = LocalContext.current
    val clipboard = LocalClipboard.current
    val scope = rememberCoroutineScope()
    val haptics = rememberHaptics()
    val copied = stringResource(R.string.common_copied)
    val cleared = stringResource(R.string.settings_cache_cleared)
    var blocked by remember { mutableStateOf(!notificationsAllowed(context)) }
    val device = model.device
    var calendarPermitted by remember { mutableStateOf(device.calendar.permitted()) }
    var healthPermitted by remember { mutableStateOf(false) }
    var deviceNotice by remember { mutableStateOf<DeviceNotice?>(null) }
    // Coming back from system settings re-checks the permissions.
    // Coming back from the recharge page shows the new balance.
    LifecycleResumeEffect(Unit) {
        blocked = !notificationsAllowed(context)
        model.refreshBalance()
        calendarPermitted = device.calendar.permitted()
        val check = scope.launch {
            healthPermitted = device.health.permitted()
            if ((deviceNotice == DeviceNotice.CalendarDenied && calendarPermitted) ||
                (deviceNotice == DeviceNotice.HealthDenied && healthPermitted)
            ) {
                deviceNotice = null
            }
        }
        onPauseOrDispose { check.cancel() }
    }
    val askCalendar = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) {
        calendarPermitted = device.calendar.permitted()
        if (calendarPermitted) model.setDeviceCalendar(true)
        deviceNotice = if (calendarPermitted) null else DeviceNotice.CalendarDenied
    }
    val askHealth = rememberLauncherForActivityResult(PermissionController.createRequestPermissionResultContract()) { granted ->
        healthPermitted = granted.any { it in device.health.permissions }
        if (healthPermitted) model.setDeviceHealth(true)
        deviceNotice = if (healthPermitted) null else DeviceNotice.HealthDenied
    }
    val askPermission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        blocked = !notificationsAllowed(context)
    }
    Settings(
        state = SettingsState(
            accountName = accountName(backend),
            balance = balance,
            account = AccountSummary.demo(context) ?: if (model.creditAccount != null) {
                AccountSummary(accountName(backend), credits = (balance as? BalanceState.Value)?.credits, signupExpiryDay = model.creditAccount?.signupExpiryDay)
            } else null,
            lynxce = backend.definesBotsLocally,
            wallet = model.creditAccount != null,
            host = modeLabel(backend),
            serverAddress = (backend as? ServerBackend)?.takeUnless { it.isCloud }?.baseUrl,
            models = models,
            settings = settings,
            language = AppLocale.tag(),
            notificationsBlocked = blocked,
            update = update,
            deviceHealth = settings.deviceHealth && healthPermitted,
            deviceCalendar = settings.deviceCalendar && calendarPermitted,
            deviceNotice = deviceNotice,
            showModels = true,
            modelSummary = modelSummary,
            phoneOnly = backend is DeviceBackend,
        ),
        actions = SettingsActions(
            onBack = onBack,
            onModels = onModels,
            onLanguage = model::setLanguage,
            onAppearance = model::setAppearance,
            onTextSize = { model.setTextSize(it) },
            onHaptics = { model.setHaptics(it) },
            onExpandReasoning = { model.setExpandReasoning(it) },
            onReadAloud = { model.setReadAloud(it) },
            onSpeechRate = { model.setSpeechRate(it) },
            onNotifications = { on ->
                model.setNotifications(on)
                if (on && blocked && Build.VERSION.SDK_INT >= 33) askPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
            },
            onOpenNotificationSettings = {
                context.startActivity(
                    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
                )
            },
            onClearCache = { model.clearLocalCache(cleared) },
            onCopyAddress = { address ->
                haptics.tap()
                scope.launch {
                    clipboard.setClipEntry(ClipEntry(ClipData.newPlainText("Octop Bot", address)))
                    model.notice(copied)
                }
            },
            onSwitchAccount = model::switchAccount,
            onSignOut = { model.signOut() },
            onOpenUrl = { url -> context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri())) },
            onCredits = onCredits,
            onRetryBalance = model::refreshBalance,
            onDeleteAccount = model::deleteAccount,
            onCheckUpdates = model::checkForUpdates,
            onUpdate = model::startUpdate,
            onCancelUpdate = model::cancelUpdateDownload,
            onReceiveBeta = { model.setReceiveBeta(it) },
            onDeviceHealth = { on ->
                when {
                    !on -> model.setDeviceHealth(false)
                    healthPermitted -> model.setDeviceHealth(true)
                    else -> when (device.health.status()) {
                        HealthConnectClient.SDK_AVAILABLE -> askHealth.launch(device.health.permissions)
                        HealthConnectClient.SDK_UNAVAILABLE_PROVIDER_UPDATE_REQUIRED -> deviceNotice = DeviceNotice.HealthUpdate
                        else -> deviceNotice = DeviceNotice.HealthUnavailable
                    }
                }
            },
            onDeviceCalendar = { on ->
                when {
                    !on -> model.setDeviceCalendar(false)
                    calendarPermitted -> model.setDeviceCalendar(true)
                    else -> askCalendar.launch(device.calendar.permissions)
                }
            },
            onFixDevice = { deviceNotice?.let { openDeviceFix(context, it) } },
        ),
    )
}

private const val HEALTH_CONNECT_PACKAGE = "com.google.android.apps.healthdata"

private fun openDeviceFix(context: Context, notice: DeviceNotice) {
    val appDetails = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, "package:${context.packageName}".toUri())
    val intent = when (notice) {
        DeviceNotice.CalendarDenied, DeviceNotice.HealthUnavailable -> appDetails
        DeviceNotice.HealthDenied -> Intent(HealthConnectClient.ACTION_HEALTH_CONNECT_SETTINGS)
        DeviceNotice.HealthUpdate -> Intent(
            Intent.ACTION_VIEW,
            "market://details?id=$HEALTH_CONNECT_PACKAGE&url=healthconnect%3A%2F%2Fonboarding".toUri(),
        )
    }
    runCatching { context.startActivity(intent) }.onFailure { runCatching { context.startActivity(appDetails) } }
}

private fun notificationsAllowed(context: Context): Boolean = NotificationManagerCompat.from(context).areNotificationsEnabled()

private enum class Picker { Language, Appearance, TextSize, SpeechRate }

@Composable
fun Settings(state: SettingsState, actions: SettingsActions) {
    var picker by rememberSaveable { mutableStateOf<Picker?>(null) }
    var confirmSignOut by rememberSaveable { mutableStateOf(false) }
    var confirmDelete by rememberSaveable { mutableStateOf(false) }
    var confirmClear by rememberSaveable { mutableStateOf(false) }
    val languages = listOf(
        AppLocale.SYSTEM to stringResource(R.string.settings_follow_system),
        AppLocale.CHINESE to "简体中文",
        AppLocale.ENGLISH to "English",
    )
    val appearances = listOf(
        Appearance.System to stringResource(R.string.settings_follow_system),
        Appearance.Dark to stringResource(R.string.settings_appearance_dark),
        Appearance.Light to stringResource(R.string.settings_appearance_light),
    )
    val textSizes = listOf(
        TextSize.Small to stringResource(R.string.settings_text_small),
        TextSize.Standard to stringResource(R.string.settings_text_standard),
        TextSize.Large to stringResource(R.string.settings_text_large),
    )
    val speechRates = listOf(
        SpeechRate.Slow to stringResource(R.string.settings_speed_slow),
        SpeechRate.Normal to stringResource(R.string.settings_speed_normal),
        SpeechRate.Fast to stringResource(R.string.settings_speed_fast),
    )
    val language = languages.firstOrNull { it.first == state.language } ?: languages.first()
    val connection = state.host

    Column(Modifier.fillMaxSize()) {
        TopBar(leading = { BackButton(actions.onBack) }) { TopBarTitle(stringResource(R.string.settings_title)) }
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp)
                .navigationBarsPadding(),
        ) {
            val uri = LocalUriHandler.current
            state.account?.let { MemberCard(it, onCredits = actions.onCredits, onOpen = { url -> uri.openUri(url) }) }
                ?: AccountCard(
                    state.accountName,
                    connection,
                    state.balance.takeIf { state.wallet },
                    onBalance = actions.onCredits,
                    onRetry = actions.onRetryBalance,
                )

            Group(stringResource(R.string.settings_general)) {
                row {
                    Item(stringResource(R.string.settings_language), value = language.second, chevron = true) { picker = Picker.Language }
                }
                row {
                    Item(
                        stringResource(R.string.settings_appearance),
                        value = appearances.first { it.first == state.settings.appearance }.second,
                        chevron = true,
                    ) { picker = Picker.Appearance }
                }
                row {
                    Item(
                        stringResource(R.string.settings_text_size),
                        value = textSizes.first { it.first == state.settings.textSize }.second,
                        chevron = true,
                    ) { picker = Picker.TextSize }
                }
                row { Toggle(stringResource(R.string.settings_haptics), state.settings.haptics, actions.onHaptics) }
            }

            Group(stringResource(R.string.settings_chat)) {
                if (state.showModels) {
                    row {
                        Item(
                            stringResource(R.string.settings_model),
                            value = state.modelSummary,
                            chevron = true,
                            onClick = actions.onModels,
                        )
                    }
                }
                row { Toggle(stringResource(R.string.settings_expand_reasoning), state.settings.expandReasoning, actions.onExpandReasoning) }
                row { Toggle(stringResource(R.string.settings_read_aloud), state.settings.readAloud, actions.onReadAloud) }
                row {
                    Item(
                        stringResource(R.string.settings_speech_rate),
                        value = speechRates.first { it.first == state.settings.speechRate }.second,
                        chevron = true,
                    ) { picker = Picker.SpeechRate }
                }
            }

            Group(
                stringResource(R.string.settings_notifications),
                footer = if (state.notificationsBlocked) {
                    {
                        Column {
                            FooterText(stringResource(R.string.settings_notify_blocked))
                            TextButton(onClick = actions.onOpenNotificationSettings, modifier = Modifier.padding(start = 4.dp)) {
                                Text(stringResource(R.string.settings_open_system_settings), color = SettingsLink)
                            }
                        }
                    }
                } else {
                    null
                },
            ) {
                row { Toggle(stringResource(R.string.settings_notify), state.settings.notifications, actions.onNotifications) }
            }

            Group(
                stringResource(R.string.settings_device),
                footer = {
                    Column {
                        FooterText(stringResource(R.string.settings_device_footer))
                        state.deviceNotice?.let { notice ->
                            FooterText(
                                stringResource(
                                    when (notice) {
                                        DeviceNotice.CalendarDenied, DeviceNotice.HealthDenied -> R.string.settings_device_denied
                                        DeviceNotice.HealthUnavailable -> R.string.settings_device_health_unavailable
                                        DeviceNotice.HealthUpdate -> R.string.settings_device_health_update
                                    },
                                ),
                            )
                            if (notice != DeviceNotice.HealthUnavailable) {
                                TextButton(onClick = actions.onFixDevice, modifier = Modifier.padding(start = 4.dp)) {
                                    Text(
                                        stringResource(
                                            if (notice == DeviceNotice.HealthUpdate) R.string.settings_device_health_install else R.string.settings_open_system_settings,
                                        ),
                                        color = SettingsLink,
                                    )
                                }
                            }
                        }
                    }
                },
            ) {
                row { Toggle(stringResource(R.string.settings_device_health), state.deviceHealth, actions.onDeviceHealth) }
                row { Toggle(stringResource(R.string.settings_device_calendar), state.deviceCalendar, actions.onDeviceCalendar) }
            }

            Group(stringResource(R.string.settings_storage), footer = { FooterText(stringResource(R.string.settings_clear_cache_footer)) }) {
                row { Item(stringResource(R.string.settings_clear_cache)) { confirmClear = true } }
            }

            Group(stringResource(R.string.settings_account)) {
                row { Item(stringResource(R.string.settings_signed_in_as), value = state.accountName) }
                // A self-hosted server has no Lynxce wallet: no credits row at all.
                if (state.wallet) {
                    row {
                        Item(
                            stringResource(R.string.settings_recharge),
                            value = (state.balance as? BalanceState.Value)?.let {
                                stringResource(R.string.settings_balance_chip, credits(it.credits))
                            },
                            valueColor = (state.balance as? BalanceState.Value)?.takeIf { it.low }?.let { LowBalanceColor },
                            chevron = true,
                            onClick = actions.onCredits,
                        )
                    }
                }
                row {
                    val address = state.serverAddress
                    Item(
                        stringResource(R.string.settings_connection),
                        value = address ?: connection,
                        onClick = address?.let { { actions.onCopyAddress(it) } },
                    )
                }
                if (state.phoneOnly) {
                    // Phone-only use has no account to leave; the keys and chats stay for next time.
                    row { Item(stringResource(R.string.models_lynxce_sign_in), chevron = true, onClick = actions.onSignOut) }
                } else {
                    row { Item(stringResource(R.string.settings_switch_account), chevron = true, onClick = actions.onSwitchAccount) }
                    row { Item(stringResource(R.string.settings_sign_out), danger = true) { confirmSignOut = true } }
                }
            }

            if (state.wallet) {
                Group(null, footer = { FooterText(stringResource(R.string.settings_delete_account_footer)) }) {
                    row { Item(stringResource(R.string.settings_delete_account), danger = true) { confirmDelete = true } }
                }
            }

            Group(stringResource(R.string.settings_about)) {
                row { VersionItem(state.update) }
                state.update.offer?.let { offer ->
                    row { UpdateItem(offer.version, state.update.phase, actions.onUpdate, actions.onCancelUpdate) }
                }
                row {
                    val busy = state.update.phase == UpdatePhase.Checking || state.update.phase is UpdatePhase.Downloading
                    Item(stringResource(R.string.update_check), onClick = actions.onCheckUpdates.takeUnless { busy })
                }
                row { Toggle(stringResource(R.string.update_receive_beta), state.settings.receiveBeta, actions.onReceiveBeta) }
                row { RepoItem(GitHubStars.bot) { actions.onOpenUrl(GitHubStars.bot.url) } }
                row { RepoItem(GitHubStars.octop) { actions.onOpenUrl(GitHubStars.octop.url) } }
                row { Item(stringResource(R.string.settings_report), external = true) { actions.onOpenUrl(ISSUE_URL) } }
                row { Item(stringResource(R.string.settings_lynxce_site), external = true) { actions.onOpenUrl(LYNXCE_URL) } }
            }
            Spacer(Modifier.height(32.dp))
        }
    }

    when (picker) {
        Picker.Language -> ChoiceDialog(
            stringResource(R.string.settings_language), languages, language.first, actions.onLanguage,
        ) { picker = null }
        Picker.Appearance -> ChoiceDialog(
            stringResource(R.string.settings_appearance), appearances, state.settings.appearance, actions.onAppearance,
        ) { picker = null }
        Picker.TextSize -> ChoiceDialog(
            stringResource(R.string.settings_text_size), textSizes, state.settings.textSize, actions.onTextSize,
        ) { picker = null }
        Picker.SpeechRate -> ChoiceDialog(
            stringResource(R.string.settings_speech_rate), speechRates, state.settings.speechRate, actions.onSpeechRate,
        ) { picker = null }
        null -> Unit
    }
    if (confirmClear) {
        ConfirmDialog(
            title = stringResource(R.string.settings_clear_cache_confirm),
            text = stringResource(R.string.settings_clear_cache_footer),
            confirm = stringResource(R.string.settings_clear),
            onConfirm = actions.onClearCache,
            onDismiss = { confirmClear = false },
        )
    }
    if (confirmDelete) {
        ConfirmDialog(
            title = stringResource(R.string.settings_delete_account_confirm),
            text = stringResource(R.string.settings_delete_account_message),
            confirm = stringResource(R.string.settings_delete_account),
            onConfirm = actions.onDeleteAccount,
            onDismiss = { confirmDelete = false },
        )
    }
    if (confirmSignOut) {
        ConfirmDialog(
            title = stringResource(R.string.settings_sign_out_confirm),
            text = null,
            confirm = stringResource(R.string.settings_sign_out),
            onConfirm = actions.onSignOut,
            onDismiss = { confirmSignOut = false },
        )
    }
}

/** The account card at the top: Chief, the account name, where it's connected, and the Lynxce balance. */
@Composable
private fun AccountCard(name: String, connection: String, balance: BalanceState?, onBalance: () -> Unit, onRetry: () -> Unit) {
    val palette = LocalPalette.current
    Row(
        Modifier
            .padding(top = 8.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(22.dp))
            .background(palette.surface)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BotCharacter(Look.chief, 56.dp, seed = "chief")
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(name, style = MaterialTheme.typography.titleLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                connection,
                style = MaterialTheme.typography.bodyMedium,
                color = palette.secondary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            balance?.let {
                Spacer(Modifier.height(8.dp))
                val failed = it == BalanceState.Failed
                Row(
                    Modifier
                        .clip(CircleShape)
                        .clickable(onClick = if (failed) onRetry else onBalance)
                        .background(palette.raised)
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    BalanceText(
                        it,
                        style = MaterialTheme.typography.labelMedium,
                        format = { amount -> stringResource(R.string.settings_balance_chip, amount) },
                    )
                    if (failed) {
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.chat_retry), style = MaterialTheme.typography.labelMedium, color = SettingsLink)
                    }
                }
            }
        }
    }
}

/** Rows of one settings group; dividers go between them, not after the last. */
private class GroupRows {
    val rows = mutableListOf<@Composable () -> Unit>()
    fun row(content: @Composable () -> Unit) {
        rows += content
    }
}

@Composable
private fun Group(title: String?, footer: (@Composable () -> Unit)? = null, build: GroupRows.() -> Unit) {
    val palette = LocalPalette.current
    val rows = GroupRows().apply(build).rows
    Column(Modifier.padding(top = 22.dp)) {
        title?.let {
            Text(
                it,
                style = MaterialTheme.typography.labelLarge,
                color = palette.secondary,
                modifier = Modifier.padding(start = 16.dp, bottom = 6.dp),
            )
        }
        Column(Modifier.clip(RoundedCornerShape(18.dp)).background(palette.surface)) {
            rows.forEachIndexed { index, row ->
                if (index > 0) HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                row()
            }
        }
        footer?.invoke()
    }
}

@Composable
private fun FooterText(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = LocalPalette.current.secondary,
        modifier = Modifier.padding(start = 16.dp, top = 6.dp, end = 16.dp),
    )
}

/** "Version 0.1.0 (1)" with the update status on the right. */
@Composable
private fun VersionItem(update: UpdateState) {
    val palette = LocalPalette.current
    val offer = update.offer
    val status = when (val phase = update.phase) {
        UpdatePhase.Checking -> stringResource(R.string.update_status_checking)
        is UpdatePhase.Downloading -> if (phase.percent < 0) {
            stringResource(R.string.update_status_downloading_plain)
        } else {
            stringResource(R.string.update_status_downloading, phase.percent)
        }
        is UpdatePhase.DownloadFailed ->
            stringResource(if (phase.integrity) R.string.update_status_verify_failed else R.string.update_status_download_failed)
        UpdatePhase.CheckFailed -> stringResource(R.string.update_status_check_failed)
        is UpdatePhase.Ready -> stringResource(R.string.update_status_ready)
        UpdatePhase.UpToDate -> stringResource(R.string.update_status_latest)
        UpdatePhase.Idle -> offer?.let { stringResource(R.string.update_status_available, it.version) }
    }
    Row(
        Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column {
            Text(stringResource(R.string.settings_version), style = MaterialTheme.typography.bodyLarge, color = palette.text)
            Text(
                "${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})",
                style = MaterialTheme.typography.bodySmall,
                color = palette.secondary,
            )
        }
        Text(
            status.orEmpty(),
            style = MaterialTheme.typography.bodyLarge,
            color = if (offer != null && update.phase == UpdatePhase.Idle) SettingsLink else palette.secondary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.End,
            modifier = Modifier.weight(1f).padding(start = 12.dp),
        )
    }
}

/** "Update to X": downloads, verifies and installs; while downloading it shows progress and cancels. */
@Composable
private fun UpdateItem(version: String, phase: UpdatePhase, onUpdate: () -> Unit, onCancel: () -> Unit) {
    val palette = LocalPalette.current
    val downloading = phase as? UpdatePhase.Downloading
    Column(Modifier.fillMaxWidth().clickable(onClick = if (downloading != null) onCancel else onUpdate)) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 15.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                stringResource(R.string.update_install_to, version),
                style = MaterialTheme.typography.bodyLarge,
                color = SettingsLink,
                modifier = Modifier.weight(1f),
            )
            val action = when {
                downloading != null -> stringResource(R.string.common_cancel)
                phase is UpdatePhase.DownloadFailed -> stringResource(R.string.chat_retry)
                else -> null
            }
            action?.let { Text(it, style = MaterialTheme.typography.bodyLarge, color = palette.secondary) }
        }
        downloading?.let {
            val modifier = Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, bottom = 12.dp)
            if (it.percent < 0) {
                LinearProgressIndicator(modifier, color = SettingsGreen, trackColor = palette.hairline)
            } else {
                LinearProgressIndicator(
                    progress = { it.percent / 100f },
                    modifier = modifier,
                    color = SettingsGreen,
                    trackColor = palette.hairline,
                )
            }
        }
    }
}

/** A GitHub project with its star count, like the website's header. */
@Composable
private fun RepoItem(repo: GitHubStars.Repo, onClick: () -> Unit) {
    val palette = LocalPalette.current
    val context = LocalContext.current
    var stars by remember(repo.path) { mutableIntStateOf(GitHubStars.cached(context, repo)) }
    LaunchedEffect(repo.path) { GitHubStars.refresh(context, repo)?.let { stars = it } }
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(repo.name, style = MaterialTheme.typography.bodyLarge, color = palette.text)
            Text(repo.path, style = MaterialTheme.typography.bodySmall, color = palette.secondary)
        }
        Row(
            Modifier.clip(CircleShape).background(palette.raised).padding(horizontal = 8.dp, vertical = 3.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Rounded.Star, contentDescription = null, tint = palette.text, modifier = Modifier.size(13.dp))
            Spacer(Modifier.width(3.dp))
            Text(GitHubStars.format(stars), style = MaterialTheme.typography.labelMedium, color = palette.text)
        }
        Spacer(Modifier.width(8.dp))
        Icon(Icons.AutoMirrored.Rounded.OpenInNew, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(18.dp))
    }
}

@Composable
private fun Item(
    title: String,
    value: String? = null,
    chevron: Boolean = false,
    external: Boolean = false,
    danger: Boolean = false,
    valueColor: Color? = null,
    onClick: (() -> Unit)? = null,
) {
    val palette = LocalPalette.current
    Row(
        Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 15.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            title,
            style = MaterialTheme.typography.bodyLarge,
            color = if (danger) MaterialTheme.colorScheme.error else palette.text,
            modifier = if (value == null) Modifier.weight(1f) else Modifier,
        )
        // The value takes the rest of the row, right-aligned, and ellipsizes when long.
        value?.let {
            Text(
                it,
                style = MaterialTheme.typography.bodyLarge,
                color = valueColor ?: palette.secondary,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                textAlign = TextAlign.End,
                modifier = Modifier.weight(1f).padding(start = 12.dp),
            )
        }
        if (chevron) Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = palette.secondary)
        if (external) Icon(Icons.AutoMirrored.Rounded.OpenInNew, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(18.dp))
    }
}

@Composable
private fun Toggle(title: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(title, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            // Settings stay neutral: a system green switch, not the brand pink.
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = SettingsGreen,
                checkedBorderColor = SettingsGreen,
            ),
        )
    }
}

@Composable
private fun <T> ChoiceDialog(title: String, options: List<Pair<T, String>>, selected: T, onPick: (T) -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                options.forEach { (option, label) ->
                    ChoiceRow(label, option == selected) {
                        onDismiss()
                        if (option != selected) onPick(option)
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) } },
    )
}

@Composable
private fun ChoiceRow(name: String, selected: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable(onClick = onClick).padding(vertical = 12.dp, horizontal = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(name, style = MaterialTheme.typography.bodyLarge, color = LocalPalette.current.text, modifier = Modifier.weight(1f))
        if (selected) Icon(Icons.Rounded.Check, contentDescription = null, tint = LocalPalette.current.text)
    }
}

@Composable
private fun ConfirmDialog(title: String, text: String?, confirm: String, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title, style = MaterialTheme.typography.titleMedium) },
        text = text?.let { { Text(it) } },
        confirmButton = {
            TextButton(onClick = { onDismiss(); onConfirm() }) { Text(confirm, color = MaterialTheme.colorScheme.error) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) } },
    )
}

/** Settings → Model (Lynxce mode): "Auto" first, then every model; a checkmark on the current one. */
@Composable
fun ModelPickerScreen(model: AppViewModel, onBack: () -> Unit) {
    val models by model.models.collectAsStateWithLifecycle()
    val settings by model.settings.collectAsStateWithLifecycle()
    ModelPicker(models, settings.model, onBack) { id ->
        model.setModel(id)
        onBack()
    }
}

@Composable
fun ModelPicker(models: List<ModelOption>, selected: String?, onBack: () -> Unit, onPick: (String?) -> Unit) {
    val palette = LocalPalette.current
    val options = listOf<ModelOption?>(null) + models
    Column(Modifier.fillMaxSize()) {
        TopBar(leading = { BackButton(onBack) }) { TopBarTitle(stringResource(R.string.settings_model)) }
        LazyColumn(Modifier.weight(1f).padding(horizontal = 16.dp).navigationBarsPadding()) {
            item {
                Spacer(Modifier.height(8.dp))
            }
            items(options, key = { it?.id ?: "auto" }) { option ->
                val first = option == null
                val last = option == options.last()
                val shape = RoundedCornerShape(
                    topStart = if (first) 18.dp else 0.dp,
                    topEnd = if (first) 18.dp else 0.dp,
                    bottomStart = if (last) 18.dp else 0.dp,
                    bottomEnd = if (last) 18.dp else 0.dp,
                )
                Column(Modifier.clip(shape).background(palette.surface)) {
                    if (!first) HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                    Row(
                        Modifier
                            .fillMaxWidth()
                            .clickable { onPick(option?.id) }
                            .padding(horizontal = 16.dp, vertical = 15.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(
                            option?.name ?: stringResource(R.string.settings_model_auto),
                            style = MaterialTheme.typography.bodyLarge,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.weight(1f),
                        )
                        if (option?.id == selected) {
                            Icon(Icons.Rounded.Check, contentDescription = null, tint = palette.text)
                        } else {
                            Spacer(Modifier.size(24.dp))
                        }
                    }
                }
            }
            item { FooterText(stringResource(R.string.settings_model_footer)) }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 1400)
@Composable
private fun SettingsPreview() {
    OctopTheme(dark = true) {
        Settings(
            state = SettingsState(
                accountName = "Alex",
                balance = BalanceState.Value(128.5),
                lynxce = true,
                host = "api.lynxce.cn",
                serverAddress = null,
                models = emptyList(),
                settings = UserSettings(),
                language = AppLocale.SYSTEM,
                notificationsBlocked = true,
            ),
            actions = SettingsActions({}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}, {}),
        )
    }
}

@Preview(showBackground = true, backgroundColor = 0xFFFFFFFF)
@Composable
private fun ModelPickerPreview() {
    OctopTheme(dark = false) {
        ModelPicker(
            models = listOf(ModelOption("deepseek-v3", "DeepSeek V3", false), ModelOption("qwen-vl", "Qwen VL", true)),
            selected = "deepseek-v3",
            onBack = {},
            onPick = {},
        )
    }
}

/** iOS-style system green for switches and blue for links, so settings never wear the brand pink. */
private val SettingsGreen = Color(0xFF34C759)
private val SettingsLink = Color(0xFF0A84FF)
