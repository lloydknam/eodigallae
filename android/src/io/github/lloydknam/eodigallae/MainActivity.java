package io.github.lloydknam.eodigallae;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.webkit.GeolocationPermissions;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** 어디갈래 사이트를 그대로 보여주는 앱. 사이트가 바뀌면 앱도 자동으로 최신이 된다. */
public class MainActivity extends Activity {
    static final String HOME = "https://lloydknam.github.io/eodigallae/";
    static final String ORIGIN = "https://lloydknam.github.io";
    private static final int REQ_LOCATION = 77;
    private WebView web;
    private String pendingOrigin;
    private GeolocationPermissions.Callback pendingCallback;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        // 밝은 화면: 흰 상단·하단 바에 어두운 아이콘
        getWindow().setStatusBarColor(Color.WHITE);
        getWindow().setNavigationBarColor(Color.WHITE);
        int flags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
        if (Build.VERSION.SDK_INT >= 26) flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
        getWindow().getDecorView().setSystemUiVisibility(flags);
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#F2F4F6"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);      // 내 코스·도장 저장
        s.setDatabaseEnabled(true);
        s.setUserAgentString(s.getUserAgentString() + " EodigallaeApp/1.2");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest r) {
                Uri u = r.getUrl();
                String path = u.getPath() == null ? "" : u.getPath();
                if ("lloydknam.github.io".equals(u.getHost()) && path.startsWith("/eodigallae")) return false;
                // 유튜브·카카오맵·인스타그램 등은 해당 앱이나 브라우저로
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) { }
                return true;
            }
        });
        // 사이트의 '내 위치' 버튼: 우리 사이트에서만, 대략적 위치 권한을 받은 뒤에 허용한다.
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback cb) {
                if (!ORIGIN.equals(origin)) { cb.invoke(origin, false, false); return; }
                if (Build.VERSION.SDK_INT < 23
                        || checkSelfPermission(Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                    cb.invoke(origin, true, false);
                } else {
                    pendingOrigin = origin;
                    pendingCallback = cb;
                    requestPermissions(new String[] { Manifest.permission.ACCESS_COARSE_LOCATION }, REQ_LOCATION);
                }
            }
        });
        setContentView(web);
        if (saved != null) web.restoreState(saved);
        else web.loadUrl(urlFor(getIntent()));
    }

    private String urlFor(Intent i) {
        if (i != null && Intent.ACTION_SEND.equals(i.getAction())) {
            String t = i.getStringExtra(Intent.EXTRA_TEXT);
            if (t != null) return HOME + "?text=" + Uri.encode(t);
        }
        return HOME;
    }

    @Override
    protected void onNewIntent(Intent i) {
        super.onNewIntent(i);
        if (Intent.ACTION_SEND.equals(i.getAction())) web.loadUrl(urlFor(i));
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        super.onRequestPermissionsResult(code, perms, results);
        if (code == REQ_LOCATION && pendingCallback != null) {
            boolean ok = results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED;
            pendingCallback.invoke(pendingOrigin, ok, false);
            pendingCallback = null;
            pendingOrigin = null;
        }
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }
}
