package com.khrecast.recast;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.drawable.BitmapDrawable;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;

/**
 * The menu and heading names drawn in the Kingdom Hearts menu font (the same look as the desktop launcher's tab names;
 * made by tools/make_tab_labels.py, which also copies them into res/drawable-nodpi/menu_*.png). They are small pictures,
 * enlarged by a whole number so the hard pixel edges stay crisp.
 */
final class Labels {
    private Labels() {
    }

    /** A picture label about `targetDp` tall (rounded to a whole-number scale, and not wider than `maxWidthPx`). */
    static ImageView picture(Context context, int resId, int targetDp, int maxWidthPx, boolean centeredInFrame,
                             String description) {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inScaled = false;                              // the pixels as drawn
        Bitmap bm = BitmapFactory.decodeResource(context.getResources(), resId, options);
        float density = context.getResources().getDisplayMetrics().density;
        int scale = Math.max(1, Math.round(targetDp * density / bm.getHeight()));
        while (scale > 1 && bm.getWidth() * scale > maxWidthPx) {
            scale--;
        }
        BitmapDrawable drawable = new BitmapDrawable(context.getResources(), bm);
        drawable.setFilterBitmap(false);                       // crisp pixels
        ImageView view = new ImageView(context);
        view.setImageDrawable(drawable);
        view.setScaleType(ImageView.ScaleType.FIT_XY);
        view.setContentDescription(description);
        int w = bm.getWidth() * scale, h = bm.getHeight() * scale;
        if (centeredInFrame) {
            view.setLayoutParams(new FrameLayout.LayoutParams(w, h, Gravity.CENTER));
        } else {
            view.setLayoutParams(new LinearLayout.LayoutParams(w, h));
        }
        return view;
    }

    /** The width a label may use on this screen: the screen minus some room at the sides. */
    static int maxWidth(Context context) {
        return context.getResources().getDisplayMetrics().widthPixels
                - 2 * Math.round(48 * context.getResources().getDisplayMetrics().density);
    }

    /** A button face made of a picture label: a normal Button with the picture centered on top (touches go to the button). */
    static FrameLayout pictureButton(Context context, int resId, int targetDp, int heightDp, String description,
                                     android.view.View.OnClickListener listener) {
        FrameLayout box = new FrameLayout(context);
        android.widget.Button button = new android.widget.Button(context);
        button.setOnClickListener(listener);
        button.setContentDescription(description);
        box.addView(button, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT));
        ImageView pic = picture(context, resId, targetDp, maxWidth(context), true, description);
        pic.setClickable(false);
        pic.setImportantForAccessibility(android.view.View.IMPORTANT_FOR_ACCESSIBILITY_NO);   // the Button already says it
        float density = context.getResources().getDisplayMetrics().density;
        pic.setElevation(12 * density);                        // a Button is raised: the picture must sit above it
        box.addView(pic);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                Math.round(heightDp * density));
        lp.topMargin = Math.round(8 * density);
        box.setLayoutParams(lp);
        return box;
    }
}
