package com.khrecast.recast;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewConfiguration;
import android.view.WindowInsets;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The game's 176x220 picture (enlarged with the nearest pixel, like the desktop's "crisp pixels") and, under it,
 * the phone's keys as touch controls: a pad for the four directions (diagonals work), Action, Magic, Status, the
 * two softkeys and Back. Several fingers at once are fine. A tap on the picture itself is passed on to the game
 * (in game pixels), which turns it into the keys of whatever button it landed on (khvcemu/tapmap.py). Everything is
 * laid out inside the area the system bars leave free, so nothing is hidden behind the navigation bar.
 */
public class GameView extends View {
    public static final int W = 176, H = 220;

    /** Called for every key that goes down or up (phone key names such as UP, SELECT, STAR, 0, SOFT1). */
    public interface KeySink {
        void key(String name, boolean down);
    }

    /** Called for a tap on the picture, in game pixels (0 to 176, 0 to 220). */
    public interface TapSink {
        void tap(float x, float y);
    }

    private static class Button {
        final String key, label;
        final RectF r = new RectF();
        final boolean round;

        Button(String key, String label, boolean round) {
            this.key = key;
            this.label = label;
            this.round = round;
        }
    }

    private final Bitmap frame = Bitmap.createBitmap(W, H, Bitmap.Config.RGB_565);
    private final Paint pixels = new Paint();                 // no filtering: crisp pixels
    private final Paint fill = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint text = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Rect src = new Rect(0, 0, W, H);
    private final RectF dst = new RectF();
    private final List<Button> buttons = new ArrayList<>();
    private final Set<String> held = new HashSet<>();
    private float padX, padY, padR, statusY;
    private int insetTop, insetBottom, insetLeft, insetRight;  // the system bars, in pixels
    private int pictureScale = Settings.FIT;                // see Settings: FIT, LARGEST or a whole number of pixels
    private String status = "";
    private KeySink sink;
    private TapSink tapSink;
    private boolean hasFrame;
    private final float slop;
    // a possible tap on the picture: where and when the finger went down, and which finger
    private int tapPointer = -1;
    private float tapX, tapY;
    private long tapTime;

    public GameView(Context context) {
        super(context);
        slop = ViewConfiguration.get(context).getScaledTouchSlop();
        pixels.setFilterBitmap(false);
        pixels.setAntiAlias(false);
        text.setColor(Color.WHITE);
        text.setTextAlign(Paint.Align.CENTER);
        text.setTypeface(Typeface.DEFAULT_BOLD);
        buttons.add(new Button("SOFT1", "Soft 1", false));
        buttons.add(new Button("CLR", "Back", false));
        buttons.add(new Button("SOFT2", "Soft 2", false));
        buttons.add(new Button("SELECT", "Action", true));
        buttons.add(new Button("STAR", "Magic", true));
        buttons.add(new Button("0", "Status", true));
        setBackgroundColor(Color.BLACK);
    }

    public void setKeySink(KeySink sink) {
        this.sink = sink;
    }

    /** Picture size (Settings.FIT, Settings.LARGEST or 1, 2, 3...): takes effect at once. */
    public void setPictureScale(int scale) {
        if (scale != pictureScale) {
            pictureScale = scale;
            layoutControls(getWidth(), getHeight());
            postInvalidate();
        }
    }

    public void setTapSink(TapSink sink) {
        this.tapSink = sink;
    }

    /** New picture: 176*220 little-endian RGB565 pixels. Called from a worker thread. */
    public void setFrame(byte[] rgb565) {
        if (rgb565 == null || rgb565.length != W * H * 2) {
            return;
        }
        synchronized (frame) {
            frame.copyPixelsFromBuffer(ByteBuffer.wrap(rgb565));
            hasFrame = true;
        }
        postInvalidate();
    }

    /** A copy of the game's current picture (176 x 220), or null before the first frame. */
    public Bitmap snapshot() {
        synchronized (frame) {
            return hasFrame ? frame.copy(Bitmap.Config.ARGB_8888, false) : null;
        }
    }

    public void setStatus(String s) {
        status = s;
        postInvalidate();
    }

    @SuppressWarnings("deprecation")
    @Override
    public WindowInsets onApplyWindowInsets(WindowInsets insets) {
        // the navigation bar, the gesture area and the status bar: nothing of ours may sit behind them
        insetTop = insets.getSystemWindowInsetTop();
        insetBottom = insets.getSystemWindowInsetBottom();
        insetLeft = insets.getSystemWindowInsetLeft();
        insetRight = insets.getSystemWindowInsetRight();
        layoutControls(getWidth(), getHeight());
        invalidate();
        return super.onApplyWindowInsets(insets);
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        layoutControls(w, h);
    }

