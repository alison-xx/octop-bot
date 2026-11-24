package io.github.alisonxx.octopbot.ui.editor

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.rounded.InsertDriveFile
import androidx.compose.material.icons.rounded.AudioFile
import androidx.compose.material.icons.rounded.Description
import androidx.compose.material.icons.rounded.FolderZip
import androidx.compose.material.icons.rounded.Image
import androidx.compose.material.icons.rounded.Schedule
import androidx.compose.material.icons.rounded.Slideshow
import androidx.compose.material.icons.rounded.TableChart
import androidx.compose.material.icons.rounded.VideoFile
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.alisonxx.octopbot.R
import io.github.alisonxx.octopbot.app.AppViewModel
import io.github.alisonxx.octopbot.app.describe
import io.github.alisonxx.octopbot.net.BotActivity
import io.github.alisonxx.octopbot.net.BotActivity.FileKind
import io.github.alisonxx.octopbot.net.BotActivity.LibraryFile
import io.github.alisonxx.octopbot.net.BotActivity.Period
import io.github.alisonxx.octopbot.net.BotActivity.UpcomingJob
import io.github.alisonxx.octopbot.net.ServerBackend
import io.github.alisonxx.octopbot.ui.common.BackButton
import io.github.alisonxx.octopbot.ui.common.TopBar
import io.github.alisonxx.octopbot.ui.common.TopBarTitle
import io.github.alisonxx.octopbot.ui.theme.LocalPalette
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.UUID

/** A server Bot's profile like Grok's: upcoming scheduled tasks and a library of the files it made. */
@Composable
fun BotActivityScreen(model: AppViewModel, botId: String, onBack: () -> Unit) {
    val bots by model.bots.collectAsStateWithLifecycle()
    val bot = bots.firstOrNull { it.id == botId }
    val server = model.server
    Column(Modifier.fillMaxSize()) {
        TopBar(leading = { BackButton(onBack) }) { TopBarTitle(bot?.name.orEmpty()) }
        if (server != null) BotActivityContent(model, server, botId)
    }
}

