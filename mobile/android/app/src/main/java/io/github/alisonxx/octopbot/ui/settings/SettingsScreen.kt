package io.github.alisonxx.octopbot.ui.settings

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.BuildConfig
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppLocale
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.model.ModelOption
import io.github.alisonxx.octopbot.store.Appearance
import io.github.alisonxx.octopbot.store.UserSettings
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.TopBarTitle
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme

private const val GITHUB_URL = "https://github.com/alison-xx/octop-bot"

/** Everything the settings page shows, separate from the ViewModel for previews. */
data class SettingsState(
    val accountName: String,
    val balance: String?,
    val lynxce: Boolean,
    val host: String,
    val models: List<ModelOption>,
    val settings: UserSettings,
    /** [AppLocale] tag; empty follows the system. */
    val language: String,
)

@Composable
fun SettingsScreen(model: AppViewModel, onBack: () -> Unit, onConnectServer: () -> Unit) {
    val session by model.session.collectAsStateWithLifecycle()
    val backend = (session as? SessionState.Ready)?.backend ?: return
    val balance by model.balance.collectAsStateWithLifecycle()
    val models by model.models.collectAsStateWithLifecycle()
    val settings by model.settings.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { model.refreshBalance() }
    Settings(
        state = SettingsState(
            backend.accountName, balance, backend.definesBotsLocally, backend.connectionLabel, models, settings, AppLocale.tag(),
        ),
        onBack = onBack,
        onConnectServer = onConnectServer,
        onUseLynxce = { model.signOut() },
        onModel = model::setModel,
        onLanguage = model::setLanguage,
        onAppearance = model::setAppearance,
        onReadAloud = { model.setReadAloud(it) },
        onNotifications = { model.setNotifications(it) },
        onSignOut = { model.signOut() },
    )
}

