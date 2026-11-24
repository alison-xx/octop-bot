package io.github.alisonxx.octopbot.ui.onboarding

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.keyframes
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.ArrowForward
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Lock
import androidx.compose.material.icons.rounded.MailOutline
import androidx.compose.material.icons.rounded.PhoneIphone
import androidx.compose.material.icons.rounded.Shield
import androidx.compose.material.icons.rounded.Tune
import androidx.compose.material.icons.rounded.Visibility
import androidx.compose.material.icons.rounded.VisibilityOff
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
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
import androidx.compose.ui.autofill.ContentType
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.scale
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.luminance
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentType
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.fromHtml
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.BotMotion
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.net.LynxceProtocol
import io.github.alisonxx.octopbot.ui.settings.VendorLogo
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.math.roundToInt

private const val RESEND_SECONDS = 60

/** Octop Bot's rose, as on the desktop and web sign-in (Chief's colour), for light and dark pages. */
private class Brand(dark: Boolean) {
    val brand = if (dark) Color(0xFFF07C90) else Color(0xFFE85D75)
    /** Rose text on the page (links, "Get code"): at least 4.5:1. */
    val text = if (dark) Color(0xFFF59AAA) else Color(0xFFC7314D)
    val buttonTop = if (dark) Color(0xFFE9566F) else Color(0xFFEA5A73)
    val buttonBottom = if (dark) Color(0xFFC93652) else Color(0xFFCF3753)
    val stage = if (dark) listOf(Color(0xFF6A2337), Color(0xFF4A1A2C), Color(0xFF24111D)) else listOf(Color(0xFFFF8E9F), Color(0xFFE85D75), Color(0xFFB3305A))
    val glow = if (dark) Color(0x47FF9678) else Color(0x8CFFD6AA)
    val shade = if (dark) Color(0x995A1E6E) else Color(0x8C782878)
}

