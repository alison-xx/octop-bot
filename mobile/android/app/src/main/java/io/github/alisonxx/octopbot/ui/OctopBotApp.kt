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
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.ui.chat.ChatScreen
import io.github.alisonxx.octopbot.ui.editor.BotEditorScreen
import io.github.alisonxx.octopbot.ui.group.GroupRoomScreen
import io.github.alisonxx.octopbot.ui.home.HomeScreen
import io.github.alisonxx.octopbot.ui.onboarding.OnboardingScreen
import io.github.alisonxx.octopbot.ui.onboarding.ServerConnectScreen
import io.github.alisonxx.octopbot.ui.settings.SettingsScreen
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

    fun chat(bot: String) = "chat/$bot"
    fun editor(bot: String?) = if (bot == null) "editor" else "editor?bot=$bot"
    fun voice(bot: String) = "voice/$bot"
    fun group(group: String) = "group/$group"
}

@Composable
fun OctopBotApp(model: AppViewModel, openBot: MutableStateFlow<String?>) {
    OctopTheme {
        val session by model.session.collectAsStateWithLifecycle()
        val snackbar = remember { SnackbarHostState() }
        LaunchedEffect(model) { model.notices.collect { snackbar.showSnackbar(it) } }
        Box(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
            when (val state = session) {
                SessionState.Loading -> Unit
                is SessionState.SignedOut -> SignedOutNav(model, state.notice)
                is SessionState.Ready -> SignedInNav(model, openBot)
            }
            // Above the floating composer.
            SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(bottom = 80.dp))
        }
    }
}

@Composable
private fun SignedOutNav(model: AppViewModel, notice: String?) {
    val nav = rememberNavController()
    NavHost(nav, startDestination = Routes.ONBOARDING) {
        composable(Routes.ONBOARDING) {
            OnboardingScreen(
                notice = notice,
                onSignIn = model::signInLynxce,
                onServer = { nav.navigate(Routes.SERVER) },
            )
        }
        composable(Routes.SERVER) {
            ServerConnectScreen(onBack = { nav.popBackStack() }, onConnected = model::useServer)
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
                onBack = { nav.popBackStack() },
                onEditBot = { nav.navigate(Routes.editor(bot)) },
                onVoice = { nav.navigate(Routes.voice(bot)) },
            )
        }
        composable(
            Routes.EDITOR,
            listOf(navArgument("bot") { type = NavType.StringType; nullable = true; defaultValue = null }),
        ) { entry ->
            BotEditorScreen(model, entry.arguments?.getString("bot"), onDone = { nav.popBackStack() })
        }
        composable(Routes.VOICE, listOf(navArgument("bot") { type = NavType.StringType })) { entry ->
            VoiceScreen(model, entry.arguments?.getString("bot").orEmpty(), onClose = { nav.popBackStack() })
        }
        composable(Routes.GROUP, listOf(navArgument("group") { type = NavType.StringType })) { entry ->
            GroupRoomScreen(model, entry.arguments?.getString("group").orEmpty(), onBack = { nav.popBackStack() })
        }
        composable(Routes.SETTINGS) {
            SettingsScreen(
                model = model,
                onBack = { nav.popBackStack() },
                onConnectServer = { nav.navigate(Routes.SERVER) },
            )
        }
        composable(Routes.SERVER) {
            ServerConnectScreen(
                onBack = { nav.popBackStack() },
                onConnected = { backend: ServerBackend -> model.useServer(backend) },
            )
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
