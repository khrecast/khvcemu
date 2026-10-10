package com.khrecast.recast;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * The first screen every time the app is opened: what this project is and is not (an unofficial, free, non-profit fan
 * project; the rights belong to their holders), and that the game's files are not part of the app. "I understand" goes on
 * to the home screen; Back leaves the app. The wording is the desktop launcher's and the website's (tests keep them equal).
 */
public class DisclaimerActivity extends Activity {
    /** The same text as `DISCLAIMER` in khvcemu/launcher.py and the website's notice. Keep it on one line: a test finds it. */
    static final String DISCLAIMER = "Kingdom Hearts and all related characters, names and assets belong to their respective rights holders. This is an unofficial fan project and is not affiliated with, endorsed by or connected to Disney, Square Enix, Superscape, Verizon, Qualcomm or any other rights holder. It exists only to preserve, and let people experience, a piece of gaming history. It is free and non-profit: nobody earns money from it, and it should never be sold.";

    static final String NO_FILES = "This app contains no game files. You need your own copy of the game: you pick its folder the first time you play.";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);

        ImageView logo = new ImageView(this);
        logo.setImageResource(R.drawable.recast_logo);
        logo.setAdjustViewBounds(true);
        logo.setScaleType(ImageView.ScaleType.FIT_CENTER);
        logo.setContentDescription("Kingdom Hearts Re:Cast");
        boolean wide = getResources().getDisplayMetrics().widthPixels > getResources().getDisplayMetrics().heightPixels;
        logo.setMaxHeight(Math.min(dp(200), Math.round(getResources().getDisplayMetrics().heightPixels * (wide ? 0.15f : 0.25f))));
        col.addView(logo, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT));

        int size = wide ? 14 : 16;                                 // landscape: smaller, so the button is on the screen
        TextView notice = text(DISCLAIMER, size, 0xFFCFD8DC);
        notice.setPadding(0, wide ? dp(8) : dp(24), 0, dp(8));
        col.addView(notice);
        TextView files = text(NO_FILES, size, 0xFFCFD8DC);
        files.setPadding(0, 0, 0, wide ? dp(12) : dp(24));
        col.addView(files);

        Button ok = new Button(this);
        ok.setText("I understand");
        ok.setAllCaps(false);
        ok.setTextSize(TypedValue.COMPLEX_UNIT_SP, 18);
        ok.setOnClickListener(v -> {
            startActivity(new Intent(this, HomeActivity.class));
            finish();
        });
        col.addView(ok, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(wide ? 52 : 60)));

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        scroll.setFillViewport(true);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, dp(24), dp(16), dp(24), dp(32));
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        return t;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
