package io.github.lloydknam.eodigallae;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

/** 어디갈래 사이트를 그대로 보여주는 앱. 사이트가 바뀌면 앱도 자동으로 최신이 된다. */
public class MainActivity extends Activity {
    static final String HOME = "https://lloydknam.github.io/eodigallae/";
    private WebView web;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);
        getWindow().setStatusBarColor(Color.parseColor("#12907A"));
        getWindow().setNavigationBarColor(Color.parseColor("#F1F8F5"));
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#F1F8F5"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);      // 내 코스·도장 저장
        s.setDatabaseEnabled(true);
        s.setUserAgentString(s.getUserAgentString() + " EodigallaeApp/1.0");
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
        web.setWebChromeClient(new WebChromeClient());
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
