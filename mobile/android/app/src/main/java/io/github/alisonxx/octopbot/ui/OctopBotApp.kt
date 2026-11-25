package io.github.alisonxx.octopbot.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.UriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.AttachmentFiles
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.net.ServerProtocol
import io.github.alisonxx.octopbot.ui.chat.ChatScreen
import io.github.alisonxx.octopbot.ui.common.ProvideUiPrefs
import io.github.alisonxx.octopbot.ui.editor.BotActivityScreen
import io.github.alisonxx.octopbot.ui.editor.BotEditorScreen
import io.github.alisonxx.octopbot.ui.group.GroupRoomScreen
import io.github.alisonxx.octopbot.ui.home.HomeScreen
import io.github.alisonxx.octopbot.ui.onboarding.OnboardingScreen
import io.github.alisonxx.octopbot.ui.onboarding.ServerConnectScreen
import io.github.alisonxx.octopbot.ui.settings.CreditsScreen
import io.github.alisonxx.octopbot.ui.settings.ModelSetupScreen
import io.github.alisonxx.octopbot.ui.settings.ModelSourcesScreen
import io.github.alisonxx.octopbot.ui.settings.SettingsScreen
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import io.github.alisonxx.octopbot.ui.voice.VoiceScreen
import io.github.alisonxx.octopbot.update.ApkInstaller
import java.io.File
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

private object Routes {
    const val ONBOARDING = "onboarding"
    const val SERVER = "server"
    const val MODEL_SETUP = "models/setup"
    const val HOME = "home"
    const val CHAT = "chat/{bot}"
    const val EDITOR = "editor?bot={bot}"
    const val ACTIVITY = "activity/{bot}"
    const val VOICE = "voice/{bot}"
    const val GROUP = "group/{group}"
    const val SETTINGS = "settings"
    const val MODELS = "settings/model"
    const val CREDITS = "settings/credits"

    fun chat(bot: String) = "chat/$bot"
    fun editor(bot: String?) = if (bot == null) "editor" else "editor?bot=$bot"
    fun activity(bot: String) = "activity/$bot"
    fun voice(bot: String) = "voice/$bot"
    fun group(group: String) = "group/$group"
}

/**
 * Pop one screen, but never the start destination: a double tap on a back button (or Escape) would otherwise
 * leave an empty NavHost. On the root screen, system back leaves the app as usual (the NavHost doesn't handle it).
 */
private fun NavHostController.back() {
    if (previousBackStackEntry != null) popBackStack()
}

@Composable
fun OctopBotApp(model: AppViewModel, openBot: MutableStateFlow<io.github.alisonxx.octopbot.NotificationChat?>) {
    val settings by model.settings.collectAsStateWithLifecycle()
    OctopTheme {
        ProvideUiPrefs(settings) {
            val session by model.session.collectAsStateWithLifecycle()
            val snackbar = remember { SnackbarHostState() }
            LaunchedEffect(model) {
                model.notices.collect {
                    // A newer message replaces the one on screen.
                    snackbar.currentSnackbarData?.dismiss()
                    launch { snackbar.showSnackbar(it, duration = SnackbarDuration.Short) }
                }
            }
            // Launch art until the session is restored and the directory loaded (at most 1.2 s), then a crossfade.
            var launched by rememberSaveable { mutableStateOf(false) }
            LaunchedEffect(Unit) {
                withTimeoutOrNull(1_200) { model.launchReady.first { it } }
                launched = true
            }
            Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                Crossfade(targetState = launched && session != SessionState.Loading, animationSpec = tween(350), label = "launch") { ready ->
                    if (!ready) {
                        LaunchScreen()
                    } else {
                        when (val state = session) {
                            SessionState.Loading -> Unit
                            is SessionState.SignedOut -> SignedOutNav(model, state.notice, state.reopenServer)
                            is SessionState.Ready -> {
                                // Files a Bot links to live on its server; open them with this account's access.
                                val context = LocalContext.current
                                val system = LocalUriHandler.current
                                val files = remember(model, system) {
                                    object : UriHandler {
                                        override fun openUri(uri: String) {
                                            if (!ServerProtocol.isWorkspaceDownload(uri)) return system.openUri(uri)
                                            model.openWorkspaceFile(uri) { file, mime -> AttachmentFiles.openWith(context, file, mime) }
                                        }
                                    }
                                }
                                CompositionLocalProvider(LocalUriHandler provides files) { SignedInNav(model, openBot) }
                            }
                        }
                    }
                }
                // Above the floating composer. Errors hide after 4 s (Short) or on tap.
                SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 80.dp)) { data ->
                    Snackbar(
                        data,
                        containerColor = LocalPalette.current.raised,
                        contentColor = LocalPalette.current.text,
                        modifier = Modifier.clickable { data.dismiss() },
                    )
                }
            }
        }
    }
}

