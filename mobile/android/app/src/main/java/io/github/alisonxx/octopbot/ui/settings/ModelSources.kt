package io.github.alisonxx.octopbot.ui.settings

import android.content.Intent
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.OpenInNew
import androidx.compose.material.icons.rounded.Add
import androidx.compose.material.icons.rounded.Check
import androidx.compose.material.icons.rounded.CheckCircle
import androidx.compose.material.icons.rounded.ChevronRight
import androidx.compose.material.icons.rounded.Close
import androidx.compose.material.icons.rounded.DeleteOutline
import androidx.compose.material.icons.rounded.Dns
import androidx.compose.material.icons.rounded.Hub
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.net.toUri
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.BalanceState
import io.github.alisonxx.octopbot.app.SessionState
import io.github.alisonxx.octopbot.app.describe
import io.github.alisonxx.octopbot.character.BotCharacter
import io.github.alisonxx.octopbot.model.Look
import io.github.alisonxx.octopbot.net.KeyPlace
import io.github.alisonxx.octopbot.net.KeyVendor
import io.github.alisonxx.octopbot.net.LocalServer
import io.github.alisonxx.octopbot.net.LynxceBackend
import io.github.alisonxx.octopbot.net.ModelKeyStore
import io.github.alisonxx.octopbot.net.NewOwnKey
import io.github.alisonxx.octopbot.net.OwnKey
import io.github.alisonxx.octopbot.net.OwnKeyList
import io.github.alisonxx.octopbot.net.PhoneModels
import io.github.alisonxx.octopbot.net.PhoneSelection
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.net.ServerModelKeys
import io.github.alisonxx.octopbot.net.VendorCatalog
import io.github.alisonxx.octopbot.net.VendorCompany
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.BalanceText
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.TopBarTitle
import io.github.alisonxx.octopbot.ui.onboarding.FormField
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.launch

// Settings → Models, Add API key and choosing a model without signing in (docs/octop-bot-saas.md).

private val LOGOS = mapOf(
    "tencent" to R.drawable.vendor_tencent,
    "aliyun" to R.drawable.vendor_aliyun,
    "volcengine" to R.drawable.vendor_volcengine,
    "zhipu" to R.drawable.vendor_zhipu,
    "kimi" to R.drawable.vendor_kimi,
    "minimax" to R.drawable.vendor_minimax,
    "siliconflow" to R.drawable.vendor_siliconflow,
    "openai" to R.drawable.vendor_openai,
    "gemini" to R.drawable.vendor_gemini,
    "openrouter" to R.drawable.vendor_openrouter,
    "groq" to R.drawable.vendor_groq,
    "modelscope" to R.drawable.vendor_modelscope,
    "mimo" to R.drawable.vendor_mimo,
    "iflytek" to R.drawable.vendor_iflytek,
    "opencode" to R.drawable.vendor_opencode,
    "lynxce" to R.drawable.vendor_lynxce,
    "ollama" to R.drawable.vendor_ollama,
)

private val COMPANY_NAMES = mapOf(
    "tencent" to R.string.models_company_tencent,
    "aliyun" to R.string.models_company_aliyun,
    "volcengine" to R.string.models_company_volcengine,
    "deepseek" to R.string.models_company_deepseek,
    "zhipu" to R.string.models_company_zhipu,
    "kimi" to R.string.models_company_kimi,
    "minimax" to R.string.models_company_minimax,
    "siliconflow" to R.string.models_company_siliconflow,
    "openai" to R.string.models_company_openai,
    "gemini" to R.string.models_company_gemini,
    "openrouter" to R.string.models_company_openrouter,
    "modelscope" to R.string.models_company_modelscope,
    "groq" to R.string.models_company_groq,
    "mimo" to R.string.models_company_mimo,
    "iflytek" to R.string.models_company_iflytek,
    "opencode" to R.string.models_company_opencode,
)

/** "腾讯云", "阿里云百炼" …; other companies use the catalog's name. */
@Composable
fun companyName(company: String, fallback: String): String = COMPANY_NAMES[company]?.let { stringResource(it) } ?: fallback

@Composable
private fun keyName(key: OwnKey, phone: PhoneModels): String =
    if (key.vendor == VendorCompany.CUSTOM) key.name else companyName(phone.company(key), key.name)

