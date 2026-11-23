package io.github.alisonxx.octopbot.ui.onboarding

import android.content.res.Resources
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.Stable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.autofill.ContentType
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentType
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.describe
import io.github.alisonxx.octopbot.net.ApiException
import io.github.alisonxx.octopbot.net.LynxceProtocol
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

private const val RESEND_SECONDS = 60

/** What the Lynxce sign-in form holds; verification code is the default, password the fallback. */
@Stable
class LynxceSignInState(
    useCode: Boolean = true,
    account: String = "",
    code: String = "",
    sent: Boolean = false,
    secondsLeft: Int = 0,
    info: String? = null,
) {
    var useCode by mutableStateOf(useCode)
    var account by mutableStateOf(account)
    var password by mutableStateOf("")
    var code by mutableStateOf(code)
    var sent by mutableStateOf(sent)
    var secondsLeft by mutableIntStateOf(secondsLeft)
    var sending by mutableStateOf(false)
    var info by mutableStateOf(info)

    val target get() = LynxceProtocol.Target.of(account)

    /** Read at call time, so the code field can auto-submit from inside onValueChange. */
    val canSubmit get() = if (useCode) target != null && LynxceProtocol.isValidCode(code) else account.isNotBlank() && password.isNotEmpty()

    /** A rejected code is cleared so typing the next one auto-submits again. */
    fun signInFailed(error: Throwable) {
        info = null
        if (useCode && LynxceProtocol.codeFailure(error) == LynxceProtocol.CodeFailure.InvalidCode) code = ""
    }

    companion object {
        // The password is deliberately not saved across process death.
        val Saver = listSaver<LynxceSignInState, Any?>(
            save = { listOf(it.useCode, it.account, it.code, it.sent, it.secondsLeft, it.info) },
            restore = { LynxceSignInState(it[0] as Boolean, it[1] as String, it[2] as String, it[3] as Boolean, it[4] as Int, it[5] as String?) },
        )
    }
}

@Composable
fun rememberLynxceSignInState(): LynxceSignInState = rememberSaveable(saver = LynxceSignInState.Saver) { LynxceSignInState() }

/**
 * A Lynxce sign-in failure as one sentence. Lynxce itself gets our wording for wrong codes and throttling;
 * an Octop server ([serverMessageFirst]) already localizes its own message, so that wins when present.
 */
fun Resources.describeLynxce(error: Throwable, serverMessageFirst: Boolean = false): String {
    if (serverMessageFirst) (error as? ApiException)?.message?.takeIf { it.isNotBlank() }?.let { return it }
    return when (LynxceProtocol.codeFailure(error)) {
        LynxceProtocol.CodeFailure.InvalidCode -> getString(R.string.error_code_invalid)
        LynxceProtocol.CodeFailure.TooFrequent -> getString(R.string.error_code_too_frequent)
        null -> describe(error)
    }
}

/**
 * Phone-or-email field, then either the 6-digit code (with a get-code / countdown / resend button) or the password,
 * then the error or "code sent" line. The caller owns the sign-in button and the [error] text; [modifier] goes on
 * the account field (e.g. to focus it).
 */
@Composable
fun LynxceSignInFields(
    state: LynxceSignInState,
    busy: Boolean,
    error: String?,
    onError: (String?) -> Unit,
    onRequestCode: suspend (LynxceProtocol.Target) -> Unit,
    onSubmit: () -> Unit,
    modifier: Modifier = Modifier,
    serverMessageFirst: Boolean = false,
) {
    val palette = LocalPalette.current
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    val codeFocus = remember { FocusRequester() }

    LaunchedEffect(state.secondsLeft) {
        if (state.secondsLeft > 0) {
            delay(1000)
            state.secondsLeft--
        }
    }

    fun requestCode() {
        val to = state.target ?: return
        if (state.sending || busy || state.secondsLeft > 0) return
        state.sending = true
        state.info = null
        onError(null)
        scope.launch {
            runCatching { onRequestCode(to) }
                .onSuccess {
                    state.sent = true
                    state.secondsLeft = RESEND_SECONDS
                    state.info = resources.getString(R.string.onboarding_code_sent)
                    runCatching { codeFocus.requestFocus() }
                }
                .onFailure { onError(resources.describeLynxce(it, serverMessageFirst)) }
            state.sending = false
        }
    }

    FormField(
        value = state.account,
        onValueChange = { state.account = it },
        label = stringResource(R.string.onboarding_account),
        keyboardType = KeyboardType.Email,
        enabled = !busy,
        modifier = modifier,
    )
    if (state.useCode) {
        val canSend = state.target != null && !state.sending && !busy && state.secondsLeft == 0
        FormField(
            value = state.code,
            onValueChange = { typed ->
                state.code = typed.filter { it in '0'..'9' }.take(LynxceProtocol.CODE_LENGTH)
                if (!busy && state.canSubmit) onSubmit()
            },
            label = stringResource(R.string.onboarding_code),
            keyboardType = KeyboardType.NumberPassword,
            imeAction = ImeAction.Go,
            onDone = onSubmit,
            enabled = !busy,
            modifier = Modifier
                .focusRequester(codeFocus)
                .semantics { contentType = ContentType.SmsOtpCode },
            trailing = {
                TextButton(onClick = ::requestCode, enabled = canSend, modifier = Modifier.padding(end = 4.dp)) {
                    Text(
                        when {
                            state.secondsLeft > 0 -> stringResource(R.string.onboarding_code_countdown, state.secondsLeft)
                            state.sent -> stringResource(R.string.onboarding_resend_code)
                            else -> stringResource(R.string.onboarding_get_code)
                        },
                        color = if (canSend) palette.text else palette.secondary,
                    )
                }
            },
        )
    } else {
        FormField(
            value = state.password,
            onValueChange = { state.password = it },
            label = stringResource(R.string.onboarding_password),
            password = true,
            imeAction = ImeAction.Go,
            onDone = onSubmit,
            enabled = !busy,
        )
    }
    error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
        ?: state.info?.let { Text(it, color = LocalPalette.current.secondary, style = MaterialTheme.typography.bodyMedium) }
}

/** The secondary switch between code and password sign-in. */
@Composable
fun LynxceModeSwitch(state: LynxceSignInState, busy: Boolean, onSwitched: () -> Unit, modifier: Modifier = Modifier) {
    TextButton(
        onClick = {
            state.useCode = !state.useCode
            state.info = null
            onSwitched()
        },
        enabled = !busy,
        modifier = modifier,
    ) {
        Text(
            stringResource(if (state.useCode) R.string.onboarding_use_password else R.string.onboarding_use_code),
            color = LocalPalette.current.text,
        )
    }
}
