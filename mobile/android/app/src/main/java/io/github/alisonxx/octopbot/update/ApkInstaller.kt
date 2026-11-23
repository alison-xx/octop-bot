package io.github.alisonxx.octopbot.update

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import java.io.File
import java.security.MessageDigest

/** Android side of installing an update: the signing-certificate check, the unknown-sources permission, the installer. */
object ApkInstaller {
    /** True when the APK at [apk] is this app, signed by exactly the certificates of the installed version. */
    fun matchesInstalled(context: Context, apk: File): Boolean {
        val pm = context.packageManager
        val archive = archiveInfo(pm, apk)?.takeIf { it.packageName == context.packageName } ?: return false
        return signersMatch(signers(installedInfo(pm, context.packageName)), signers(archive))
    }

    /** Pure comparison of two signer lists (DER certificates), by their SHA-256. */
    fun signersMatch(installed: List<ByteArray>, archive: List<ByteArray>): Boolean {
        val a = installed.map(::digest).toSet()
        return a.isNotEmpty() && a == archive.map(::digest).toSet()
    }

    /** Android 8+ asks the user once to let this app install packages. */
    fun canInstall(context: Context): Boolean = context.packageManager.canRequestPackageInstalls()

    fun unknownSourcesIntent(context: Context): Intent =
        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, "package:${context.packageName}".toUri())

    /** The system installer for [apk], through the app's FileProvider (`cache/updates/`). */
    fun installIntent(context: Context, apk: File): Intent {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.photos", apk)
        return Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }

    private fun digest(cert: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(cert).joinToString("") { "%02x".format(it) }

    @Suppress("DEPRECATION")
    private fun signers(info: PackageInfo?): List<ByteArray> {
        info ?: return emptyList()
        return if (Build.VERSION.SDK_INT >= 28) {
            info.signingInfo?.apkContentsSigners?.map { it.toByteArray() }.orEmpty()
        } else {
            info.signatures?.map { it.toByteArray() }.orEmpty()
        }
    }

    @Suppress("DEPRECATION")
    private fun flags(): Int =
        if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES

    private fun archiveInfo(pm: PackageManager, apk: File): PackageInfo? = if (Build.VERSION.SDK_INT >= 33) {
        pm.getPackageArchiveInfo(apk.path, PackageManager.PackageInfoFlags.of(flags().toLong()))
    } else {
        pm.getPackageArchiveInfo(apk.path, flags())
    }

    private fun installedInfo(pm: PackageManager, packageName: String): PackageInfo? = runCatching {
        if (Build.VERSION.SDK_INT >= 33) {
            pm.getPackageInfo(packageName, PackageManager.PackageInfoFlags.of(flags().toLong()))
        } else {
            pm.getPackageInfo(packageName, flags())
        }
    }.getOrNull()
}
