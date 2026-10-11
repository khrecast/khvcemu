package com.khrecast.recast;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.HashMap;
import java.util.Map;

/**
 * Text in the Kingdom Hearts menu font for words only known at run time (the game's softkey words). The letters come from one
 * picture, menu_font_atlas.png, made by tools/make_tab_labels.py from the font (which is not in the repository), with a text file
 * (res/raw/menu_font_atlas.txt) giving each character's cell. Drawn at a whole-number scale with hard edges when that fits, smoothed otherwise.
 */
final class MenuFont {
    private final Bitmap atlas;
    private final int height;
    private final Map<Character, int[]> cells = new HashMap<>();          // character -> {x, width} in the picture
    private final Paint crisp = new Paint();
    private final Paint smooth = new Paint(Paint.FILTER_BITMAP_FLAG);
    private final Rect src = new Rect();
    private final RectF dst = new RectF();

    MenuFont(Context context) {
        BitmapFactory.Options options = new BitmapFactory.Options();
        options.inScaled = false;
        atlas = BitmapFactory.decodeResource(context.getResources(), R.drawable.menu_font_atlas, options);
        crisp.setFilterBitmap(false);
        int h = 0;
        try (BufferedReader in = new BufferedReader(new InputStreamReader(
                context.getResources().openRawResource(R.raw.menu_font_atlas), "UTF-8"))) {
            h = Integer.parseInt(in.readLine().trim());
            String line;
            while ((line = in.readLine()) != null) {
                String[] p = line.trim().split(" ");
                if (p.length == 3) {
                    cells.put((char) Integer.parseInt(p[0]), new int[]{Integer.parseInt(p[1]), Integer.parseInt(p[2])});
                }
            }
        } catch (IOException | RuntimeException e) {
            cells.clear();                                                  // no usable alphabet: callers fall back to the system font
        }
        height = h;
    }

    /** The width of the text at scale 1, or 0 when it has nothing this font can draw. */
    private float width(String text) {
        float total = 0;
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch == ' ') {
                total += height * 0.35f;
            } else {
                int[] cell = cells.get(ch);
                if (cell == null) {
                    return 0f;                                              // a character this font lacks: draw the whole word another way
                }
                total += cell[1];
            }
        }
        return total;
    }

    /** Draws the text centered on cx, cy as large as fits maxW x maxH. False when the font cannot draw it (nothing is drawn). */
    boolean draw(Canvas c, String text, float cx, float cy, float maxW, float maxH) {
        if (atlas == null || height == 0 || cells.isEmpty()) {
            return false;
        }
        float w = width(text);
        if (w == 0f) {
            return false;
        }
        float f = Math.min(maxW / w, maxH / height);
        float whole = (float) Math.floor(f);
        boolean hard = whole >= 1 && f - whole < 0.2f;                     // (near a whole number: keep the hard pixel edges)
        float scale = hard ? whole : f;
        Paint paint = hard ? crisp : smooth;
        float x = cx - w * scale / 2f, top = cy - height * scale / 2f;
        if (hard) {
            x = Math.round(x);                                             // whole pixels, so the hard edges stay even
            top = Math.round(top);
        }
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            if (ch == ' ') {
                x += height * 0.35f * scale;
                continue;
            }
            int[] cell = cells.get(ch);
            if (cell == null) {
                continue;
            }
            src.set(cell[0], 0, cell[0] + cell[1], height);
            dst.set(x, top, x + cell[1] * scale, top + height * scale);
            c.drawBitmap(atlas, src, dst, paint);
            x += cell[1] * scale;
        }
        return true;
    }
}