@Composable
private fun SignedOutNav(model: AppViewModel, notice: String?, reopenServer: Boolean) {
    val nav = rememberNavController()
    // "Switch account or server" from a server: straight to the server form (it fills in the address).
    LaunchedEffect(reopenServer) { if (reopenServer) nav.navigate(Routes.SERVER) }
    NavHost(nav, startDestination = Routes.ONBOARDING) {
        composable(Routes.ONBOARDING) {
            OnboardingScreen(
                notice = notice,
                onSignIn = model::signInLynxce,
                onRequestCode = model::requestLynxceCode,
                onCodeSignIn = model::signInLynxceCode,
                onOwnModel = { nav.navigate(Routes.MODEL_SETUP) },
                onServer = { nav.navigate(Routes.SERVER) },
            )
        }
        composable(Routes.MODEL_SETUP) {
            ModelSetupScreen(model.phoneModels, onBack = { nav.back() }, onStart = model::usePhoneOnly)
        }
        composable(Routes.SERVER) {
            ServerConnectScreen(onBack = { nav.back() }, onConnected = model::useServer)
        }
    }
}

@Composable
private fun SignedInNav(model: AppViewModel, openBot: MutableStateFlow<io.github.alisonxx.octopbot.NotificationChat?>) {
    val nav = rememberNavController()
    val pending by openBot.collectAsState()
    val directory by model.bots.collectAsState()
    LaunchedEffect(pending, directory) {
        val target = pending ?: return@LaunchedEffect
        if (directory.isEmpty()) return@LaunchedEffect
        try {
            if (model.openNotification(target.botId, target.threadId))
                nav.navigate(Routes.chat(target.botId)) { popUpTo(Routes.HOME) }
        } catch (error: kotlinx.coroutines.CancellationException) {
            throw error
        } catch (_: Exception) {
            // An unavailable or removed conversation leaves the signed-in directory on screen.
        }
        openBot.value = null
    }
    AskForNotifications(model)
    InstallUpdates(model)
    // Back from the recharge Custom Tab: show the new balance.
    LifecycleResumeEffect(model) {
        model.appResumed()
        onPauseOrDispose {}
    }
    NavHost(nav, startDestination = Routes.HOME) {
        composable(Routes.HOME) {
            HomeScreen(
                model = model,
                onOpenBot = { nav.navigate(Routes.chat(it)) },
                onOpenGroup = { nav.navigate(Routes.group(it)) },
                onEditBot = { nav.navigate(Routes.editor(it)) },
                onNewBot = { nav.navigate(Routes.editor(null)) },
                onSettings = { nav.navigate(Routes.SETTINGS) },
                onCredits = { nav.navigate(Routes.CREDITS) },
                onVoice = { nav.navigate(Routes.voice(it)) },
            )
        }
        composable(Routes.CHAT, listOf(navArgument("bot") { type = NavType.StringType })) { entry ->
            val bot = entry.arguments?.getString("bot").orEmpty()
            ChatScreen(
                model = model,
                botId = bot,
                onBack = { nav.back() },
                onEditBot = { nav.navigate(Routes.editor(bot)) },
                onVoice = { nav.navigate(Routes.voice(bot)) },
            )
        }
        composable(
            Routes.EDITOR,
            listOf(navArgument("bot") { type = NavType.StringType; nullable = true; defaultValue = null }),
        ) { entry ->
            BotEditorScreen(
                model,
                entry.arguments?.getString("bot"),
                onDone = { nav.back() },
                onActivity = { nav.navigate(Routes.activity(it)) },
            )
        }
        composable(Routes.ACTIVITY, listOf(navArgument("bot") { type = NavType.StringType })) { entry ->
            BotActivityScreen(model, entry.arguments?.getString("bot").orEmpty(), onBack = { nav.back() })
        }
        composable(Routes.VOICE, listOf(navArgument("bot") { type = NavType.StringType })) { entry ->
            VoiceScreen(model, entry.arguments?.getString("bot").orEmpty(), onClose = { nav.back() })
        }
        composable(Routes.GROUP, listOf(navArgument("group") { type = NavType.StringType })) { entry ->
            GroupRoomScreen(model, entry.arguments?.getString("group").orEmpty(), onBack = { nav.back() })
        }
        composable(Routes.SETTINGS) {
            SettingsScreen(
                model = model,
                onBack = { nav.back() },
                onModels = { nav.navigate(Routes.MODELS) },
                onCredits = { nav.navigate(Routes.CREDITS) },
            )
        }
        composable(Routes.CREDITS) {
            CreditsScreen(model, onBack = { nav.back() })
        }
        composable(Routes.MODELS) {
            ModelSourcesScreen(model, onBack = { nav.back() }, onCredits = { nav.navigate(Routes.CREDITS) })
        }
    }
}

