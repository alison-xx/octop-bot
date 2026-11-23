package io.github.alisonxx.octopbot.ui.settings

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.BalanceState
import io.github.alisonxx.octopbot.app.UsageState
import io.github.alisonxx.octopbot.net.ServerProtocol
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.BalanceText
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.TopBarTitle
import io.github.alisonxx.octopbot.ui.common.openCheckout
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import io.github.alisonxx.octopbot.ui.theme.OctopTheme
import java.text.DecimalFormat
import java.text.DecimalFormatSymbols
import java.util.Locale

/** Settings → Credits & top-up: the balance, Top up, and (on an Octop server) the last 30 days of usage. */
@Composable
fun CreditsScreen(model: AppViewModel, onBack: () -> Unit) {
    val balance by model.balance.collectAsStateWithLifecycle()
    val usage by model.usage.collectAsStateWithLifecycle()
    val refreshing by model.creditsRefreshing.collectAsStateWithLifecycle()
    val recharging by model.recharging.collectAsStateWithLifecycle()
    val context = LocalContext.current
    LaunchedEffect(Unit) { model.refreshCredits() }
    Credits(
        balance = balance ?: BalanceState.Loading,
        usage = usage,
        refreshing = refreshing,
        recharging = recharging,
        onBack = onBack,
        onRefresh = model::refreshCredits,
        onRecharge = { model.recharge { openCheckout(context, it) } },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Credits(
    balance: BalanceState,
    usage: UsageState?,
    refreshing: Boolean,
    recharging: Boolean,
    onBack: () -> Unit,
    onRefresh: () -> Unit,
    onRecharge: () -> Unit,
) {
    val palette = LocalPalette.current
    Column(Modifier.fillMaxSize()) {
        TopBar(leading = { BackButton(onBack) }) { TopBarTitle(stringResource(R.string.credits_title)) }
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = onRefresh, modifier = Modifier.weight(1f)) {
            Column(
                Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp)
                    .navigationBarsPadding(),
            ) {
                Column(
                    Modifier
                        .padding(top = 8.dp)
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(22.dp))
                        .background(palette.surface)
                        .padding(20.dp),
                ) {
                    Text(stringResource(R.string.credits_balance_label), style = MaterialTheme.typography.labelLarge, color = palette.secondary)
                    Spacer(Modifier.height(6.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        BalanceText(
                            balance,
                            style = MaterialTheme.typography.headlineLarge,
                            format = { it },
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            if (balance == BalanceState.Failed) stringResource(R.string.credits_balance_failed) else stringResource(R.string.credits_unit),
                            style = MaterialTheme.typography.titleMedium,
                            color = palette.secondary,
                        )
                        if (balance == BalanceState.Failed) {
                            TextButton(onClick = onRefresh) { Text(stringResource(R.string.chat_retry)) }
                        }
                    }
                    if ((balance as? BalanceState.Value)?.low == true) {
                        Spacer(Modifier.height(8.dp))
                        Text(stringResource(R.string.credits_low_note), style = MaterialTheme.typography.bodyMedium, color = palette.secondary)
                    }
                    Spacer(Modifier.height(16.dp))
                    Button(
                        onClick = onRecharge,
                        enabled = !recharging,
                        modifier = Modifier.fillMaxWidth().height(48.dp),
                        colors = ButtonDefaults.buttonColors(containerColor = palette.text, contentColor = palette.background),
                    ) {
                        if (recharging) {
                            CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = palette.secondary)
                        } else {
                            Text(stringResource(R.string.credits_recharge), style = MaterialTheme.typography.titleMedium)
                        }
                    }
                }

                usage?.let { UsageSection(it) }

                Text(
                    stringResource(R.string.credits_footer),
                    style = MaterialTheme.typography.bodySmall,
                    color = palette.secondary,
                    modifier = Modifier.padding(start = 16.dp, top = 16.dp, end = 16.dp, bottom = 32.dp),
                )
            }
        }
    }
}