/** A vendor's logo on a white tile, or its initials when the app has no logo for it. */
@Composable
fun VendorLogo(company: String, size: Dp = 28.dp) {
    val palette = LocalPalette.current
    val shape = RoundedCornerShape(size * 0.24f)
    val logo = LOGOS[company]
    when {
        company == VendorCompany.CUSTOM -> Box(Modifier.size(size).clip(shape).background(palette.raised), contentAlignment = Alignment.Center) {
            Icon(Icons.Rounded.Hub, contentDescription = null, tint = palette.text, modifier = Modifier.size(size * 0.55f))
        }
        company == "server" -> Box(Modifier.size(size).clip(shape).background(palette.raised), contentAlignment = Alignment.Center) {
            Icon(Icons.Rounded.Dns, contentDescription = null, tint = palette.text, modifier = Modifier.size(size * 0.55f))
        }
        logo != null -> Box(
            Modifier.size(size).clip(shape).background(Color.White).border(0.5.dp, palette.hairline, shape),
            contentAlignment = Alignment.Center,
        ) { Image(painterResource(logo), contentDescription = null, modifier = Modifier.padding(size * 0.12f)) }
        else -> Box(Modifier.size(size).clip(shape).background(palette.raised), contentAlignment = Alignment.Center) {
            Text(
                if (company == "deepseek") "DS" else company.take(2).uppercase(),
                fontWeight = FontWeight.Bold,
                fontSize = (size.value * 0.36f).sp,
                color = palette.text,
            )
        }
    }
}

/** Company tiles, three to a row. */
@Composable
fun VendorGrid(companies: List<VendorCompany>, onPick: (VendorCompany) -> Unit) {
    val palette = LocalPalette.current
    companies.chunked(3).forEach { row ->
        Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            row.forEach { company ->
                Column(
                    Modifier
                        .weight(1f)
                        .clip(RoundedCornerShape(14.dp))
                        .background(palette.surface)
                        .clickable { onPick(company) }
                        .padding(vertical = 14.dp, horizontal = 6.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    VendorLogo(company.id, 34.dp)
                    Text(
                        companyName(company.id, company.plans.firstOrNull()?.name ?: company.id),
                        style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.Medium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            repeat(3 - row.size) { Spacer(Modifier.weight(1f)) }
        }
    }
}

/** "我的 API Key  [厂商直接收费]" with an optional trailing action. */
@Composable
private fun SourceHeader(title: String, tag: String, trailing: @Composable () -> Unit = {}) {
    val palette = LocalPalette.current
    Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp, top = 22.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, style = MaterialTheme.typography.titleSmall)
        Spacer(Modifier.width(8.dp))
        Text(
            tag,
            style = MaterialTheme.typography.labelSmall,
            color = palette.secondary,
            modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(palette.raised).padding(horizontal = 6.dp, vertical = 2.dp),
        )
        Spacer(Modifier.weight(1f))
        trailing()
    }
}

@Composable
private fun Card(content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(LocalPalette.current.surface), content = content)
}

@Composable
private fun Footer(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodySmall,
        color = LocalPalette.current.secondary,
        modifier = Modifier.padding(start = 16.dp, top = 6.dp, end = 16.dp),
    )
}

@Composable
private fun InUse(model: String) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.widthIn(max = 160.dp)) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(Color(0xFF34C759)))
        Spacer(Modifier.width(5.dp))
        Text(model, style = MaterialTheme.typography.labelMedium, color = LocalPalette.current.secondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
    }
}

/** A source row: logo, name, second line, then [trailing]. */
@Composable
private fun SourceRow(
    company: String,
    title: String,
    subtitle: String,
    onClick: (() -> Unit)? = null,
    trailing: @Composable () -> Unit = {},
) {
    Row(
        Modifier
            .fillMaxWidth()
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        VendorLogo(company, 32.dp)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = LocalPalette.current.secondary, maxLines = 2, overflow = TextOverflow.Ellipsis)
        }
        Spacer(Modifier.width(8.dp))
        trailing()
    }
}

/** "选择模型" opening a menu of [models]. */
@Composable
private fun UseMenu(models: List<Pair<String, String>>, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val palette = LocalPalette.current
    Box {
        Text(
            stringResource(R.string.models_keys_use),
            style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.clip(CircleShape).background(palette.raised).clickable { open = true }.padding(horizontal = 12.dp, vertical = 6.dp),
        )
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            models.forEach { (id, label) ->
                DropdownMenuItem(text = { Text(label) }, onClick = {
                    open = false
                    onPick(id)
                })
            }
        }
    }
}