/** Ask once for POST_NOTIFICATIONS (Android 13+) while reply notifications are on. */
@Composable
private fun AskForNotifications(model: AppViewModel) {
    if (Build.VERSION.SDK_INT < 33) return
    val settings by model.settings.collectAsStateWithLifecycle()
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(settings.notifications) {
        if (settings.notifications) launcher.launch(Manifest.permission.POST_NOTIFICATIONS)
    }
}

/**
 * Hands each verified update APK to the system installer. Without the "install unknown apps" permission it
 * explains, opens that system page, and continues when the user comes back with it granted.
 */
@Composable
private fun InstallUpdates(model: AppViewModel) {
    val context = LocalContext.current
    var waiting by remember { mutableStateOf<File?>(null) }
    var explain by remember { mutableStateOf(false) }
    fun install(apk: File) {
        runCatching { context.startActivity(ApkInstaller.installIntent(context, apk)) }
    }
    LaunchedEffect(model) {
        model.updateInstalls.collect { apk ->
            if (ApkInstaller.canInstall(context)) {
                install(apk)
            } else {
                waiting = apk
                explain = true
            }
        }
    }
    LifecycleResumeEffect(waiting) {
        val apk = waiting
        if (apk != null && !explain && ApkInstaller.canInstall(context)) {
            waiting = null
            install(apk)
        }
        onPauseOrDispose {}
    }
    if (explain) {
        AlertDialog(
            onDismissRequest = { explain = false; waiting = null },
            title = { Text(stringResource(R.string.update_permission_title), style = MaterialTheme.typography.titleLarge) },
            text = { Text(stringResource(R.string.update_permission_text)) },
            confirmButton = {
                TextButton(onClick = {
                    explain = false
                    runCatching { context.startActivity(ApkInstaller.unknownSourcesIntent(context)) }
                }) { Text(stringResource(R.string.update_permission_open)) }
            },
            dismissButton = {
                TextButton(onClick = { explain = false; waiting = null }) { Text(stringResource(R.string.common_cancel)) }
            },
        )
    }
}
