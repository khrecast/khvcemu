package com.khrecast.recast;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.List;

/**
 * The first-run screen: pick the folder that holds the game files (Android's folder picker), copy it into the app, check
 * it, then play. Also where the copied files can be removed. The app opens here, and goes straight on to the game when
 * the files are already installed.
 */
public class SetupActivity extends Activity {
    private static final int PICK = 1;

    private TextView message;
    private TextView problems;
    private ProgressBar busy;
    private Button choose;
    private Button play;
    private Button remove;
    private boolean working;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        int pad = dp(24);
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);

        col.addView(Labels.picture(this, R.drawable.menu_game_files, 32, Labels.maxWidth(this), false, "Game files"));
        message = text("", 16, 0xFFCFD8DC);
        message.setPadding(0, dp(16), 0, dp(24));
        col.addView(message);

        choose = button("Choose the game folder", v -> startActivityForResult(
                new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE), PICK));
        col.addView(choose);
        play = button("Done", v -> finish());
        col.addView(play);
        remove = button("Remove the game files", v -> {
            GameInstaller.remove(this);
            problems.setText("");
            refresh();
        });
        col.addView(remove);

        busy = new ProgressBar(this);
        busy.setIndeterminate(true);
        busy.setVisibility(View.GONE);
        col.addView(busy);
        problems = text("", 15, 0xFFFFAB91);
        problems.setPadding(0, dp(16), 0, 0);
        col.addView(problems);

        ScrollView scroll = new ScrollView(this);
        scroll.setBackgroundColor(Color.BLACK);
        Labels.theme(choose, true);
        Labels.theme(play, false);
        Labels.theme(remove, false);
        scroll.addView(col);
        setContentView(scroll);
        Edge.pad(scroll, col, pad, dp(24), pad, dp(32));
    }

    @Override
    protected void onResume() {
        super.onResume();
        refresh();
    }

    private void refresh() {
        boolean installed = GameInstaller.isInstalled(this);
        message.setText(installed
                ? "The game files are installed."
                : "Re:Cast plays the Kingdom Hearts game from 2005 and needs its game files, which are not part of this "
                + "app. Copy the folder that holds the game's mif and mod folders to this phone, then choose it here. "
                + "(Android does not let an app pick the Download folder itself: put the game folder inside a folder, "
                + "for example Download/Games/KH, and pick that.)");
        choose.setText(installed ? "Choose the game folder again" : "Choose the game folder");
        choose.setEnabled(!working);
        play.setVisibility(installed && !working ? View.VISIBLE : View.GONE);
        remove.setVisibility(installed && !working ? View.VISIBLE : View.GONE);
        busy.setVisibility(working ? View.VISIBLE : View.GONE);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode != PICK || resultCode != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        Uri tree = data.getData();
        working = true;
        problems.setText("");
        message.setText("Copying the game files...");
        refresh();
        new Thread(() -> {
            List<String> found = GameInstaller.install(getApplicationContext(), tree,
                    text -> runOnUiThread(() -> message.setText(text)));
            runOnUiThread(() -> {
                working = false;
                if (found.isEmpty()) {
                    finish();                                  // back to where it was opened from: the game is ready
                } else {
                    problems.setText(join(found));
                    refresh();
                }
            });
        }, "recast-install").start();
    }

    private static String join(List<String> lines) {
        StringBuilder sb = new StringBuilder("These game files are not right:\n");
        for (String s : lines) {
            sb.append("\n- ").append(s);
        }
        return sb.toString();
    }

    private TextView text(String s, int sp, int color) {
        TextView t = new TextView(this);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        return t;
    }

    private Button button(String label, View.OnClickListener l) {
        Button b = new Button(this);
        b.setText(label);
        b.setAllCaps(false);
        b.setOnClickListener(l);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(60));
        lp.topMargin = dp(10);
        b.setLayoutParams(lp);
        return b;
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }
}
