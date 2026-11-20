package app.lodestar.mobile;

import android.app.Activity;
import android.app.DownloadManager;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.Menu;
import android.view.MenuItem;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.URLUtil;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.net.URL;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

/**
 * Lodestar for Android: opens your own Lodestar (Setup > Phone access on your computer) over your home Wi-Fi or a phone
 * tether. Pairing, sign-in and every safety rule stay on the computer; this app only shows it. It loads private
 * addresses only (10/8, 172.16/12, 192.168/16, .local); every other link opens in your browser.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "lodestar", KEY_BASE = "base";
    private static final int PORT_FIRST = 8780, PORT_LAST = 8782, FILE_REQUEST = 7;

    private SharedPreferences prefs;
    private WebView web;
    private String base;  // e.g. http://192.168.1.153:8780
    private ValueCallback<Uri[]> fileCallback;
    private final Handler ui = new Handler(Looper.getMainLooper());
    private ExecutorService scan;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        if ((getApplicationInfo().flags & android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);  // debug builds only: lets the test drive the page over adb
        }
        CookieManager.getInstance().setAcceptCookie(true);
        base = prefs.getString(KEY_BASE, null);
        if (base == null) showSetup(null);
        else showWeb(base + "/");
    }

    // ---- setup: type the address Setup > Phone access shows, or find it on this network
    private void showSetup(String message) {
        web = null;
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = dp(20);
        box.setPadding(pad, pad, pad, pad);
        TextView title = text("Connect to Lodestar", 24);
        box.addView(title);
        box.addView(text("On your computer: Lodestar > Setup > Phone access > Turn on, then New pairing code. "
                + "This phone must be on the same Wi-Fi, or tethered to the computer (USB or hotspot).", 15));
        if (message != null) {
            TextView m = text(message, 15);
            m.setTextColor(Color.rgb(185, 28, 28));
            box.addView(m);
        }
        EditText addr = new EditText(this);
        addr.setHint("http://192.168.1.153:8780");
        addr.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        addr.setSingleLine(true);
        if (base != null) addr.setText(base);
        box.addView(addr);
        Button go = new Button(this);
        go.setText("Connect");
        go.setOnClickListener(v -> connect(addr.getText().toString()));
        box.addView(go);
        Button find = new Button(this);
        find.setText("Find Lodestar on this network");
        TextView status = text("", 14);
        LinearLayout found = new LinearLayout(this);
        found.setOrientation(LinearLayout.VERTICAL);
        find.setOnClickListener(v -> findLodestar(status, found, find));
        box.addView(find);
        box.addView(status);
        box.addView(found);
        ScrollView sv = new ScrollView(this);
        sv.addView(box);
        setContentView(sv);
        setTitle("Lodestar");
    }

    private void connect(String typed) {
        String b = normalise(typed);
        if (b == null) {
            showSetup("Type the address Lodestar shows under Setup > Phone access, e.g. http://192.168.1.153:8780");
            return;
        }
        if (!isPrivate(Uri.parse(b).getHost())) {
            showSetup("That is not an address on your own network. Lodestar only serves your home Wi-Fi or a tether.");
            return;
        }
        base = b;
        prefs.edit().putString(KEY_BASE, b).apply();
        showWeb(b + "/");
    }

    /** "192.168.1.5:8780/phone" -> "http://192.168.1.5:8780"; null when it is not an http(s) address. */
    static String normalise(String typed) {
        String t = typed == null ? "" : typed.trim();
        if (t.isEmpty()) return null;
        if (!t.matches("(?i)^https?://.*")) t = "http://" + t;
        Uri u = Uri.parse(t);
        if (u.getHost() == null || u.getHost().isEmpty()) return null;
        int port = u.getPort() > 0 ? u.getPort() : PORT_FIRST;
        return u.getScheme().toLowerCase(Locale.ROOT) + "://" + u.getHost() + ":" + port;
    }

    /** Private IPv4 (10/8, 172.16/12, 192.168/16) or a .local name: the only hosts this app loads. */
    static boolean isPrivate(String host) {
        if (host == null) return false;
        String h = host.toLowerCase(Locale.ROOT);
        if (h.endsWith(".local")) return true;
        String[] p = h.split("\\.");
        if (p.length != 4) return false;
        int[] n = new int[4];
        try {
            for (int i = 0; i < 4; i++) {
                n[i] = Integer.parseInt(p[i]);
                if (n[i] < 0 || n[i] > 255) return false;
            }
        } catch (NumberFormatException e) {
            return false;
        }
        return n[0] == 10 || (n[0] == 172 && n[1] >= 16 && n[1] <= 31) || (n[0] == 192 && n[1] == 168);
    }

    // ---- find: try every address on this phone's private networks (Wi-Fi, hotspot, USB tether) on Lodestar's ports
    private void findLodestar(TextView status, LinearLayout found, Button btn) {
        List<String> nets = localPrefixes();
        if (nets.isEmpty()) {
            status.setText("This phone is on no private network: join your home Wi-Fi or tether to the computer.");
            return;
        }
        btn.setEnabled(false);
        found.removeAllViews();
        status.setText("Looking on " + String.join(", ", nets) + " ...");
        if (scan != null) scan.shutdownNow();
        scan = Executors.newFixedThreadPool(48);
        List<String> hits = Collections.synchronizedList(new ArrayList<>());
        for (String prefix : nets) {
            for (int i = 1; i < 255; i++) {
                for (int port = PORT_FIRST; port <= PORT_LAST; port++) {
                    final String url = "http://" + prefix + i + ":" + port;
                    scan.execute(() -> {
                        if (isLodestar(url) && !hits.contains(url)) {
                            hits.add(url);
                            ui.post(() -> {
                                Button b = new Button(this);
                                b.setText("Use " + url);
                                b.setAllCaps(false);
                                b.setOnClickListener(v -> connect(url));
                                found.addView(b);
                            });
                        }
                    });
                }
            }
        }
        scan.shutdown();
        new Thread(() -> {
            try {
                scan.awaitTermination(60, TimeUnit.SECONDS);
            } catch (InterruptedException ignored) {
                Thread.currentThread().interrupt();
            }
            ui.post(() -> {
                btn.setEnabled(true);
                status.setText(hits.isEmpty()
                        ? "Not found. Is Phone access turned on in Lodestar (Setup), and is this phone on the same network?"
                        : "Found Lodestar: tap the address to connect.");
            });
        }).start();
    }

    /** "192.168.1." for each private IPv4 network this phone is on. */
    static List<String> localPrefixes() {
        List<String> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (!(a instanceof Inet4Address)) continue;
                    String ip = a.getHostAddress();
                    if (!isPrivate(ip)) continue;
                    String prefix = ip.substring(0, ip.lastIndexOf('.') + 1);
                    if (!out.contains(prefix)) out.add(prefix);
                }
            }
        } catch (Exception ignored) {
            // no interfaces readable: the caller says so
        }
        return out;
    }

    /** Lodestar's pairing page answers /phone with its title. */
    private static boolean isLodestar(String url) {
        HttpURLConnection c = null;
        try {
            c = (HttpURLConnection) new URL(url + "/phone").openConnection();
            c.setConnectTimeout(350);
            c.setReadTimeout(800);
            c.setInstanceFollowRedirects(false);
            if (c.getResponseCode() != 200) return false;
            byte[] buf = new byte[2048];
            int n;
            try (InputStream in = c.getInputStream()) {
                n = in.read(buf);
            }
            return n > 0 && new String(buf, 0, n, "UTF-8").contains("Lodestar on your phone");
        } catch (Exception e) {
            return false;
        } finally {
            if (c != null) c.disconnect();
        }
    }

    // ---- the app: Lodestar itself, in a WebView kept to your computer's address
    private void showWeb(String url) {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);  // Lodestar's page is JavaScript; the WebView never loads another site
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setSupportMultipleWindows(false);  // target=_blank links come through shouldOverrideUrlLoading below
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (sameOrigin(u)) return false;
                openOutside(u);
                return true;
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest req, WebResourceError err) {
                if (req.isForMainFrame()) showOffline(String.valueOf(err.getDescription()));
            }

            @Override
            public void onPageFinished(WebView view, String u) {
                CookieManager.getInstance().flush();  // the pairing cookie survives the app closing
                setTitle("Lodestar");
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams params) {
                if (fileCallback != null) fileCallback.onReceiveValue(null);
                fileCallback = cb;
                try {
                    startActivityForResult(params.createIntent(), FILE_REQUEST);
                } catch (ActivityNotFoundException e) {
                    fileCallback = null;
                    toast("No app on this phone can pick a file");
                    return false;
                }
                return true;
            }
        });
        web.setDownloadListener((dl, ua, disposition, mime, length) -> download(dl, ua, disposition, mime));
        setContentView(web);
        web.loadUrl(url);
    }

    private boolean sameOrigin(Uri u) {
        Uri b = Uri.parse(base);
        return u.getScheme() != null && u.getScheme().equalsIgnoreCase(b.getScheme())
                && u.getHost() != null && u.getHost().equalsIgnoreCase(b.getHost()) && u.getPort() == b.getPort();
    }

    private void openOutside(Uri u) {
        String scheme = u.getScheme() == null ? "" : u.getScheme().toLowerCase(Locale.ROOT);
        if (!scheme.equals("http") && !scheme.equals("https") && !scheme.equals("mailto")) return;  // never intent: or javascript:
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));
        } catch (ActivityNotFoundException e) {
            toast("No app on this phone opens that link");
        }
    }

    private void download(String url, String ua, String disposition, String mime) {
        Uri u = Uri.parse(url);
        if (!sameOrigin(u)) {  // a blob: export or another site: Lodestar on the computer saves those
            toast("Save this file from Lodestar on your computer");
            return;
        }
        DownloadManager.Request r = new DownloadManager.Request(u);
        r.addRequestHeader("Cookie", CookieManager.getInstance().getCookie(url));
        r.addRequestHeader("User-Agent", ua);
        r.setMimeType(mime);
        String name = URLUtil.guessFileName(url, disposition, mime);
        r.setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, name);
        r.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
        DownloadManager dm = (DownloadManager) getSystemService(DOWNLOAD_SERVICE);
        if (dm != null) {
            dm.enqueue(r);
            toast("Downloading " + name);
        }
    }

    private void showOffline(String why) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER_HORIZONTAL);
        int pad = dp(24);
        box.setPadding(pad, pad, pad, pad);
        box.addView(text("Can't reach Lodestar", 22));
        box.addView(text("Is your computer on, Lodestar running with Phone access turned on, and this phone on the same "
                + "Wi-Fi or tethered? (" + why + ")", 15));
        Button retry = new Button(this);
        retry.setText("Try again");
        retry.setOnClickListener(v -> showWeb(base + "/"));
        box.addView(retry);
        Button change = new Button(this);
        change.setText("Change address");
        change.setOnClickListener(v -> showSetup(null));
        box.addView(change);
        setContentView(box);
        web = null;
    }

    // ---- menu, back, files
    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "Reload");
        menu.add(0, 2, 1, "Change address");
        menu.add(0, 3, 2, "Forget this computer");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        switch (item.getItemId()) {
            case 1:
                if (web != null) web.reload();
                else if (base != null) showWeb(base + "/");
                return true;
            case 2:
                showSetup(null);
                return true;
            case 3:
                prefs.edit().remove(KEY_BASE).apply();
                CookieManager.getInstance().removeAllCookies(null);
                base = null;
                showSetup("This phone forgot the computer. Pair again with a new code.");
                return true;
            default:
                return super.onOptionsItemSelected(item);
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    @SuppressWarnings("deprecation")
    protected void onActivityResult(int request, int result, Intent data) {
        if (request == FILE_REQUEST && fileCallback != null) {
            fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            fileCallback = null;
            return;
        }
        super.onActivityResult(request, result, data);
    }

    @Override
    protected void onPause() {
        super.onPause();
        CookieManager.getInstance().flush();
    }

    @Override
    protected void onDestroy() {
        if (scan != null) scan.shutdownNow();
        super.onDestroy();
    }

    // ---- small helpers
    private TextView text(String s, int sp) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(sp);
        t.setPadding(0, dp(6), 0, dp(6));
        t.setLayoutParams(new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

}
