package app.lodestar.mobile;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.content.pm.PackageInstaller;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.widget.Toast;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Updates this app from the computer it is connected to: /phone/app.json says which build the computer has,
 * /phone/app.apk is that build. Nothing else is ever downloaded or installed, and Android itself refuses an update
 * signed by another key, so a changed file on the network cannot replace the app. The update installs through
 * PackageInstaller (no prompt on Android 12+, one confirm screen before), then the app reopens (Restart below).
 */
final class Updater {
    static final String ACTION_STATUS = "app.lodestar.mobile.UPDATE_STATUS";
    private static final String CHANNEL = "updates";
    private static final Pattern CODE = Pattern.compile("\"code\"\\s*:\\s*(\\d{1,9})");
    private static final Pattern NAME = Pattern.compile("\"name\"\\s*:\\s*\"([^\"\\\\]{1,40})\"");
    private Updater() {
    }

    private static void onUi(Runnable r) {
        new Handler(Looper.getMainLooper()).post(r);  // made here, not at class load: the JVM tests load this class
    }

    /** The build number in /phone/app.json, or -1 when the answer is not one. */
    static long parseCode(String json) {
        Matcher m = json == null ? null : CODE.matcher(json);
        return m != null && m.find() ? Long.parseLong(m.group(1)) : -1;
    }

    static String parseName(String json) {
        Matcher m = json == null ? null : NAME.matcher(json);
        return m != null && m.find() ? m.group(1) : "";
    }

    /** An update only when the computer's build is strictly newer: never a downgrade, never a guess. */
    static boolean isNewer(long remote, long installed) {
        return remote > 0 && remote > installed;
    }

    @SuppressWarnings("deprecation")
    static long installedCode(Context c) {
        try {
            PackageInfo pi = c.getPackageManager().getPackageInfo(c.getPackageName(), 0);
            return Build.VERSION.SDK_INT >= 28 ? pi.getLongVersionCode() : pi.versionCode;
        } catch (PackageManager.NameNotFoundException e) {
            return Long.MAX_VALUE;  // cannot tell: never offer one
        }
    }

    /** Asks the computer at base (already checked private by MainActivity.connect) for a newer build. quiet: say
     *  nothing when there is none or the computer cannot be reached. */
    static void check(Activity a, String base, boolean quiet) {
        new Thread(() -> {
            String json = fetch(base + "/phone/app.json");
            long remote = parseCode(json), mine = installedCode(a);
            onUi(() -> {
                if (a.isFinishing()) return;
                if (isNewer(remote, mine)) offer(a, base, parseName(json));
                else if (!quiet) toast(a, json == null ? "Could not reach Lodestar on your computer"
                        : "Lodestar for Android is up to date");
            });
        }).start();
    }

    private static void offer(Activity a, String base, String name) {
        new AlertDialog.Builder(a)
                .setTitle("Update Lodestar")
                .setMessage("Your computer has a newer Lodestar app" + (name.isEmpty() ? "" : " (" + name + ")")
                        + ". It downloads from your computer and installs; then tap the \"Lodestar updated\" notice to "
                        + "reopen it (Android 10+ does not let an app reopen itself).")
                .setPositiveButton("Update", (d, w) -> start(a, base))
                .setNegativeButton("Later", null)
                .show();
    }

