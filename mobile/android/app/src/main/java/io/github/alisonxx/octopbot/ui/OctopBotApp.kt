package io.github.alisonxx.octopbot.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.ui.unit.dp
import androidx.compose.material3.MaterialTheme
import androidx.compose.foundation.clickable
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.animation.Crossfade
import androidx.compose.animation.core.tween
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.withTimeoutOrNull
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.ui.chat.ChatScreen
import io.github.alisonxx.octopbot.ui.editor.BotEditorScreen
import io.github.alisonxx.octopbot.ui.group.GroupRoomScreen
import io.github.alisonxx.octopbot.ui.home.HomeScreen
import io.github.alisonxx.octopbot.ui.onboarding.OnboardingScreen
import io.github.alisonxx.octopbot.ui.onboarding.ServerConnectScreen
import io.github.alisonxx.octopbot.ui.settings.ModelPickerScreen
import io.github.alisonxx.octopbot.ui.settings.SettingsScreen
import io.github.alisonxx.octopbot.ui.common.ProvideUiPrefs
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.launch
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import io.github.alisonxx.octopbot.ui.voice.VoiceScreen
import kotlinx.coroutines.flow.MutableStateFlow

private object Routes {
    const val ONBOARDING = "onboarding"
    const val SERVER = "server"
    const val HOME = "home"
    const val CHAT = "chat/{bot}"
    const val EDITOR = "editor?bot={bot}"
    const val VOICE = "voice/{bot}"
    const val GROUP = "group/{group}"
    const val SETTINGS = "settings"
    const val MODELS = "settings/model"

    fun chat(bot: String) = "chat/$bot"
    fun editor(bot: String?) = if (bot == null) "editor" else "editor?bot=$bot"
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
fun OctopBotApp(model: AppViewModel, openBot: MutableStateFlow<String?>) {
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
                            is SessionState.Ready -> SignedInNav(model, openBot)
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
                onServer = { nav.navigate(Routes.SERVER) },
            )
        }
        composable(Routes.SERVER) {
            ServerConnectScreen(onBack = { nav.back() }, onConnected = model::useServer)
        }
    }
}

@Composable
private fun SignedInNav(model: AppViewModel, openBot: MutableStateFlow<String?>) {
    val nav = rememberNavController()
    val pending by openBot.collectAsState()
    LaunchedEffect(pending) {
        val bot = pending ?: return@LaunchedEffect
        openBot.value = null
        nav.navigate(Routes.chat(bot)) { popUpTo(Routes.HOME) }
    }
    AskForNotifications(model)
    NavHost(nav, startDestination = Routes.HOME) {
        composable(Routes.HOME) {
            HomeScreen(
                model = model,
                onOpenBot = { nav.navigate(Routes.chat(it)) },
                onOpenGroup = { nav.navigate(Routes.group(it)) },
                onEditBot = { nav.navigate(Routes.editor(it)) },
                onNewBot = { nav.navigate(Routes.editor(null)) },
                onSettings = { nav.navigate(Routes.SETTINGS) },
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
            BotEditorScreen(model, entry.arguments?.getString("bot"), onDone = { nav.back() })
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
            )
        }
        composable(Routes.MODELS) {
            ModelPickerScreen(model, onBack = { nav.back() })
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