@Composable
fun Settings(
    state: SettingsState,
    onBack: () -> Unit,
    onConnectServer: () -> Unit,
    onUseLynxce: () -> Unit,
    onModel: (String?) -> Unit,
    onLanguage: (String) -> Unit,
    onAppearance: (Appearance) -> Unit,
    onReadAloud: (Boolean) -> Unit,
    onNotifications: (Boolean) -> Unit,
    onSignOut: () -> Unit,
) {
    val context = LocalContext.current
    var confirmSignOut by rememberSaveable { mutableStateOf(false) }
    var modelPicker by rememberSaveable { mutableStateOf(false) }
    var languagePicker by rememberSaveable { mutableStateOf(false) }
    var appearancePicker by rememberSaveable { mutableStateOf(false) }
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
    Column(Modifier.fillMaxSize()) {
        TopBar(leading = { BackButton(onBack) }) { TopBarTitle(stringResource(R.string.settings_title)) }
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp)
                .navigationBarsPadding(),
        ) {
            Group(stringResource(R.string.settings_account)) {
                Item(stringResource(R.string.settings_signed_in_as), value = state.accountName)
                if (state.lynxce) Item(stringResource(R.string.settings_balance), value = state.balance ?: "—")
            }
            Group(stringResource(R.string.settings_connection)) {
                Item(
                    if (state.lynxce) stringResource(R.string.settings_lynxce) else stringResource(R.string.settings_server),
                    value = state.host,
                )
                if (state.lynxce) {
                    Item(stringResource(R.string.onboarding_server), chevron = true, onClick = onConnectServer)
                } else {
                    Item(stringResource(R.string.settings_use_lynxce), chevron = true, onClick = onUseLynxce)
                }
            }
            if (state.lynxce) {
                Group(stringResource(R.string.settings_model), footer = stringResource(R.string.settings_model_footer)) {
                    val current = state.models.firstOrNull { it.id == state.settings.model }?.name
                        ?: stringResource(R.string.settings_model_auto)
                    Item(stringResource(R.string.settings_model), value = current, chevron = true, onClick = { modelPicker = true })
                }
            }
            Group(stringResource(R.string.settings_general)) {
                Item(
                    stringResource(R.string.settings_language),
                    value = languages.firstOrNull { it.first == state.language }?.second ?: languages.first().second,
                    chevron = true,
                    onClick = { languagePicker = true },
                )
                Item(
                    stringResource(R.string.settings_appearance),
                    value = appearances.first { it.first == state.settings.appearance }.second,
                    chevron = true,
                    onClick = { appearancePicker = true },
                )
            }
            Group(stringResource(R.string.settings_voice)) {
                Toggle(stringResource(R.string.settings_read_aloud), state.settings.readAloud, onReadAloud)
                Toggle(stringResource(R.string.settings_notify), state.settings.notifications, onNotifications)
            }
            Group(stringResource(R.string.settings_about)) {
                Item(stringResource(R.string.settings_version), value = BuildConfig.VERSION_NAME)
                Item(stringResource(R.string.settings_github), chevron = true, onClick = {
                    context.startActivity(Intent(Intent.ACTION_VIEW, GITHUB_URL.toUri()))
                })
            }
            Group(null) {
                Item(stringResource(R.string.settings_sign_out), danger = true, onClick = { confirmSignOut = true })
            }
            Spacer(Modifier.height(24.dp))
        }
    }
    if (confirmSignOut) {
        AlertDialog(
            onDismissRequest = { confirmSignOut = false },
            text = { Text(stringResource(R.string.settings_sign_out_confirm)) },
            confirmButton = {
                TextButton(onClick = { confirmSignOut = false; onSignOut() }) {
                    Text(stringResource(R.string.settings_sign_out), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { confirmSignOut = false }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
    if (modelPicker) {
        val options = listOf<String?>(null) + state.models.map { it.id }
        ChoiceDialog(
            title = stringResource(R.string.settings_model),
            options = options,
            label = { id -> state.models.firstOrNull { it.id == id }?.name ?: stringResource(R.string.settings_model_auto) },
            selected = state.settings.model,
            onPick = onModel,
            onDismiss = { modelPicker = false },
        )
    }
    if (languagePicker) {
        ChoiceDialog(
            title = stringResource(R.string.settings_language),
            options = languages.map { it.first },
            label = { tag -> languages.first { it.first == tag }.second },
            selected = state.language.takeIf { tag -> languages.any { it.first == tag } } ?: AppLocale.SYSTEM,
            onPick = onLanguage,
            onDismiss = { languagePicker = false },
        )
    }
    if (appearancePicker) {
        ChoiceDialog(
            title = stringResource(R.string.settings_appearance),
            options = appearances.map { it.first },
            label = { value -> appearances.first { it.first == value }.second },
            selected = state.settings.appearance,
            onPick = onAppearance,
            onDismiss = { appearancePicker = false },
        )
    }
}

@Composable
private fun <T> ChoiceDialog(
    title: String,
    options: List<T>,
    label: @Composable (T) -> String,
    selected: T,
    onPick: (T) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                options.forEach { option ->
                    ChoiceRow(label(option), option == selected) {
                        onPick(option)
                        onDismiss()
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
        Text(name, modifier = Modifier.weight(1f))
        if (selected) Icon(Icons.Rounded.Check, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
    }
}

@Composable
private fun Group(title: String?, footer: String? = null, content: @Composable ColumnScope.() -> Unit) {
    val palette = LocalPalette.current
    Column(Modifier.padding(top = 20.dp)) {
        title?.let {
            Text(it, style = MaterialTheme.typography.labelLarge, color = palette.secondary, modifier = Modifier.padding(start = 16.dp, bottom = 6.dp))
        }
        Column(Modifier.clip(RoundedCornerShape(18.dp)).background(palette.surface), content = content)
        footer?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = palette.secondary, modifier = Modifier.padding(start = 16.dp, top = 6.dp, end = 16.dp))
        }
    }
}

@Composable
private fun Item(title: String, value: String? = null, chevron: Boolean = false, danger: Boolean = false, onClick: (() -> Unit)? = null) {
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
            modifier = Modifier.weight(1f),
        )
        value?.let {
            Spacer(Modifier.width(12.dp))
            Text(it, style = MaterialTheme.typography.bodyLarge, color = palette.secondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        if (chevron) Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = palette.secondary)
    }
    HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
}

@Composable
private fun Toggle(title: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    val palette = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(title, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
    HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
}

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 900)
@Composable
private fun SettingsPreview() {
    OctopTheme(dark = true) {
        Settings(
            state = SettingsState(
                accountName = "Alex",
                balance = "128.50",
                lynxce = true,
                host = "api.lynxce.cn",
                models = emptyList(),
                settings = UserSettings(readAloud = false, notifications = true, model = null),
                language = AppLocale.SYSTEM,
            ),
            onBack = {}, onConnectServer = {}, onUseLynxce = {}, onModel = {}, onLanguage = {}, onAppearance = {},
            onReadAloud = {}, onNotifications = {}, onSignOut = {},
        )
    }
}