/**
 * Start page, laid out like the desktop sign-in (direction B) folded for a phone: a rose banner with Chief, then one
 * "phone or email" field and the code with "Get code" inside it (or the password, via "Use password"), the rose sign-in
 * button, and the secondary ways in: without an account on the user's own model, or a self-hosted server.
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
    val brand = remember(palette.background) { Brand(palette.background.luminance() < 0.5f) }
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    val form = rememberLynxceSignInState()
    var busy by rememberSaveable { mutableStateOf(false) }
    var error by rememberSaveable { mutableStateOf(notice) }
    val accountFocus = remember { FocusRequester() }
    val secondFocus = remember { FocusRequester() }
    val shakeAccount = remember { Animatable(0f) }
    val shakeSecond = remember { Animatable(0f) }

    LaunchedEffect(form.secondsLeft) {
        if (form.secondsLeft > 0) {
            delay(1000)
            form.secondsLeft--
        }
    }

    fun shake(field: Animatable<Float, *>) = scope.launch {
        field.snapTo(0f)
        field.animateTo(0f, keyframes {
            durationMillis = 360
            -8f at 60
            8f at 120
            -6f at 180
            6f at 240
            -3f at 300
        })
    }

    fun submit() {
        if (busy) return
        if (!form.canSubmit) {
            // Point at what is missing rather than greying the button out.
            if (form.accountMissing) {
                shake(shakeAccount)
                runCatching { accountFocus.requestFocus() }
            } else {
                shake(shakeSecond)
                runCatching { secondFocus.requestFocus() }
            }
            return
        }
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

    fun requestCode() {
        val to = form.target ?: return
        if (form.sending || busy || form.secondsLeft > 0) return
        form.sending = true
        form.info = null
        error = null
        scope.launch {
            runCatching { onRequestCode(to) }
                .onSuccess {
                    form.sent = true
                    form.secondsLeft = RESEND_SECONDS
                    form.info = resources.getString(R.string.onboarding_code_sent)
                    runCatching { secondFocus.requestFocus() }
                }
                .onFailure { error = resources.describeLynxce(it) }
            form.sending = false
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
        Column(Modifier.widthIn(max = 460.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Spacer(Modifier.height(4.dp))
            Banner(brand, busy)
            Column(Modifier.padding(top = 6.dp)) {
                Text(stringResource(R.string.onboarding_title), fontSize = 26.sp, fontWeight = FontWeight.Bold, color = palette.text)
                Spacer(Modifier.height(4.dp))
                Text(stringResource(R.string.onboarding_subtitle), style = MaterialTheme.typography.bodyMedium, color = palette.secondary)
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                VendorLogo("lynxce", 22.dp)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.onboarding_lynxce_account), style = MaterialTheme.typography.titleSmall, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Text(
                    stringResource(R.string.onboarding_recommended_sync),
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.SemiBold,
                    color = brand.text,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.clip(CircleShape).background(brand.brand.copy(alpha = 0.1f)).padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }
            SignInField(
                value = form.account,
                onValueChange = {
                    form.account = it
                    error = null
                },
                placeholder = stringResource(R.string.onboarding_target),
                leading = if ('@' in form.account) Icons.Rounded.MailOutline else Icons.Rounded.PhoneIphone,
                keyboardType = KeyboardType.Email,
                enabled = !busy,
                brand = brand,
                modifier = Modifier.offset { IntOffset(shakeAccount.value.dp.roundToPx(), 0) }.focusRequester(accountFocus),
            )
            if (form.useCode) {
                val canSend = form.target != null && !form.sending && !busy && form.secondsLeft == 0
                SignInField(
                    value = form.code,
                    onValueChange = { typed ->
                        form.code = typed.filter { it in '0'..'9' }.take(LynxceProtocol.CODE_LENGTH)
                        if (!busy && form.canSubmit) submit()
                    },
                    placeholder = stringResource(R.string.onboarding_code_six),
                    leading = Icons.Rounded.Shield,
                    keyboardType = KeyboardType.NumberPassword,
                    imeAction = ImeAction.Go,
                    onDone = ::submit,
                    enabled = !busy,
                    brand = brand,
                    modifier = Modifier
                        .offset { IntOffset(shakeSecond.value.dp.roundToPx(), 0) }
                        .focusRequester(secondFocus)
                        .semantics { contentType = ContentType.SmsOtpCode },
                    trailing = {
                        TextButton(onClick = ::requestCode, enabled = canSend, modifier = Modifier.padding(end = 4.dp)) {
                            Text(
                                when {
                                    form.secondsLeft > 0 -> stringResource(R.string.onboarding_code_countdown, form.secondsLeft)
                                    form.sent -> stringResource(R.string.onboarding_resend_code)
                                    else -> stringResource(R.string.onboarding_get_code)
                                },
                                fontWeight = FontWeight.SemiBold,
                                color = if (canSend) brand.text else palette.secondary,
                            )
                        }
                    },
                )
            } else {
                SignInField(
                    value = form.password,
                    onValueChange = { form.password = it },
                    placeholder = stringResource(R.string.onboarding_password),
                    leading = Icons.Rounded.Lock,
                    password = true,
                    imeAction = ImeAction.Go,
                    onDone = ::submit,
                    enabled = !busy,
                    brand = brand,
                    modifier = Modifier.offset { IntOffset(shakeSecond.value.dp.roundToPx(), 0) }.focusRequester(secondFocus),
                )
            }
            Row(verticalAlignment = Alignment.Top) {
                val (line, color) = when {
                    error != null -> error!! to MaterialTheme.colorScheme.error
                    form.info != null && form.useCode -> form.info!! to palette.secondary
                    form.useCode -> stringResource(R.string.onboarding_auto_register) to palette.secondary
                    else -> stringResource(R.string.onboarding_register) to palette.secondary
                }
                Text(line, style = MaterialTheme.typography.bodySmall, color = color, modifier = Modifier.weight(1f).padding(top = 2.dp))
                Spacer(Modifier.width(12.dp))
                Text(
                    stringResource(if (form.useCode) R.string.onboarding_use_password_link else R.string.onboarding_use_code_link),
                    style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.SemiBold,
                    color = brand.text,
                    modifier = Modifier.clickable(enabled = !busy) {
                        form.useCode = !form.useCode
                        form.info = null
                        error = null
                    }.padding(2.dp),
                )
            }
            BrandButton(stringResource(R.string.onboarding_sign_in), busy, brand, onClick = ::submit)
            Text(
                AnnotatedString.fromHtml(
                    stringResource(R.string.onboarding_agreement),
                    linkStyles = TextLinkStyles(SpanStyle(color = palette.text, textDecoration = TextDecoration.Underline)),
                ),
                style = MaterialTheme.typography.bodySmall,
                color = palette.secondary,
            )
            Row(Modifier.padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                HorizontalDivider(Modifier.weight(1f), color = palette.hairline)
                Text(stringResource(R.string.onboarding_or), style = MaterialTheme.typography.labelMedium, color = palette.secondary, modifier = Modifier.padding(horizontal = 12.dp))
                HorizontalDivider(Modifier.weight(1f), color = palette.hairline)
            }
            Row(
                Modifier
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
            TextButton(onClick = onServer, enabled = !busy, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Text(stringResource(R.string.onboarding_server), style = MaterialTheme.typography.titleSmall, color = palette.secondary)
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

/** The desktop's left-hand stage, folded into a banner: Chief and the headline on the rose gradient. */
@Composable
private fun Banner(brand: Brand, busy: Boolean) {
    Row(
        Modifier
            .fillMaxWidth()
            .heightIn(min = 148.dp)
            .clip(RoundedCornerShape(26.dp))
            .drawBehind {
                drawRect(Brush.linearGradient(brand.stage, start = Offset.Zero, end = Offset(size.width, size.height)))
                drawRect(Brush.radialGradient(listOf(brand.glow, Color.Transparent), center = Offset(size.width * 0.85f, 0f), radius = size.width * 0.6f))
                drawRect(Brush.radialGradient(listOf(brand.shade, Color.Transparent), center = Offset(0f, size.height), radius = size.width * 0.6f))
            }
            .padding(horizontal = 18.dp, vertical = 22.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BotCharacter(Look.chief, 88.dp, motion = if (busy) BotMotion.Working else BotMotion.Idle, seed = "chief")
        Spacer(Modifier.width(14.dp))
        // Its own string so Chinese breaks after 「随叫随到的」 rather than inside a word.
        Text(stringResource(R.string.onboarding_banner_title), fontSize = 24.sp, lineHeight = 30.sp, fontWeight = FontWeight.Bold, color = Color.White)
    }
}

/** Always looks tappable: with something missing the caller shakes that field instead. */
@Composable
private fun BrandButton(label: String, busy: Boolean, brand: Brand, onClick: () -> Unit) {
    val interaction = remember { MutableInteractionSource() }
    val pressed by interaction.collectIsPressedAsState()
    Row(
        Modifier
            .fillMaxWidth()
            .height(54.dp)
            .scale(if (pressed) 0.98f else 1f)
            .shadow(10.dp, RoundedCornerShape(14.dp), ambientColor = brand.brand, spotColor = brand.brand)
            .clip(RoundedCornerShape(14.dp))
            .background(Brush.verticalGradient(listOf(brand.buttonTop, brand.buttonBottom)))
            .clickable(interactionSource = interaction, indication = null, enabled = !busy, onClick = onClick),
        horizontalArrangement = Arrangement.Center,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = Color.White)
        } else {
            Text(label, color = Color.White, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.width(8.dp))
            Icon(Icons.AutoMirrored.Rounded.ArrowForward, contentDescription = null, tint = Color.White, modifier = Modifier.size(18.dp))
        }
    }
}