@Composable
private fun BotActivityContent(model: AppViewModel, server: ServerBackend, botId: String) {
    val palette = LocalPalette.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var library by rememberSaveable { mutableStateOf(false) }
    var jobs by remember { mutableStateOf<List<UpcomingJob>?>(null) }
    var files by remember { mutableStateOf<List<LibraryFile>?>(null) }
    var showAll by remember { mutableStateOf(false) }
    var changing by remember { mutableStateOf<String?>(null) }
    var opening by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val resources = context.resources

    suspend fun loadJobs() {
        runCatching { server.upcoming(botId) }
            .onSuccess { jobs = it; error = null }
            .onFailure { error = resources.describe(it) }
    }
    LaunchedEffect(library) {
        if (!library && jobs == null) loadJobs()
        if (library && files == null) {
            runCatching { server.library(botId) }
                .onSuccess { files = it; error = null }
                .onFailure { error = resources.describe(it) }
        }
    }

    LazyColumn(
        Modifier.fillMaxSize().navigationBarsPadding(),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                listOf(R.string.profile_activity to false, R.string.profile_library to true).forEachIndexed { index, (label, value) ->
                    SegmentedButton(
                        selected = library == value,
                        onClick = { library = value },
                        shape = SegmentedButtonDefaults.itemShape(index, 2),
                    ) { Text(stringResource(label)) }
                }
            }
        }
        error?.let { message ->
            item { Text(message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
        }
        if (!library) {
            item { Heading(stringResource(R.string.profile_upcoming)) }
            val list = jobs
            when {
                list == null -> item { Loading() }
                list.isEmpty() -> item { Empty(stringResource(R.string.profile_no_upcoming)) }
                else -> item {
                    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(palette.surface)) {
                        val shown = if (showAll) list else list.take(BotActivity.FIRST_SHOWN)
                        shown.forEachIndexed { index, job ->
                            if (index > 0) HorizontalDivider(color = palette.hairline)
                            val toggleLabel = stringResource(R.string.profile_toggle, job.name)
                            Row(
                                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(Icons.Rounded.Schedule, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(20.dp))
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(job.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Text(job.schedule, style = MaterialTheme.typography.bodySmall, color = palette.secondary, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                }
                                Switch(
                                    checked = job.enabled,
                                    enabled = job.canToggle && (changing == null || changing == job.id),
                                    onCheckedChange = { on ->
                                        changing = job.id
                                        jobs = list.map { if (it.id == job.id) it.copy(enabled = on) else it }
                                        scope.launch {
                                            runCatching { server.setCronEnabled(botId, job.id, on) }
                                                .onFailure { error = resources.describe(it) }
                                            loadJobs()
                                            changing = null
                                        }
                                    },
                                    modifier = Modifier.semantics { contentDescription = toggleLabel },
                                )
                            }
                        }
                        if (!showAll && list.size > BotActivity.FIRST_SHOWN) {
                            HorizontalDivider(color = palette.hairline)
                            TextButton(onClick = { showAll = true }, modifier = Modifier.fillMaxWidth()) {
                                Text(stringResource(R.string.profile_show_more), color = palette.secondary)
                            }
                        }
                    }
                }
            }
        } else {
            val list = files
            when {
                list == null -> item { Loading() }
                list.isEmpty() -> item { Empty(stringResource(R.string.profile_no_files)) }
                else -> BotActivity.grouped(list).forEach { (period, group) ->
                    item(key = "h-" + period.name) { Heading(stringResource(period.label)) }
                    items(group, key = { it.path }) { file ->
                        Row(
                            Modifier
                                .fillMaxWidth()
                                .clip(RoundedCornerShape(12.dp))
                                .clickable(enabled = opening == null) {
                                    opening = file.path
                                    scope.launch {
                                        runCatching { open(context, file, server.fileBytes(file.url)) }
                                            .onFailure { model.notice(resources.describe(it)) }
                                        opening = null
                                    }
                                }
                                .padding(horizontal = 8.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(BotActivity.kind(file).icon, contentDescription = null, tint = palette.secondary, modifier = Modifier.size(20.dp))
                            Spacer(Modifier.width(12.dp))
                            Text(file.name, style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.MiddleEllipsis, modifier = Modifier.weight(1f))
                            if (opening == file.path) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Heading(text: String) {
    Text(text, style = MaterialTheme.typography.titleSmall, color = LocalPalette.current.secondary, modifier = Modifier.padding(top = 10.dp))
}

@Composable
private fun Empty(text: String) {
    Text(text, style = MaterialTheme.typography.bodyMedium, color = LocalPalette.current.secondary)
}

@Composable
private fun Loading() {
    Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator(Modifier.size(24.dp)) }
}

private val Period.label: Int
    get() = when (this) {
        Period.Today -> R.string.profile_today
        Period.Week -> R.string.profile_week
        Period.Older -> R.string.profile_older
    }

private val FileKind.icon: ImageVector
    get() = when (this) {
        FileKind.Image -> Icons.Rounded.Image
        FileKind.Video -> Icons.Rounded.VideoFile
        FileKind.Audio -> Icons.Rounded.AudioFile
        FileKind.Sheet -> Icons.Rounded.TableChart
        FileKind.Slides -> Icons.Rounded.Slideshow
        FileKind.Archive -> Icons.Rounded.FolderZip
        FileKind.Document -> Icons.Rounded.Description
        FileKind.Other -> Icons.AutoMirrored.Rounded.InsertDriveFile
    }

/** Save to the app cache and open it in another app; with no viewer, offer the share sheet instead. */
private suspend fun open(context: Context, file: LibraryFile, bytes: ByteArray) {
    val local = withContext(Dispatchers.IO) {
        val folder = File(context.cacheDir, "shared/files/" + UUID.randomUUID()).apply { mkdirs() }
        File(folder, file.name.ifBlank { "download" }).apply { writeBytes(bytes) }
    }
    val uri = FileProvider.getUriForFile(context, context.packageName + ".photos", local)
    val type = file.mime ?: "application/octet-stream"
    val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, type).addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    try {
        context.startActivity(view)
    } catch (_: ActivityNotFoundException) {
        val send = Intent(Intent.ACTION_SEND).setType(type).putExtra(Intent.EXTRA_STREAM, uri)
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        send.clipData = ClipData.newRawUri(null, uri)
        context.startActivity(Intent.createChooser(send, null))
    }
}