@Composable
private fun UsageSection(usage: UsageState) {
    val palette = LocalPalette.current
    Text(
        stringResource(R.string.credits_usage_title),
        style = MaterialTheme.typography.labelLarge,
        color = palette.secondary,
        modifier = Modifier.padding(start = 16.dp, top = 22.dp, bottom = 6.dp),
    )
    val byBot = usage.byBot
    val byModel = usage.byModel
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp)).background(palette.surface)) {
        when {
            usage.loading && byBot == null && byModel == null -> Row(
                Modifier.fillMaxWidth().padding(20.dp),
                horizontalArrangement = Arrangement.Center,
            ) { CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp) }
            byBot == null && byModel == null -> UsageNote(stringResource(R.string.credits_usage_failed))
            else -> {
                val totals = byBot ?: byModel!!
                Row(Modifier.fillMaxWidth().padding(16.dp)) {
                    UsageFigure(stringResource(R.string.credits_usage_tokens), tokens(totals.totalTokens), Modifier.weight(1f))
                    UsageFigure(stringResource(R.string.credits_usage_calls), tokens(totals.modelCalls), Modifier.weight(1f))
                }
                if (totals.totalTokens == 0L && byBot?.buckets.isNullOrEmpty() && byModel?.buckets.isNullOrEmpty()) {
                    Divider()
                    UsageNote(stringResource(R.string.credits_usage_empty))
                } else {
                    byBot?.let { UsageBuckets(stringResource(R.string.credits_usage_by_bot), it.buckets) }
                    byModel?.let { UsageBuckets(stringResource(R.string.credits_usage_by_model), it.buckets) }
                    if (usage.failed) {
                        Divider()
                        UsageNote(stringResource(R.string.credits_usage_failed))
                    }
                }
            }
        }
    }
}

@Composable
private fun Divider() {
    HorizontalDivider(color = LocalPalette.current.hairline.copy(alpha = 0.6f), modifier = Modifier.padding(start = 16.dp))
}

@Composable
private fun UsageFigure(label: String, value: String, modifier: Modifier) {
    Column(modifier) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = LocalPalette.current.secondary)
        Text(value, style = MaterialTheme.typography.titleLarge)
    }
}

@Composable
private fun UsageBuckets(title: String, buckets: List<ServerProtocol.UsageBucket>) {
    val palette = LocalPalette.current
    Divider()
    Text(
        title,
        style = MaterialTheme.typography.labelLarge,
        color = palette.secondary,
        modifier = Modifier.padding(start = 16.dp, top = 12.dp, bottom = 2.dp),
    )
    if (buckets.isEmpty()) {
        UsageNote(stringResource(R.string.credits_usage_empty))
        return
    }
    buckets.forEach { bucket ->
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                bucket.label,
                style = MaterialTheme.typography.bodyLarge,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Text(tokens(bucket.totalTokens), style = MaterialTheme.typography.bodyLarge, color = palette.secondary)
        }
    }
    Spacer(Modifier.height(6.dp))
}

@Composable
private fun UsageNote(text: String) {
    Text(
        text,
        style = MaterialTheme.typography.bodyMedium,
        color = LocalPalette.current.secondary,
        modifier = Modifier.padding(16.dp),
    )
}

private fun tokens(value: Long): String = DecimalFormat("#,##0", DecimalFormatSymbols(Locale.US)).format(value)

@Preview(showBackground = true, backgroundColor = 0xFF000000, heightDp = 900)
@Composable
private fun CreditsPreview() {
    val bots = ServerProtocol.UsageSummary(
        1_234_567,
        321,
        listOf(ServerProtocol.UsageBucket("chief", "Chief", 900_000), ServerProtocol.UsageBucket("writer", "Writer", 334_567)),
    )
    val models = bots.copy(buckets = listOf(ServerProtocol.UsageBucket("deepseek-v3", "deepseek-v3", 1_234_567)))
    OctopTheme(dark = true) {
        Credits(BalanceState.Value(82.5), UsageState(loading = false, byBot = bots, byModel = models), false, false, {}, {}, {})
    }
}
