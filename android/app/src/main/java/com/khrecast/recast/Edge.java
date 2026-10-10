package com.khrecast.recast;

import android.view.View;

/** Keeps a scrolling screen's content clear of the status bar and the navigation bar (the app draws edge to edge). */
final class Edge {
    private Edge() {
    }

    /** Pads `content` by the given amounts (pixels) plus whatever the system bars take, as soon as they are known. */
    @SuppressWarnings("deprecation")
    static void pad(View scroll, View content, int left, int top, int right, int bottom) {
        content.setPadding(left, top, right, bottom);
        scroll.setOnApplyWindowInsetsListener((v, insets) -> {
            content.setPadding(left + insets.getSystemWindowInsetLeft(), top + insets.getSystemWindowInsetTop(),
                    right + insets.getSystemWindowInsetRight(), bottom + insets.getSystemWindowInsetBottom());
            return insets;
        });
        scroll.requestApplyInsets();
    }
}
