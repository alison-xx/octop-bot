package io.github.alisonxx.octopbot.ui.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.OctopApplication
import io.github.alisonxx.octopbot.app.describe
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.net.ServerProtocol
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.TopBarTitle
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import kotlinx.coroutines.launch

private enum class Step { Address, Lynxce, Unsupported }

/** URL → probe (https, then http when no scheme was typed) → Lynxce sign-in, the only way in. */
@Composable
fun ServerConnectScreen(onBack: () -> Unit, onConnected: (ServerBackend) -> Unit) {
    val resources = LocalResources.current
    val context = LocalContext.current
    val store = remember(context) { (context.applicationContext as OctopApplication).store }
    val scope = rememberCoroutineScope()
    var step by rememberSaveable { mutableStateOf(Step.Address) }
    var address by rememberSaveable { mutableStateOf("") }
    var base by rememberSaveable { mutableStateOf("") }
    var unclaimed by rememberSaveable { mutableStateOf(false) }
    // A multi-tenant server (Octop Bot cloud): any Lynxce account signs in, there is no owner.
    var multiTenant by rememberSaveable { mutableStateOf(false) }
    val lynxce = rememberLynxceSignInState()
    // Set up earlier with a local password: asked once, to bind the Lynxce owner.
    var legacy by rememberSaveable { mutableStateOf(false) }
    var legacyPassword by rememberSaveable { mutableStateOf("") }
    var busy by rememberSaveable { mutableStateOf(false) }
    var error by rememberSaveable { mutableStateOf<String?>(null) }
    val focus = remember { FocusRequester() }

    LaunchedEffect(Unit) {
        if (address.isEmpty()) store.lastServer()?.let { address = it }
    }
    // After probing, the first field of the sign-in step takes focus.
    LaunchedEffect(step) {
        if (step != Step.Address) runCatching { focus.requestFocus() }
    }

    fun run(describe: (Throwable) -> String = { resources.describe(it) }, action: suspend () -> Unit) {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            runCatching { action() }.onFailure { error = describe(it) }
            busy = false
        }
    }

    fun next() {
        when (step) {
            Step.Address -> {
                if (ServerProtocol.normalizeUrl(address) == null) {
                    error = resources.getString(R.string.server_address_invalid)
                    return
                }
                run {
                    val probe = ServerBackend.probe(address.trim())
                    store.setLastServer(address.trim())
                    base = probe.base
                    lynxce.password = ""
                    legacyPassword = ""
                    val mode = probe.mode
                    unclaimed = mode is ServerBackend.Companion.SignInMode.Lynxce && !mode.claimed
                    multiTenant = mode is ServerBackend.Companion.SignInMode.Lynxce && mode.cloud
                    legacy = mode == ServerBackend.Companion.SignInMode.Legacy
                    step = if (mode == ServerBackend.Companion.SignInMode.Unsupported) Step.Unsupported else Step.Lynxce
                }
            }
            // The server localizes its own errors (wrong code, owner mismatch, throttling), so its message wins.
            Step.Lynxce -> run({ failure ->
                lynxce.signInFailed(failure)
                resources.describeLynxce(failure, serverMessageFirst = true)
            }) {
                if (!lynxce.canSubmit) return@run
                val old = legacyPassword.takeIf { legacy }
                val backend = if (lynxce.useCode) {
                    ServerBackend.signInWithLynxceCode(base, lynxce.account, lynxce.code, store, old)
                } else {
                    ServerBackend.signInWithLynxce(base, lynxce.account.trim(), lynxce.password, store, old)
                }
                onConnected(backend)
            }
            Step.Unsupported -> Unit
        }
    }

    val ready = !busy && when (step) {
        Step.Address -> address.isNotBlank()
        Step.Lynxce -> lynxce.canSubmit && (!legacy || legacyPassword.isNotEmpty())
        Step.Unsupported -> false
    }

    Column(Modifier.fillMaxSize().imePadding()) {
        TopBar(leading = {
            BackButton {
                if (step == Step.Address) onBack() else {
                    step = Step.Address
                    error = null
                }
            }
        }) { TopBarTitle(stringResource(R.string.server_title)) }
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            when (step) {
                Step.Address -> {
                    FormField(
                        value = address,
                        onValueChange = { address = it },
                        label = stringResource(R.string.server_address),
                        placeholder = stringResource(R.string.server_address_placeholder),
                        keyboardType = KeyboardType.Uri,
                        imeAction = ImeAction.Go,
                        onDone = ::next,
                        enabled = !busy,
                    )
                    Hint(stringResource(R.string.server_address_footer))
                }
                Step.Lynxce -> {
                    Text(base, style = MaterialTheme.typography.titleMedium)
                    Hint(stringResource(if (multiTenant) R.string.server_sign_in_lynxce_cloud else R.string.server_sign_in_lynxce))
                    if (unclaimed) Hint(stringResource(R.string.server_unclaimed))
                    if (legacy) {
                        Hint(stringResource(R.string.server_legacy_hint))
                        FormField(
                            value = legacyPassword,
                            onValueChange = { legacyPassword = it },
                            label = stringResource(R.string.server_legacy_password),
                            password = true,
                            enabled = !busy,
                        )
                    }
                    LynxceSignInFields(
                        state = lynxce,
                        busy = busy,
                        error = error,
                        onError = { error = it },
                        onRequestCode = { ServerBackend.requestLynxceCode(base, it.value) },
                        onSubmit = ::next,
                        modifier = Modifier.focusRequester(focus),
                        serverMessageFirst = true,
                    )
                    LynxceModeSwitch(lynxce, busy, onSwitched = { error = null }, modifier = Modifier.align(Alignment.CenterHorizontally))
                }
                Step.Unsupported -> {
                    Text(base, style = MaterialTheme.typography.titleMedium)
                    Hint(stringResource(R.string.server_unsupported))
                }
            }
            // The Lynxce fields show their own error line.
            if (step != Step.Lynxce) error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
        }
        Button(
            onClick = ::next,
            enabled = ready,
            modifier = Modifier
                .navigationBarsPadding()
                .padding(horizontal = 24.dp, vertical = 16.dp)
                .fillMaxWidth()
                .height(52.dp),
        ) {
            if (busy) {
                CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
            } else {
                Text(
                    stringResource(
                        if (step == Step.Address) R.string.server_next else R.string.onboarding_sign_in,
                    ),
                    style = MaterialTheme.typography.titleMedium,
                )
            }
        }
    }
}

@Composable
private fun Hint(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = LocalPalette.current.secondary)
}

@Preview(showBackground = true, backgroundColor = 0xFF000000)
@Composable
private fun ServerConnectPreview() {
    OctopTheme(dark = true) { ServerConnectScreen(onBack = {}, onConnected = {}) }
}