/** The sign-in page's fields: page background, hairline border, rose while focused, placeholder instead of a label. */
@Composable
private fun SignInField(
    value: String,
    onValueChange: (String) -> Unit,
    placeholder: String,
    leading: androidx.compose.ui.graphics.vector.ImageVector,
    brand: Brand,
    modifier: Modifier = Modifier,
    keyboardType: KeyboardType = KeyboardType.Text,
    imeAction: ImeAction = ImeAction.Next,
    onDone: () -> Unit = {},
    password: Boolean = false,
    enabled: Boolean = true,
    trailing: (@Composable () -> Unit)? = null,
) {
    val palette = LocalPalette.current
    var reveal by rememberSaveable { mutableStateOf(false) }
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        placeholder = { Text(placeholder) },
        leadingIcon = { Icon(leading, contentDescription = null, tint = palette.secondary) },
        singleLine = true,
        enabled = enabled,
        shape = RoundedCornerShape(14.dp),
        visualTransformation = if (password && !reveal) PasswordVisualTransformation() else VisualTransformation.None,
        keyboardOptions = KeyboardOptions(keyboardType = if (password) KeyboardType.Password else keyboardType, imeAction = imeAction, autoCorrectEnabled = false),
        keyboardActions = KeyboardActions(onDone = { onDone() }, onGo = { onDone() }),
        trailingIcon = if (password) {
            {
                IconButton(onClick = { reveal = !reveal }) {
                    Icon(
                        if (reveal) Icons.Rounded.VisibilityOff else Icons.Rounded.Visibility,
                        contentDescription = stringResource(if (reveal) R.string.password_hide else R.string.password_show),
                    )
                }
            }
        } else trailing,
        colors = OutlinedTextFieldDefaults.colors(
            unfocusedContainerColor = palette.background,
            focusedContainerColor = palette.background,
            disabledContainerColor = palette.background,
            unfocusedBorderColor = palette.hairline,
            focusedBorderColor = brand.brand,
            cursorColor = brand.brand,
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

@Preview(showBackground = true, backgroundColor = 0xFF000000)
@Composable
private fun OnboardingPreview() {
    OctopTheme(dark = true) {
        OnboardingScreen(notice = null, onSignIn = { _, _ -> }, onRequestCode = {}, onCodeSignIn = { _, _ -> }, onOwnModel = {}, onServer = {})
    }
}