    /** Landscape: the picture in the middle at the full height, the pad and the softkeys at its left, the buttons and
     *  the other softkey at its right, so both thumbs rest at the sides of the phone. */
    private void layoutLandscape(int w, int h) {
        float left = insetLeft, right = w - insetRight, width = right - left;
        float top = insetTop, bottom = h - insetBottom, free = bottom - top;
        float gh = free * 0.93f;                                       // the status line sits under the picture
        if (pictureScale != Settings.FIT) {
            int most = Math.max(1, (int) Math.floor(gh / H));
            gh = H * (pictureScale == Settings.LARGEST ? most : Math.min(pictureScale, most));
        }
        float gw = gh * W / H;
        float gx = left + (width - gw) / 2f;
        dst.set(gx, top + free * 0.01f, gx + gw, top + free * 0.01f + gh);
        statusY = bottom - free * 0.008f;

        float leftW = Math.max(0f, gx - left), rightW = Math.max(0f, right - (gx + gw));
        float lc = left + leftW / 2f, rc = gx + gw + rightW / 2f;     // the middle of each side
        float softH = free * 0.12f, softTop = top + free * 0.04f, gap = leftW * 0.03f;
        buttons.get(0).r.set(left + gap, softTop, lc - gap, softTop + softH);                      // SOFT1
        buttons.get(1).r.set(lc + gap, softTop, left + leftW - gap, softTop + softH);              // CLR
        buttons.get(2).r.set(rc - rightW * 0.45f, softTop, rc + rightW * 0.45f, softTop + softH);  // SOFT2

        float areaTop = softTop + softH + free * 0.03f, areaBottom = bottom - free * 0.05f;
        float area = areaBottom - areaTop;
        padR = Math.min(leftW * 0.44f, area * 0.46f);
        padX = lc;
        padY = areaBottom - padR;
        float big = Math.min(rightW * 0.2f, area * 0.27f);
        float small = big * 0.72f;
        float cy = areaTop + area / 2f;
        setCircle(buttons.get(3), rc + rightW * 0.1f, cy + area * 0.2f, big);                      // Action
        setCircle(buttons.get(4), rc - rightW * 0.2f, cy - area * 0.08f, small);                   // Magic
        setCircle(buttons.get(5), rc + rightW * 0.2f, cy - area * 0.28f, small);                   // Status
    }

    /** The picture at the top of the free area, the softkeys under it, the pad and buttons in what is left. */
    private void layoutControls(int w, int h) {
        if (w == 0 || h == 0) {
            return;
        }
        if (w > h) {
            layoutLandscape(w, h);
            return;
        }
        float left = insetLeft, right = w - insetRight, width = right - left;
        float top = insetTop, bottom = h - insetBottom, free = bottom - top;
        float gh = Math.min(width * (float) H / W, free * 0.60f);      // as large as the width allows, at most 60%
        if (pictureScale != Settings.FIT) {                            // a whole number of screen pixels per game pixel
            int most = Math.max(1, (int) Math.floor(gh / H));          // the largest that fits
            gh = H * (pictureScale == Settings.LARGEST ? most : Math.min(pictureScale, most));
        }
        float gw = gh * W / H;
        float gx = left + (width - gw) / 2f;
        dst.set(gx, top + free * 0.01f, gx + gw, top + free * 0.01f + gh);

        float softTop = dst.bottom + free * 0.012f;
        float soft = free * 0.055f;
        float third = width / 3f;
        float pad = width * 0.02f;
        buttons.get(0).r.set(left + pad, softTop, left + third - pad, softTop + soft);                // SOFT1
        buttons.get(1).r.set(left + third + pad, softTop, left + 2 * third - pad, softTop + soft);    // CLR
        buttons.get(2).r.set(left + 2 * third + pad, softTop, right - pad, softTop + soft);           // SOFT2

        // the status line sits at the bottom of the free area; the pad and buttons end above it, a little higher
        // than the bare edge, so a thumb resting on them never touches the gesture area
        statusY = bottom - free * 0.008f;
        float areaTop = softTop + soft + free * 0.012f;
        float areaBottom = bottom - free * 0.04f;
        float area = areaBottom - areaTop;
        float cy = areaTop + area / 2f;
        padR = Math.min(width * 0.24f, area * 0.46f);
        padX = left + width * 0.27f;
        padY = cy;
        float big = Math.min(width * 0.13f, area * 0.27f);
        float small = big * 0.72f;
        setCircle(buttons.get(3), left + width * 0.75f, cy + area * 0.16f, big);       // Action
        setCircle(buttons.get(4), left + width * 0.61f, cy - area * 0.21f, small);     // Magic
        setCircle(buttons.get(5), left + width * 0.89f, cy - area * 0.27f, small);     // Status
    }

    private static void setCircle(Button b, float cx, float cy, float r) {
        b.r.set(cx - r, cy - r, cx + r, cy + r);
    }

