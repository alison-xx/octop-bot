package io.github.alisonxx.octopbot.ui.editor

import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalResources
import androidx.compose.ui.res.stringResource
import androidx.core.net.toUri
import androidx.compose.ui.unit.dp
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.describe
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.net.ServerProtocol.ComputerStatus
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.launch

/** Octop Bot cloud: is this Bot's computer running, and pause it to stop paying. */
@Composable
fun CloudComputerPanel(server: ServerBackend, botId: String) {
    val palette = LocalPalette.current
    val scope = rememberCoroutineScope()
    val context = LocalContext.current
    var status by remember(botId) { mutableStateOf<ComputerStatus?>(null) }
    var failed by remember(botId) { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var starting by remember { mutableStateOf(false) }
    var screenError by remember { mutableStateOf<String?>(null) }
    val resources = LocalResources.current
    LaunchedEffect(botId) {
        runCatching { server.computerStatus(botId) }
            .onSuccess { status = it }
            .onFailure { failed = true }
    }
    val label = when {
        starting -> stringResource(R.string.computer_starting)
        failed -> stringResource(R.string.computer_unavailable)
        status == null -> "…"
        else -> when (status!!.state) {
            ComputerStatus.State.None -> stringResource(R.string.computer_state_none)
            ComputerStatus.State.Running -> stringResource(R.string.computer_state_running)
            ComputerStatus.State.Paused -> stringResource(R.string.computer_state_paused)
        }
    }
    Column(Modifier.fillMaxWidth().padding(top = 6.dp)) {
        Text(stringResource(R.string.computer_header), style = MaterialTheme.typography.titleSmall, color = palette.secondary)
        Row(
            Modifier
                .fillMaxWidth()
                .padding(top = 8.dp)
                .clip(RoundedCornerShape(16.dp))
                .background(palette.surface)
                .padding(horizontal = 16.dp, vertical = 12.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.computer_title), style = MaterialTheme.typography.bodyMedium)
                Text(label, style = MaterialTheme.typography.bodySmall, color = palette.secondary)
            }
            if (status != null) {
                TextButton(
                    enabled = !busy,
                    onClick = {
                        busy = true
                        screenError = null
                        // Opening the screen starts or resumes the computer, which can take a minute or more.
                        starting = status?.state != ComputerStatus.State.Running
                        scope.launch {
                            runCatching { server.screenUrl(botId, control = status?.takeover == true) }
                                .onSuccess { url -> context.startActivity(Intent(Intent.ACTION_VIEW, url.toUri())) }
                                .onFailure { screenError = resources.describe(it) }
                            runCatching { server.computerStatus(botId) }.onSuccess { status = it }
                            starting = false
                            busy = false
                        }
                    },
                ) { Text(stringResource(R.string.computer_view)) }
                TextButton(
                    enabled = !busy,
                    onClick = {
                        busy = true
                        scope.launch {
                            runCatching { server.setTakeover(botId, status?.takeover != true) }.onSuccess { status = it }
                            busy = false
                        }
                    },
                ) { Text(stringResource(if (status?.takeover == true) R.string.computer_hand_back else R.string.computer_take_over)) }
            }
            if (status?.state == ComputerStatus.State.Running && status?.takeover != true) {
                TextButton(
                    enabled = !busy,
                    onClick = {
                        busy = true
                        scope.launch {
                            runCatching { server.pauseComputer(botId) }.onSuccess { status = it }
                            busy = false
                        }
                    },
                ) { Text(stringResource(R.string.computer_pause)) }
            }
        }
        screenError?.let {
            Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 6.dp, start = 4.dp, end = 4.dp))
        }
        Text(
            stringResource(R.string.computer_footer),
            style = MaterialTheme.typography.bodySmall,
            color = palette.secondary,
            modifier = Modifier.padding(top = 6.dp, start = 4.dp, end = 4.dp),
        )
    }
}
