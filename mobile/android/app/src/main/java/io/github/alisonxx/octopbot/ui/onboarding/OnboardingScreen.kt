package io.github.alisonxx.octopbot.ui.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import io.github.alisonxx.octopbot.ui.settings.VendorLogo
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
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.fromHtml
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.net.LynxceProtocol
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import kotlinx.coroutines.launch

/**
 * Start page: the Lynxce account first (code or password, as tabs), then "use without signing in" with the user's own
 * model, and a self-hosted server below. A code is the default because new Lynxce accounts have no password.
 */
@Composable
fun OnboardingScreen(
    notice: String?,
    onSignIn: suspend (String, String) -> Unit,
    onRequestCode: suspend (LynxceProtocol.Target) -> Unit,
    onCodeSignIn: suspend (LynxceProtocol.Target, String) -> Unit,
    onOwnModel: () -> Unit,
    onServer: () -> Unit,
) {
    val palette = LocalPalette.current
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    val form = rememberLynxceSignInState()
    var busy by rememberSaveable { mutableStateOf(false) }
    var error by rememberSaveable { mutableStateOf(notice) }

    fun submit() {
        if (busy || !form.canSubmit) return
        busy = true
        error = null
        scope.launch {
            runCatching {
                if (form.useCode) onCodeSignIn(form.target!!, form.code) else onSignIn(form.account.trim(), form.password)
            }.onFailure {
                error = resources.describeLynxce(it)
                form.signInFailed(it)
            }
            busy = false
        }
    }

    Column(
        Modifier
            .fillMaxSize()
            .systemBarsPadding()
            .imePadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(24.dp))
        BotCharacter(Look.chief, 88.dp, motion = if (busy) BotMotion.Working else BotMotion.Idle, seed = "chief")
        Spacer(Modifier.height(12.dp))
        Text(stringResource(R.string.onboarding_hero_title), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center)
        Spacer(Modifier.height(6.dp))
        Text(
            stringResource(R.string.onboarding_hero_body),
            style = MaterialTheme.typography.bodyMedium,
            color = palette.secondary,
            textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(20.dp))
        Column(
            Modifier
                .widthIn(max = 460.dp)
                .clip(RoundedCornerShape(22.dp))
                .background(palette.surface)
                .padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                VendorLogo("lynxce", 24.dp)
                Spacer(Modifier.width(10.dp))
                Text(stringResource(R.string.onboarding_lynxce_account), style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                Text(
                    stringResource(R.string.onboarding_recommended),
                    style = MaterialTheme.typography.labelMedium,
                    color = palette.secondary,
                    modifier = Modifier.clip(CircleShape).background(palette.raised).padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
            MethodTabs(form.useCode, enabled = !busy) { code ->
                if (form.useCode != code) {
                    form.useCode = code
                    form.info = null
                    error = null
                }
            }
            LynxceSignInFields(
                state = form,
                busy = busy,
                error = error,
                onError = { error = it },
                onRequestCode = onRequestCode,
                onSubmit = ::submit,
            )
            Button(onClick = ::submit, enabled = !busy && form.canSubmit, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                if (busy) {
                    CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                } else {
                    Text(stringResource(R.string.onboarding_sign_in), style = MaterialTheme.typography.titleMedium)
                }
            }
            if (form.useCode) {
                Text(stringResource(R.string.onboarding_code_hint), style = MaterialTheme.typography.bodySmall, color = palette.secondary)
            } else {
                // New accounts have no password: the code sign-in creates them.
                Text(
                    stringResource(R.string.onboarding_register),
                    style = MaterialTheme.typography.bodySmall,
                    color = palette.secondary,
                    modifier = Modifier.clickable(enabled = !busy) {
                        form.useCode = true
                        error = null
                    },
                )
            }
            Text(
                AnnotatedString.fromHtml(
                    stringResource(R.string.onboarding_agreement),
                    linkStyles = TextLinkStyles(SpanStyle(color = palette.text, textDecoration = TextDecoration.Underline)),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = palette.secondary,
            )
        }
        Row(Modifier.widthIn(max = 460.dp).padding(vertical = 18.dp), verticalAlignment = Alignment.CenterVertically) {
            HorizontalDivider(Modifier.weight(1f), color = palette.hairline)
            Text(stringResource(R.string.onboarding_or), style = MaterialTheme.typography.labelMedium, color = palette.secondary, modifier = Modifier.padding(horizontal = 12.dp))
            HorizontalDivider(Modifier.weight(1f), color = palette.hairline)
        }
        Row(
            Modifier
                .widthIn(max = 460.dp)
                .fillMaxWidth()
                .clip(RoundedCornerShape(18.dp))
                .border(1.dp, palette.hairline, RoundedCornerShape(18.dp))
                .clickable(enabled = !busy, onClick = onOwnModel)
                .padding(16.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(40.dp).clip(RoundedCornerShape(11.dp)).background(palette.raised), contentAlignment = Alignment.Center) {
                Icon(Icons.Rounded.Tune, contentDescription = null, tint = palette.text)
            }
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.onboarding_own_model), style = MaterialTheme.typography.titleSmall)
                Text(stringResource(R.string.onboarding_own_model_body), style = MaterialTheme.typography.bodySmall, color = palette.secondary)
            }
            Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = palette.secondary)
        }
        Spacer(Modifier.height(12.dp))
        TextButton(onClick = onServer, enabled = !busy) {
            Text(stringResource(R.string.onboarding_server), style = MaterialTheme.typography.titleSmall, color = palette.secondary)
        }
        Spacer(Modifier.height(16.dp))
    }
}

/** 验证码 | 密码, a segmented pair at the top of the account card (as on the web). */
@Composable
private fun MethodTabs(useCode: Boolean, enabled: Boolean, onPick: (Boolean) -> Unit) {
    val palette = LocalPalette.current
    Row(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(palette.raised)
            .padding(4.dp)
            .selectableGroup(),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        listOf(true to R.string.onboarding_tab_code, false to R.string.onboarding_tab_password).forEach { (code, label) ->
            val selected = useCode == code
            Box(
                Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(9.dp))
                    .background(if (selected) palette.background else Color.Transparent)
                    .selectable(selected = selected, enabled = enabled, role = Role.Tab) { onPick(code) }
                    .padding(vertical = 9.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    stringResource(label),
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
                    color = if (selected) palette.text else palette.secondary,
                )
            }
        }
    }
}

@Preview(showBackground = true, backgroundColor = 0xFF000000)
@Composable
private fun OnboardingPreview() {
    OctopTheme(dark = true) {
        OnboardingScreen(notice = null, onSignIn = { _, _ -> }, onRequestCode = {}, onCodeSignIn = { _, _ -> }, onOwnModel = {}, onServer = {})
    }
}