    @Override
    protected void onDraw(Canvas c) {
        c.drawColor(Color.BLACK);
        synchronized (frame) {
            if (hasFrame) {
                c.drawBitmap(frame, src, dst, pixels);
            }
        }
        // the direction pad
        fill.setStyle(Paint.Style.FILL);
        fill.setColor(0xFF1E2A3C);
        c.drawCircle(padX, padY, padR, fill);
        fill.setColor(held.contains("UP") ? 0xFF5B9DFF : 0xFF34455E);
        drawArrow(c, padX, padY - padR * 0.62f, 0);
        fill.setColor(held.contains("DOWN") ? 0xFF5B9DFF : 0xFF34455E);
        drawArrow(c, padX, padY + padR * 0.62f, 180);
        fill.setColor(held.contains("LEFT") ? 0xFF5B9DFF : 0xFF34455E);
        drawArrow(c, padX - padR * 0.62f, padY, 270);
        fill.setColor(held.contains("RIGHT") ? 0xFF5B9DFF : 0xFF34455E);
        drawArrow(c, padX + padR * 0.62f, padY, 90);
        // the buttons
        for (Button b : buttons) {
            fill.setColor(held.contains(b.key) ? 0xFF5B9DFF : 0xFF34455E);
            if (b.round) {
                c.drawCircle(b.r.centerX(), b.r.centerY(), b.r.width() / 2f, fill);
            } else {
                c.drawRoundRect(b.r, b.r.height() / 3f, b.r.height() / 3f, fill);
            }
            text.setTextSize(Math.min(b.r.height() * 0.38f, b.r.width() * 0.26f));
            c.drawText(b.label, b.r.centerX(), b.r.centerY() + text.getTextSize() * 0.35f, text);
        }
        text.setTextSize(getHeight() * 0.014f);
        text.setColor(0xFF8EA4BF);
        c.drawText(status, dst.centerX(), statusY, text);
        text.setColor(Color.WHITE);
    }

    /** A triangle pointing in `deg` degrees (0 = up) centred on x, y. */
    private void drawArrow(Canvas c, float x, float y, float deg) {
        float s = padR * 0.26f;
        c.save();
        c.rotate(deg, x, y);
        Path p = new Path();
        p.moveTo(x, y - s);
        p.lineTo(x + s, y + s * 0.8f);
        p.lineTo(x - s, y + s * 0.8f);
        p.close();
        c.drawPath(p, fill);
        c.restore();
    }

    @Override
    public boolean onTouchEvent(MotionEvent e) {
        int action = e.getActionMasked();
        trackTap(e, action);
        Set<String> now = new HashSet<>();
        if (action != MotionEvent.ACTION_UP && action != MotionEvent.ACTION_CANCEL) {
            int skip = action == MotionEvent.ACTION_POINTER_UP ? e.getActionIndex() : -1;
            for (int i = 0; i < e.getPointerCount(); i++) {
                if (i != skip) {
                    keysAt(e.getX(i), e.getY(i), now);
                }
            }
        }
        for (String k : new ArrayList<>(held)) {
            if (!now.contains(k)) {
                held.remove(k);
                send(k, false);
            }
        }
        for (String k : now) {
            if (held.add(k)) {
                send(k, true);
            }
        }
        invalidate();
        return true;
    }

    /** A short touch on the picture that does not move is a tap on whatever the game drew there. */
    private void trackTap(MotionEvent e, int action) {
        if (action == MotionEvent.ACTION_DOWN || action == MotionEvent.ACTION_POINTER_DOWN) {
            int i = e.getActionIndex();
            if (tapPointer == -1 && dst.contains(e.getX(i), e.getY(i))) {
                tapPointer = e.getPointerId(i);
                tapX = e.getX(i);
                tapY = e.getY(i);
                tapTime = e.getEventTime();
            }
        } else if (action == MotionEvent.ACTION_UP || action == MotionEvent.ACTION_POINTER_UP) {
            int i = e.getActionIndex();
            if (tapPointer != -1 && e.getPointerId(i) == tapPointer) {
                float x = e.getX(i), y = e.getY(i);
                boolean still = Math.hypot(x - tapX, y - tapY) <= slop * 2;
                if (still && e.getEventTime() - tapTime < 500 && tapSink != null && dst.contains(x, y)) {
                    tapSink.tap((x - dst.left) / dst.width() * W, (y - dst.top) / dst.height() * H);
                }
                tapPointer = -1;
            }
        } else if (action == MotionEvent.ACTION_CANCEL) {
            tapPointer = -1;
        }
    }

    /** Lets go of every key (the app left the foreground). */
    public void releaseAll() {
        for (String k : new ArrayList<>(held)) {
            send(k, false);
        }
        held.clear();
        tapPointer = -1;
        postInvalidate();
    }

    private void send(String key, boolean down) {
        if (sink != null) {
            sink.key(key, down);
        }
    }

    private void keysAt(float x, float y, Set<String> out) {
        for (Button b : buttons) {
            RectF r = b.r;
            if (b.round) {                                                  // a circle, with a little slack for a thumb
                float radius = r.width() / 2f * 1.1f;
                if (Math.hypot(x - r.centerX(), y - r.centerY()) <= radius) {
                    out.add(b.key);
                }
            } else if (r.contains(x, y)) {
                out.add(b.key);
            }
        }
        float dx = x - padX, dy = y - padY;
        if (dx * dx + dy * dy <= padR * padR * 1.4f && dx * dx + dy * dy >= padR * padR * 0.02f) {
            float t = padR * 0.3f;
            if (dx < -t) out.add("LEFT");
            if (dx > t) out.add("RIGHT");
            if (dy < -t) out.add("UP");
            if (dy > t) out.add("DOWN");
        }
    }
}
