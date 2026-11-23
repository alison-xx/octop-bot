package io.github.alisonxx.octopbot.ui.onboarding

import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.describe
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import kotlinx.coroutines.launch

/** Lynxce account sign-in (the default path) with a way to a self-hosted server instead. */
@Composable
fun OnboardingScreen(notice: String?, onSignIn: suspend (String, String) -> Unit, onServer: () -> Unit) {
    val palette = LocalPalette.current
    val resources = LocalResources.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var account by rememberSaveable { mutableStateOf("") }
    var password by rememberSaveable { mutableStateOf("") }
    var busy by rememberSaveable { mutableStateOf(false) }
    var error by rememberSaveable { mutableStateOf(notice) }
    val ready = account.isNotBlank() && password.isNotEmpty() && !busy

    fun submit() {
        if (!ready) return
        busy = true
        error = null
        scope.launch {
            runCatching { onSignIn(account.trim(), password) }.onFailure { error = resources.describe(it) }
            busy = false
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(48.dp))
        BotCharacter(Look.chief, 136.dp, motion = if (busy) BotMotion.Working else BotMotion.Idle, seed = "chief")
        Spacer(Modifier.height(16.dp))
        Text("Octop Bot", style = MaterialTheme.typography.headlineLarge)
        Spacer(Modifier.height(6.dp))
        Text(
            stringResource(R.string.onboarding_tagline),
            style = MaterialTheme.typography.bodyLarge,
            color = palette.secondary,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(36.dp))
        Column(Modifier.widthIn(max = 420.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(stringResource(R.string.onboarding_lynxce), style = MaterialTheme.typography.titleMedium)
            FormField(
                value = account,
                onValueChange = { account = it },
                label = stringResource(R.string.onboarding_account),
                keyboardType = KeyboardType.Email,
                enabled = !busy,
            )
            FormField(
                value = password,
                onValueChange = { password = it },
                label = stringResource(R.string.onboarding_password),
                password = true,
                imeAction = ImeAction.Go,
                onDone = ::submit,
                enabled = !busy,
            )
            error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
            Button(onClick = ::submit, enabled = ready, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                if (busy) {
                    CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                } else {
                    Text(stringResource(R.string.onboarding_sign_in), style = MaterialTheme.typography.titleMedium)
                }
            }
            TextButton(
                onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, "https://lynxce.cn".toUri())) },
                modifier = Modifier.align(Alignment.CenterHorizontally),
            ) { Text(stringResource(R.string.onboarding_register), color = palette.secondary) }
        }
        Spacer(Modifier.height(32.dp))
        TextButton(onClick = onServer, enabled = !busy) {
            Text(stringResource(R.string.onboarding_server), style = MaterialTheme.typography.titleSmall)
        }
        Text(
            stringResource(R.string.onboarding_footnote),
            style = MaterialTheme.typography.bodySmall,
            color = palette.secondary,
            textAlign = TextAlign.Center,
            modifier = Modifier.widthIn(max = 360.dp).padding(bottom = 16.dp),
        )
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF000000)
@Composable
private fun OnboardingPreview() {
    OctopTheme(dark = true) { OnboardingScreen(notice = null, onSignIn = { _, _ -> }, onServer = {}) }
}