    private static void start(Activity a, String base) {
        if (Build.VERSION.SDK_INT >= 26 && !a.getPackageManager().canRequestPackageInstalls()) {
            toast(a, "Allow Lodestar to install updates, then come back and tap Check for update");
            a.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + a.getPackageName())));
            return;
        }
        if (Build.VERSION.SDK_INT >= 33
                && a.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            a.requestPermissions(new String[] {Manifest.permission.POST_NOTIFICATIONS}, 9);  // the "tap to open" fallback
        }
        toast(a, "Downloading the update from your computer...");
        Context app = a.getApplicationContext();
        new Thread(() -> {
            String err = install(app, base + "/phone/app.apk");
            if (err != null) onUi(() -> toast(app, err));
        }).start();
    }

    /** Streams the APK into a PackageInstaller session and commits it; null when committed, else what went wrong. */
    private static String install(Context c, String url) {
        PackageInstaller pi = c.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams p = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        p.setAppPackageName(c.getPackageName());
        if (Build.VERSION.SDK_INT >= 31) {
            p.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED);  // self-update: no prompt
        }
        int id = -1;
        HttpURLConnection h = null;
        try {
            id = pi.createSession(p);
            h = (HttpURLConnection) new URL(url).openConnection();
            h.setConnectTimeout(5000);
            h.setReadTimeout(30000);
            h.setInstanceFollowRedirects(false);
            if (h.getResponseCode() != 200) throw new IllegalStateException("your computer answered " + h.getResponseCode());
            try (PackageInstaller.Session s = pi.openSession(id)) {
                try (InputStream in = h.getInputStream(); OutputStream out = s.openWrite("lodestar.apk", 0, -1)) {
                    byte[] buf = new byte[65536];
                    for (int n; (n = in.read(buf)) > 0; ) out.write(buf, 0, n);
                    s.fsync(out);
                }
                Intent done = new Intent(ACTION_STATUS).setPackage(c.getPackageName());
                PendingIntent cb = PendingIntent.getBroadcast(c, id, done,
                        PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0));
                s.commit(cb.getIntentSender());
            }
            return null;
        } catch (Exception e) {
            if (id >= 0) {
                try {
                    pi.abandonSession(id);
                } catch (Exception ignored) {
                    // already gone
                }
            }
            return "Update failed: " + e.getMessage();
        } finally {
            if (h != null) h.disconnect();
        }
    }

    private static String fetch(String url) {
        HttpURLConnection h = null;
        try {
            h = (HttpURLConnection) new URL(url).openConnection();
            h.setConnectTimeout(4000);
            h.setReadTimeout(6000);
            h.setInstanceFollowRedirects(false);
            if (h.getResponseCode() != 200) return null;
            byte[] buf = new byte[4096];
            int n;
            try (InputStream in = h.getInputStream()) {
                n = in.read(buf);
            }
            return n > 0 ? new String(buf, 0, n, "UTF-8") : null;
        } catch (Exception e) {
            return null;
        } finally {
            if (h != null) h.disconnect();
        }
    }

    static void toast(Context c, String s) {
        Toast.makeText(c, s, Toast.LENGTH_LONG).show();
    }

    /** The installer's answer: a confirm screen to show (Android 8-11), or why it failed. */
    public static final class Status extends BroadcastReceiver {
        @Override
        @SuppressWarnings("deprecation")
        public void onReceive(Context c, Intent i) {
            int st = i.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
            if (st == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                Intent confirm = i.getParcelableExtra(Intent.EXTRA_INTENT);
                if (confirm != null) c.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } else if (st == PackageInstaller.STATUS_FAILURE_CONFLICT || st == PackageInstaller.STATUS_FAILURE_INCOMPATIBLE) {
                toast(c, "Update refused: it is not signed like this app (built on another computer?). Install it from "
                        + "the pairing page instead.");
            } else if (st != PackageInstaller.STATUS_SUCCESS) {
                String m = i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
                toast(c, "Update did not install" + (m == null ? "" : ": " + m));
            }
        }
    }

    /** After the update replaced this app: reopen it, and leave a "tap to open" notice in case Android keeps a
     *  background app from opening itself (Android 10+). */
    public static final class Restart extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent i) {
            if (!Intent.ACTION_MY_PACKAGE_REPLACED.equals(i.getAction())) return;
            Intent open = new Intent(c, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            try {
                c.startActivity(open);
            } catch (Exception ignored) {
                // blocked from the background: the notice below opens it
            }
            NotificationManager nm = c.getSystemService(NotificationManager.class);
            if (nm == null || (Build.VERSION.SDK_INT >= 33
                    && c.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)) {
                return;
            }
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Updates", NotificationManager.IMPORTANCE_DEFAULT));
            PendingIntent tap = PendingIntent.getActivity(c, 0, open, PendingIntent.FLAG_IMMUTABLE);
            nm.notify(1, new Notification.Builder(c, CHANNEL)
                    .setSmallIcon(android.R.drawable.stat_sys_download_done)
                    .setContentTitle("Lodestar updated")
                    .setContentText("Tap to open")
                    .setContentIntent(tap)
                    .setAutoCancel(true)
                    .build());
        }
    }
}
