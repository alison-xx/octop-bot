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

private enum class Step { Address, Lynxce, LocalPassword, Password, Mfa }

/** URL → probe (https, then http when no scheme was typed) → Lynxce or password sign-in → optional TOTP. */
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
    var account by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var mfaToken by rememberSaveable { mutableStateOf("") }
    var code by rememberSaveable { mutableStateOf("") }
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

    fun run(action: suspend () -> Unit) {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            runCatching { action() }.onFailure { error = resources.describe(it) }
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
                    password = ""
                    step = when (val mode = probe.mode) {
                        is ServerBackend.Companion.SignInMode.Lynxce -> {
                            unclaimed = !mode.claimed
                            Step.Lynxce
                        }
                        ServerBackend.Companion.SignInMode.LocalPassword -> Step.LocalPassword
                        ServerBackend.Companion.SignInMode.Password -> Step.Password
                    }
                }
            }
            Step.Lynxce -> run { onConnected(ServerBackend.signInWithLynxce(base, account.trim(), password, store)) }
            Step.LocalPassword, Step.Password -> run {
                val username = if (step == Step.LocalPassword) "local" else account.trim()
                when (val result = ServerBackend.signIn(base, username, password, store)) {
                    is ServerBackend.Companion.SignIn.Done -> onConnected(result.backend)
                    is ServerBackend.Companion.SignIn.NeedsMfa -> {
                        mfaToken = result.mfaToken
                        step = Step.Mfa
                    }
                }
            }
            Step.Mfa -> run { onConnected(ServerBackend.verifyMfa(base, mfaToken, code.trim(), store)) }
        }
    }

    val ready = !busy && when (step) {
        Step.Address -> address.isNotBlank()
        Step.Lynxce, Step.Password -> account.isNotBlank() && password.isNotEmpty()
        Step.LocalPassword -> password.isNotEmpty()
        Step.Mfa -> code.trim().length >= 6
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
                Step.Lynxce, Step.Password -> {
                    Text(base, style = MaterialTheme.typography.titleMedium)
                    if (step == Step.Lynxce) {
                        Hint(stringResource(R.string.server_sign_in_lynxce))
                        if (unclaimed) Hint(stringResource(R.string.server_unclaimed))
                    } else {
                        Hint(stringResource(R.string.server_sign_in_password))
                    }
                    FormField(
                        value = account,
                        onValueChange = { account = it },
                        label = stringResource(if (step == Step.Lynxce) R.string.onboarding_account else R.string.server_username),
                        keyboardType = if (step == Step.Lynxce) KeyboardType.Email else KeyboardType.Text,
                        enabled = !busy,
                        modifier = Modifier.focusRequester(focus),
                    )
                    FormField(
                        value = password,
                        onValueChange = { password = it },
                        label = stringResource(R.string.onboarding_password),
                        password = true,
                        imeAction = ImeAction.Go,
                        onDone = ::next,
                        enabled = !busy,
                    )
                }
                Step.LocalPassword -> {
                    Text(base, style = MaterialTheme.typography.titleMedium)
                    Hint(stringResource(R.string.server_sign_in_local))
                    FormField(
                        value = password,
                        onValueChange = { password = it },
                        label = stringResource(R.string.onboarding_password),
                        password = true,
                        imeAction = ImeAction.Go,
                        onDone = ::next,
                        enabled = !busy,
                        modifier = Modifier.focusRequester(focus),
                    )
                }
                Step.Mfa -> {
                    Hint(stringResource(R.string.server_mfa_hint))
                    FormField(
                        value = code,
                        onValueChange = { value -> code = value.filter { it.isDigit() }.take(8) },
                        label = stringResource(R.string.server_mfa),
                        keyboardType = KeyboardType.NumberPassword,
                        imeAction = ImeAction.Go,
                        onDone = ::next,
                        enabled = !busy,
                        modifier = Modifier.focusRequester(focus),
                    )
                }
            }
            error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
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
                        when (step) {
                            Step.Address -> R.string.server_next
                            Step.Mfa -> R.string.server_verify
                            else -> R.string.onboarding_sign_in
                        },
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