/** Settings → Models: Lynxce (credits), my API keys (billed by the vendor), and local models on the user's network. */
@Composable
fun ModelSourcesScreen(model: AppViewModel, onBack: () -> Unit, onCredits: () -> Unit) {
    val session by model.session.collectAsStateWithLifecycle()
    val backend = (session as? SessionState.Ready)?.backend ?: return
    val store = remember(backend) { model.modelKeys }
    val phone = model.phoneModels
    val onPhone = store?.onPhone == true
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    val settings by model.settings.collectAsStateWithLifecycle()
    val models by model.models.collectAsStateWithLifecycle()
    val balance by model.balance.collectAsStateWithLifecycle()
    val selection by phone.selection.collectAsStateWithLifecycle()
    val phoneKeys by phone.ownKeys.collectAsStateWithLifecycle()
    val local by phone.local.collectAsStateWithLifecycle()
    var serverList by remember { mutableStateOf<OwnKeyList?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var actionError by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf<String?>(null) }
    var adding by remember { mutableStateOf(false) }
    var addingLocal by remember { mutableStateOf(false) }
    var removing by remember { mutableStateOf<OwnKey?>(null) }
    var removingLocal by remember { mutableStateOf<LocalServer?>(null) }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(store, reload) {
        if (store == null || onPhone) return@LaunchedEffect
        loadError = null
        runCatching { store.list() }
            .onSuccess { serverList = it; model.setServerKeys(it) }
            .onFailure { loadError = resources.describe(it) }
    }
    val keyInUse = selection?.takeIf { it.source == PhoneSelection.Source.Key }
    val keys: OwnKeyList? = if (onPhone) OwnKeyList(phoneKeys, keyInUse?.id, keyInUse?.model) else serverList

    fun leave() {
        val server = store as? ServerModelKeys ?: return
        busy = LEAVE
        actionError = null
        scope.launch {
            runCatching { server.leave() }
                .onSuccess { serverList = it; model.setServerKeys(it) }
                .onFailure { actionError = resources.describe(it) }
            busy = null
        }
    }

    fun act(id: String, block: suspend () -> Unit) {
        busy = id
        actionError = null
        scope.launch {
            runCatching { block() }.onFailure { actionError = resources.describe(it) }
            busy = null
        }
    }

    val palette = LocalPalette.current
    Column(Modifier.fillMaxSize()) {
        TopBar(leading = { BackButton(onBack) }) { TopBarTitle(stringResource(R.string.settings_model)) }
        Column(
            Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp)
                .navigationBarsPadding(),
        ) {
            Text(
                stringResource(if (backend is ServerBackend && !backend.isCloud) R.string.models_body_server else R.string.models_body),
                style = MaterialTheme.typography.bodyMedium,
                color = palette.secondary,
                modifier = Modifier.padding(horizontal = 4.dp, vertical = 8.dp),
            )

            if (backend is ServerBackend && !backend.isCloud) {
                // A self-hosted server: its admin's models, or one of my keys.
                SourceHeader(stringResource(R.string.models_server_title), stringResource(R.string.models_server_billing))
                Card {
                    SourceRow("server", stringResource(R.string.models_server_default), stringResource(R.string.models_server_body)) {
                        if (keys != null && keys.inUse == null) InUse(stringResource(R.string.models_in_use))
                    }
                    if (keys?.inUse != null) LeaveRow(stringResource(R.string.models_server_use), busy == LEAVE) { leave() }
                }
            } else {
            // Lynxce
            SourceHeader(stringResource(R.string.models_lynxce_title), stringResource(R.string.models_lynxce_billing))
            Card {
                when {
                    backend is LynxceBackend -> {
                        val options = listOf<Pair<String?, String>>(null to stringResource(R.string.settings_model_auto)) + models.map { it.id to it.name }
                        options.forEachIndexed { index, (id, name) ->
                            if (index > 0) HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                            Row(
                                Modifier.fillMaxWidth().clickable {
                                    phone.useLynxce()
                                    model.setModel(id)
                                }.padding(horizontal = 16.dp, vertical = 14.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(name, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                                if (selection == null && settings.model == id) Icon(Icons.Rounded.Check, contentDescription = null, tint = palette.text)
                            }
                        }
                        HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                        CreditsRow(balance, onCredits)
                    }
                    backend is ServerBackend -> {
                        SourceRow("lynxce", stringResource(R.string.models_lynxce_title), stringResource(R.string.models_lynxce_cloud)) {
                            if (keys != null && keys.inUse == null) InUse(stringResource(R.string.models_in_use))
                        }
                        if (keys?.inUse != null) LeaveRow(stringResource(R.string.models_lynxce_use), busy == LEAVE) { leave() }
                        HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                        CreditsRow(balance, onCredits)
                    }
                    else -> SourceRow(
                        "lynxce",
                        stringResource(R.string.models_lynxce_sign_in),
                        stringResource(R.string.models_lynxce_sign_in_body),
                        onClick = { model.signOut() },
                    ) { Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = palette.secondary) }
                }
            }

            }

            // My API keys
            SourceHeader(stringResource(R.string.models_keys_title), stringResource(R.string.models_keys_billing)) {
                TextButton(onClick = { adding = true }, enabled = store != null) {
                    Icon(Icons.Rounded.Add, contentDescription = null, modifier = Modifier.size(18.dp), tint = palette.text)
                    Spacer(Modifier.width(4.dp))
                    Text(stringResource(R.string.models_keys_add), color = palette.text)
                }
            }
            Card {
                when {
                    loadError != null -> Column(Modifier.padding(16.dp)) {
                        Text(loadError.orEmpty(), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium)
                        TextButton(onClick = { reload++ }) { Text(stringResource(R.string.chat_retry), color = palette.text) }
                    }
                    keys == null -> Box(Modifier.fillMaxWidth().padding(20.dp), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp)
                    }
                    keys.keys.isEmpty() -> Column(Modifier.fillMaxWidth().clickable { adding = true }.padding(16.dp)) {
                        Text(stringResource(R.string.models_keys_empty_title), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                        Text(stringResource(R.string.models_keys_empty_body), style = MaterialTheme.typography.bodySmall, color = palette.secondary)
                    }
                    else -> keys.keys.forEachIndexed { index, key ->
                        if (index > 0) HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 60.dp))
                        val inUse = if (keys.inUse == key.id) keys.selectedModel else null
                        SourceRow(
                            if (key.vendor == VendorCompany.CUSTOM) VendorCompany.CUSTOM else phone.company(key),
                            keyName(key, phone),
                            key.keyHint + " · " + stringResource(R.string.models_count, key.models.size),
                        ) {
                            when {
                                busy == key.id -> CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                                inUse != null -> InUse(inUse)
                                key.models.isNotEmpty() -> UseMenu(key.models.map { it.id to it.label }) { choice ->
                                    act(key.id) {
                                        val next = store!!.use(key.id, choice)
                                        if (!onPhone) { serverList = next; model.setServerKeys(next) }
                                    }
                                }
                            }
                            IconButton(onClick = { removing = key }) {
                                Icon(Icons.Rounded.DeleteOutline, contentDescription = stringResource(R.string.models_keys_remove), tint = palette.secondary)
                            }
                        }
                    }
                }
            }
            actionError?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(start = 16.dp, top = 6.dp)) }
            Footer(stringResource(keptFooter(store?.place)))

            // Local models (phone only)
            if (onPhone) {
                SourceHeader(stringResource(R.string.models_local_title), stringResource(R.string.models_local_billing))
                Card {
                    local.forEachIndexed { index, server ->
                        if (index > 0) HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 60.dp))
                        val inUse = selection?.takeIf { it.source == PhoneSelection.Source.Local && it.id == server.id }?.model
                        SourceRow("ollama", server.name, server.host + " · " + stringResource(R.string.models_count, server.models.size)) {
                            if (inUse != null) InUse(inUse) else UseMenu(server.models.map { it.id to it.label }) { phone.useLocal(server.id, it) }
                            IconButton(onClick = { removingLocal = server }) {
                                Icon(Icons.Rounded.DeleteOutline, contentDescription = stringResource(R.string.models_keys_remove), tint = palette.secondary)
                            }
                        }
                        HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                    }
                    Row(
                        Modifier.fillMaxWidth().clickable { addingLocal = true }.padding(horizontal = 16.dp, vertical = 14.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Rounded.Add, contentDescription = null, tint = palette.text)
                        Spacer(Modifier.width(12.dp))
                        Text(stringResource(R.string.models_local_add), style = MaterialTheme.typography.bodyLarge)
                    }
                }
                Footer(stringResource(R.string.models_local_footer))
            }
            Spacer(Modifier.height(32.dp))
        }
    }

    if (adding && store != null) {
        AddModelKeyDialog(
            store = store,
            phone = phone,
            onDismiss = { adding = false },
            onChanged = { if (!onPhone) { serverList = it; model.setServerKeys(it) } },
        )
    }
    if (addingLocal) {
        LocalModelDialog(phone, onDismiss = { addingLocal = false }, onUsed = { addingLocal = false })
    }
    removing?.let { key ->
        AlertDialog(
            onDismissRequest = { removing = null },
            title = { Text(stringResource(R.string.models_keys_remove_confirm), style = MaterialTheme.typography.titleMedium) },
            confirmButton = {
                TextButton(onClick = {
                    removing = null
                    act(key.id) {
                        store!!.remove(key.id)
                        if (!onPhone) store.list().let { serverList = it; model.setServerKeys(it) }
                    }
                }) { Text(stringResource(R.string.models_keys_remove), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { removing = null }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
    removingLocal?.let { server ->
        AlertDialog(
            onDismissRequest = { removingLocal = null },
            title = { Text(stringResource(R.string.models_local_remove_confirm), style = MaterialTheme.typography.titleMedium) },
            confirmButton = {
                TextButton(onClick = {
                    removingLocal = null
                    phone.removeLocal(server.id)
                }) { Text(stringResource(R.string.models_keys_remove), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { removingLocal = null }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
}

private const val LEAVE = "leave"

private fun keptFooter(place: KeyPlace?): Int = when (place) {
    KeyPlace.Cloud -> R.string.models_keys_kept_cloud
    KeyPlace.Server -> R.string.models_keys_kept_server
    else -> R.string.models_keys_kept_phone
}

/** Stop chatting on my own key (the key is kept). */
@Composable
private fun LeaveRow(title: String, busy: Boolean, onClick: () -> Unit) {
    val palette = LocalPalette.current
    HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
    Row(
        Modifier.fillMaxWidth().clickable(enabled = !busy, onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(title, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        if (busy) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
    }
}

/** Credits & top-up (Android recharges in a Custom Tab from that screen). */
@Composable
private fun CreditsRow(balance: BalanceState?, onCredits: () -> Unit) {
    val palette = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().clickable(onClick = onCredits).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(stringResource(R.string.settings_recharge), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        balance?.let { BalanceText(it, MaterialTheme.typography.bodyLarge, color = palette.secondary) }
        Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = palette.secondary)
    }
}

private enum class AddStep { Pick, Key, Done }

/**
 * Add one of the user's own vendor API keys: pick a company, then its plan and the key, then the model to chat on
 * once the vendor accepts the key. [company] starts at the key step; [onUsed] follows choosing the model.
 */
@Composable
fun AddModelKeyDialog(
    store: ModelKeyStore,
    phone: PhoneModels,
    onDismiss: () -> Unit,
    onChanged: (OwnKeyList) -> Unit,
    company: VendorCompany? = null,
    onUsed: (() -> Unit)? = null,
) {
    val palette = LocalPalette.current
    val resources = LocalResources.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var catalog by remember { mutableStateOf<VendorCatalog?>(null) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var step by remember { mutableStateOf(if (company != null) AddStep.Key else AddStep.Pick) }
    var more by remember { mutableStateOf(false) }
    var chosen by remember { mutableStateOf(company) }
    var planId by remember { mutableStateOf(company?.plans?.firstOrNull()?.id.orEmpty()) }
    var apiKey by remember { mutableStateOf("") }
    var baseUrl by remember { mutableStateOf("") }
    var label by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var added by remember { mutableStateOf<OwnKey?>(null) }
    var modelId by remember { mutableStateOf("") }
    var reload by remember { mutableStateOf(0) }

    LaunchedEffect(reload) {
        loadError = null
        runCatching { store.vendors() }
            .onSuccess { loaded ->
                catalog = loaded
                // A tile picked before the server's list arrived: use that company's plans from it.
                chosen?.takeIf { it.id != VendorCompany.CUSTOM }?.let { picked ->
                    VendorCompany.group(loaded.vendors).firstOrNull { it.id == picked.id }?.let { fresh ->
                        chosen = fresh
                        if (fresh.plans.none { it.id == planId }) planId = fresh.plans.firstOrNull()?.id.orEmpty()
                    }
                }
            }
            .onFailure { loadError = resources.describe(it) }
    }
    val custom = chosen?.id == VendorCompany.CUSTOM
    val plan: KeyVendor? = chosen?.plans?.firstOrNull { it.id == planId }
    val canSave = apiKey.isNotBlank() && (!custom || baseUrl.isNotBlank())

    fun choose(next: VendorCompany) {
        chosen = next
        planId = next.plans.firstOrNull()?.id.orEmpty()
        apiKey = ""
        baseUrl = ""
        label = ""
        error = null
        step = AddStep.Key
    }

    fun save() {
        val picked = chosen ?: return
        if (busy || !canSave) return
        busy = true
        error = null
        val request = if (custom) {
            NewOwnKey(VendorCompany.CUSTOM, apiKey.trim(), label.trim(), baseUrl.trim())
        } else {
            NewOwnKey(planId.ifEmpty { picked.plans.first().id }, apiKey.trim())
        }
        scope.launch {
            runCatching { store.add(request) }
                .onSuccess { key ->
                    apiKey = ""
                    added = key
                    modelId = key.models.firstOrNull()?.id.orEmpty()
                    step = AddStep.Done
                    runCatching { store.list() }.onSuccess(onChanged)
                }
                .onFailure { error = resources.describe(it) }
            busy = false
        }
    }

    fun useModel() {
        val key = added ?: return
        if (modelId.isEmpty() || busy) return
        busy = true
        error = null
        scope.launch {
            runCatching { store.use(key.id, modelId) }
                .onSuccess {
                    onChanged(it)
                    onDismiss()
                    onUsed?.invoke()
                }
                .onFailure { error = resources.describe(it) }
            busy = false
        }
    }

    val title = when (step) {
        AddStep.Pick -> stringResource(R.string.models_add_title)
        AddStep.Done -> stringResource(R.string.models_add_done_title)
        AddStep.Key -> if (custom) {
            stringResource(R.string.models_add_custom)
        } else {
            stringResource(R.string.models_add_vendor_title, companyName(chosen?.id.orEmpty(), chosen?.plans?.firstOrNull()?.name.orEmpty()))
        }
    }

    Dialog(onDismissRequest = { if (!busy) onDismiss() }, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).imePadding()) {
            TopBar(
                leading = {
                    if (step == AddStep.Key && company == null) {
                        BackButton { step = AddStep.Pick; error = null }
                    } else if (step != AddStep.Done) {
                        IconButton(onClick = onDismiss) { Icon(Icons.Rounded.Close, contentDescription = stringResource(R.string.common_cancel)) }
                    }
                },
                trailing = {
                    if (step == AddStep.Key) {
                        if (busy) {
                            CircularProgressIndicator(Modifier.padding(end = 16.dp).size(20.dp), strokeWidth = 2.dp)
                        } else {
                            TextButton(onClick = ::save, enabled = canSave) {
                                Text(stringResource(R.string.models_add_verify), fontWeight = FontWeight.SemiBold, color = if (canSave) palette.text else palette.secondary)
                            }
                        }
                    }
                },
            ) { TopBarTitle(title) }
            Column(
                Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).navigationBarsPadding(),
            ) {
                when (step) {
                    AddStep.Pick -> {
                        val loaded = catalog
                        when {
                            loadError != null -> Column(Modifier.padding(vertical = 24.dp)) {
                                Text(loadError.orEmpty(), color = MaterialTheme.colorScheme.error)
                                TextButton(onClick = { reload++ }) { Text(stringResource(R.string.chat_retry), color = palette.text) }
                            }
                            loaded == null -> Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
                            else -> {
                                val companies = VendorCompany.group(loaded.vendors)
                                Text(
                                    stringResource(
                                when (store.place) {
                                    KeyPlace.Phone -> R.string.models_add_hint_phone
                                    KeyPlace.Cloud -> R.string.models_add_hint_cloud
                                    KeyPlace.Server -> R.string.models_add_hint_server
                                },
                            ),
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = palette.secondary,
                                    modifier = Modifier.padding(vertical = 12.dp),
                                )
                                VendorGrid(companies.filter { it.featured }, ::choose)
                                val others = companies.filterNot { it.featured }
                                if (others.isNotEmpty()) {
                                    if (more) VendorGrid(others, ::choose) else TextButton(onClick = { more = true }) {
                                        Text(stringResource(R.string.models_add_more, others.size), color = palette.text)
                                    }
                                }
                                if (loaded.customAllowed) {
                                    Row(
                                        Modifier
                                            .fillMaxWidth()
                                            .padding(top = 8.dp)
                                            .clip(RoundedCornerShape(14.dp))
                                            .border(BorderStroke(1.dp, palette.hairline), RoundedCornerShape(14.dp))
                                            .clickable { choose(VendorCompany(VendorCompany.CUSTOM, emptyList())) }
                                            .padding(14.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        VendorLogo(VendorCompany.CUSTOM, 30.dp)
                                        Spacer(Modifier.width(12.dp))
                                        Text(stringResource(R.string.models_add_custom), modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
                                        Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = palette.secondary)
                                    }
                                }
                                Spacer(Modifier.height(24.dp))
                            }
                        }
                    }
                    AddStep.Key -> Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.padding(top = 12.dp)) {
                        val plans = chosen?.plans.orEmpty()
                        if (!custom && plans.size > 1) {
                            Text(stringResource(R.string.models_add_plan), style = MaterialTheme.typography.labelLarge, color = palette.secondary)
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                plans.forEach { option ->
                                    val selected = option.id == planId
                                    Text(
                                        option.name,
                                        style = MaterialTheme.typography.labelLarge,
                                        color = if (selected) palette.background else palette.text,
                                        modifier = Modifier
                                            .clip(CircleShape)
                                            .background(if (selected) palette.text else palette.raised)
                                            .clickable { planId = option.id }
                                            .padding(horizontal = 12.dp, vertical = 7.dp),
                                    )
                                }
                            }
                        }
                        if (custom) {
                            FormField(baseUrl, { baseUrl = it; error = null }, stringResource(R.string.models_add_base_url), keyboardType = KeyboardType.Uri, placeholder = "https://api.example.com/v1")
                            FormField(label, { label = it }, stringResource(R.string.models_add_name))
                        }
                        FormField(
                            apiKey,
                            { apiKey = it; error = null },
                            "API Key",
                            password = true,
                            imeAction = ImeAction.Done,
                            onDone = ::save,
                            placeholder = plan?.apiKeyPrefix?.takeIf { it.isNotEmpty() }?.let { "$it…" } ?: stringResource(R.string.models_add_key_placeholder),
                        )
                        Text(
                            stringResource(
                                when (store.place) {
                                    KeyPlace.Phone -> R.string.models_add_kept_phone
                                    KeyPlace.Cloud -> R.string.models_add_kept_cloud
                                    KeyPlace.Server -> R.string.models_add_kept_server
                                },
                            ),
                            style = MaterialTheme.typography.bodySmall,
                            color = palette.secondary,
                        )
                        if (!custom && plan != null) {
                            Text(stringResource(R.string.models_add_endpoint) + " " + plan.baseUrl, style = MaterialTheme.typography.bodySmall, color = palette.secondary)
                            plan.docs?.takeIf { it.isNotEmpty() }?.let { docs ->
                                Row(
                                    Modifier.clip(RoundedCornerShape(8.dp)).clickable {
                                        runCatching { context.startActivity(Intent(Intent.ACTION_VIEW, docs.toUri())) }
                                    }.padding(vertical = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Text(stringResource(R.string.models_add_get_key), style = MaterialTheme.typography.labelLarge)
                                    Spacer(Modifier.width(4.dp))
                                    Icon(Icons.AutoMirrored.Rounded.OpenInNew, contentDescription = null, modifier = Modifier.size(14.dp))
                                }
                            }
                        }
                        error?.let {
                            Text(
                                it,
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodyMedium,
                                modifier = Modifier.clip(RoundedCornerShape(12.dp)).background(palette.surface).padding(12.dp).fillMaxWidth(),
                            )
                        }
                    }
                    AddStep.Done -> Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.padding(top = 12.dp)) {
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(palette.surface).padding(14.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(Icons.Rounded.CheckCircle, contentDescription = null, tint = Color(0xFF34C759))
                            Spacer(Modifier.width(10.dp))
                            Text(stringResource(R.string.models_add_found, added?.models?.size ?: 0), style = MaterialTheme.typography.bodyLarge)
                        }
                        val choices = added?.models.orEmpty()
                        if (choices.isNotEmpty()) {
                            Text(stringResource(R.string.models_add_choose_model), style = MaterialTheme.typography.labelLarge, color = palette.secondary)
                            Card {
                                choices.forEachIndexed { index, choice ->
                                    if (index > 0) HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                                    Row(
                                        Modifier.fillMaxWidth().clickable { modelId = choice.id }.padding(horizontal = 16.dp, vertical = 14.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Text(choice.label, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyLarge)
                                        if (modelId == choice.id) Icon(Icons.Rounded.Check, contentDescription = null, tint = palette.text)
                                    }
                                }
                            }
                        }
                        error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
                        Button(onClick = ::useModel, enabled = modelId.isNotEmpty() && !busy, modifier = Modifier.fillMaxWidth().height(50.dp)) {
                            if (busy) CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = MaterialTheme.colorScheme.onPrimary)
                            else Text(stringResource(R.string.models_add_use_model), style = MaterialTheme.typography.titleSmall)
                        }
                        if (onUsed == null) {
                            OutlinedButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth().height(50.dp)) {
                                Text(stringResource(R.string.models_add_later), color = palette.text)
                            }
                        }
                        Spacer(Modifier.height(24.dp))
                    }
                }
            }
        }
    }
}

/** Connect the Ollama or LM Studio running on a computer on the same network. */
@Composable
fun LocalModelDialog(phone: PhoneModels, onDismiss: () -> Unit, onUsed: (LocalServer) -> Unit) {
    val palette = LocalPalette.current
    val resources = LocalResources.current
    val scope = rememberCoroutineScope()
    var address by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var found by remember { mutableStateOf<LocalServer?>(null) }
    var modelId by remember { mutableStateOf("") }

    fun connect() {
        if (busy || address.isBlank()) return
        busy = true
        error = null
        scope.launch {
            runCatching { phone.addLocal(address) }
                .onSuccess { found = it; modelId = it.models.firstOrNull()?.id.orEmpty() }
                .onFailure { error = resources.describe(it) }
            busy = false
        }
    }

    Dialog(onDismissRequest = { if (!busy) onDismiss() }, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).imePadding()) {
            TopBar(
                leading = { IconButton(onClick = onDismiss) { Icon(Icons.Rounded.Close, contentDescription = stringResource(R.string.common_cancel)) } },
                trailing = {
                    val server = found
                    when {
                        busy -> CircularProgressIndicator(Modifier.padding(end = 16.dp).size(20.dp), strokeWidth = 2.dp)
                        server != null -> TextButton(onClick = {
                            phone.useLocal(server.id, modelId)
                            onUsed(server)
                        }, enabled = modelId.isNotEmpty()) { Text(stringResource(R.string.models_local_use), fontWeight = FontWeight.SemiBold, color = palette.text) }
                        else -> TextButton(onClick = ::connect, enabled = address.isNotBlank()) {
                            Text(stringResource(R.string.models_local_connect), fontWeight = FontWeight.SemiBold, color = if (address.isNotBlank()) palette.text else palette.secondary)
                        }
                    }
                },
            ) { TopBarTitle(stringResource(R.string.models_local_add_title)) }
            Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Spacer(Modifier.height(4.dp))
                FormField(
                    address,
                    { address = it; found = null; error = null },
                    stringResource(R.string.models_local_address),
                    keyboardType = KeyboardType.Uri,
                    imeAction = ImeAction.Go,
                    onDone = ::connect,
                    placeholder = "192.168.1.8:11434",
                )
                Text(stringResource(R.string.models_local_address_footer), style = MaterialTheme.typography.bodySmall, color = palette.secondary)
                error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodyMedium) }
                found?.let { server ->
                    Text(stringResource(R.string.models_add_choose_model), style = MaterialTheme.typography.labelLarge, color = palette.secondary)
                    Card {
                        server.models.forEachIndexed { index, choice ->
                            if (index > 0) HorizontalDivider(color = palette.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
                            Row(
                                Modifier.fillMaxWidth().clickable { modelId = choice.id }.padding(horizontal = 16.dp, vertical = 14.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(choice.label, modifier = Modifier.weight(1f))
                                if (modelId == choice.id) Icon(Icons.Rounded.Check, contentDescription = null, tint = palette.text)
                            }
                        }
                    }
                }
            }
        }
    }
}

/**
 * "Use without signing in": choose the model Bots reply with — the user's own vendor API key, or an Ollama / LM
 * Studio on their network. Picking one starts the app in phone-only use.
 */
@Composable
fun ModelSetupScreen(phone: PhoneModels, onBack: () -> Unit, onStart: () -> Unit) {
    val palette = LocalPalette.current
    val companies = remember { VendorCompany.group(phone.bundled) }
    var company by remember { mutableStateOf<VendorCompany?>(null) }
    var addingLocal by remember { mutableStateOf(false) }
    var more by remember { mutableStateOf(false) }
    val selection by phone.selection.collectAsStateWithLifecycle()
    val keys by phone.ownKeys.collectAsStateWithLifecycle()
    val local by phone.local.collectAsStateWithLifecycle()
    val current = remember(selection, keys, local) { phone.current { it.name } }
    val ready = current != null && phone.hasModel

    Column(Modifier.fillMaxSize()) {
        TopBar(leading = { BackButton(onBack) }) {
            Text(stringResource(R.string.models_setup_mode), style = MaterialTheme.typography.labelMedium, color = palette.secondary)
        }
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp),
            verticalArrangement = Arrangement.spacedBy(22.dp),
        ) {
            Row(verticalAlignment = Alignment.Bottom) {
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(stringResource(R.string.models_setup_title), style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text(stringResource(R.string.models_setup_body), style = MaterialTheme.typography.bodyMedium, color = palette.secondary)
                }
                BotCharacter(Look.chief, 64.dp, seed = "chief")
            }
            Column {
                Text(stringResource(R.string.models_setup_keys), style = MaterialTheme.typography.titleMedium)
                Text(stringResource(R.string.models_setup_keys_note), style = MaterialTheme.typography.bodySmall, color = palette.secondary, modifier = Modifier.padding(bottom = 12.dp))
                VendorGrid(companies.filter { it.featured }) { company = it }
                val others = companies.filterNot { it.featured }
                if (more) VendorGrid(others) { company = it }
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    if (!more && others.isNotEmpty()) {
                        OutlinedButton(onClick = { more = true }) { Text(stringResource(R.string.models_add_more, others.size), color = palette.text) }
                    }
                    OutlinedButton(onClick = { company = VendorCompany(VendorCompany.CUSTOM, emptyList()) }) {
                        Icon(Icons.Rounded.Add, contentDescription = null, modifier = Modifier.size(16.dp), tint = palette.text)
                        Spacer(Modifier.width(4.dp))
                        Text(stringResource(R.string.models_add_custom_short), color = palette.text)
                    }
                }
            }
            Column {
                Text(stringResource(R.string.models_local_title), style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(bottom = 12.dp))
                Row(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(palette.surface).clickable { addingLocal = true }.padding(14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    VendorLogo("ollama", 36.dp)
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(stringResource(R.string.models_setup_local), style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.SemiBold)
                        Text(stringResource(R.string.models_setup_local_body), style = MaterialTheme.typography.bodySmall, color = palette.secondary)
                    }
                    Icon(Icons.Rounded.ChevronRight, contentDescription = null, tint = palette.secondary)
                }
            }
            Row(verticalAlignment = Alignment.Top) {
                VendorLogo("lynxce", 22.dp)
                Spacer(Modifier.width(10.dp))
                Column {
                    Text(stringResource(R.string.models_setup_lynxce), style = MaterialTheme.typography.bodySmall, color = palette.secondary)
                    TextButton(onClick = onBack, modifier = Modifier.padding(start = 0.dp)) {
                        Text(stringResource(R.string.models_lynxce_sign_in), color = palette.text, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
        if (ready) {
            Button(
                onClick = onStart,
                modifier = Modifier.fillMaxWidth().navigationBarsPadding().padding(horizontal = 20.dp, vertical = 10.dp).height(52.dp),
            ) { Text(stringResource(R.string.models_setup_start, current!!.first), style = MaterialTheme.typography.titleSmall, maxLines = 1) }
        } else {
            Spacer(Modifier.navigationBarsPadding())
        }
    }
    company?.let { picked ->
        AddModelKeyDialog(
            store = phone,
            phone = phone,
            company = picked,
            onDismiss = { company = null },
            onChanged = {},
            onUsed = onStart,
        )
    }
    if (addingLocal) {
        LocalModelDialog(phone, onDismiss = { addingLocal = false }, onUsed = {
            addingLocal = false
            onStart()
        })
    }
}
