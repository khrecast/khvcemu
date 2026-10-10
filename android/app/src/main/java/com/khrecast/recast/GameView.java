package com.khrecast.recast;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.view.MotionEvent;
import android.view.View;

import java.nio.ByteBuffer;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * The game's 176x220 picture (enlarged with the nearest pixel, like the desktop's "crisp pixels") and, under it,
 * the phone's keys as touch controls: a pad for the four directions (diagonals work), Action, Magic, Status, the
 * two softkeys and Back. Several fingers at once are fine.
 */
public class GameView extends View {
    public static final int W = 176, H = 220;

    /** Called for every key that goes down or up (phone key names such as UP, SELECT, STAR, 0, SOFT1). */
    public interface KeySink {
        void key(String name, boolean down);
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
    private float padX, padY, padR;
    private String status = "";
    private KeySink sink;
    private boolean hasFrame;

    public GameView(Context context) {
        super(context);
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

    public void setStatus(String s) {
        status = s;
        postInvalidate();
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldw, int oldh) {
        // the picture at the top, as large as the width allows but at most 58 percent of the height
        float gh = Math.min(w * (float) H / W, h * 0.58f);
        float gw = gh * W / H;
        float gx = (w - gw) / 2f;
        dst.set(gx, h * 0.03f, gx + gw, h * 0.03f + gh);

        float top = dst.bottom + h * 0.012f;
        float soft = h * 0.055f;
        float third = w / 3f;
        float pad = w * 0.02f;
        buttons.get(0).r.set(pad, top, third - pad, top + soft);                    // SOFT1
        buttons.get(1).r.set(third + pad, top, 2 * third - pad, top + soft);        // CLR
        buttons.get(2).r.set(2 * third + pad, top, w - pad, top + soft);            // SOFT2

        float area = h - (top + soft) - h * 0.02f;
        float cy = top + soft + h * 0.01f + area / 2f;
        padR = Math.min(w * 0.24f, area * 0.46f);
        padX = w * 0.27f;
        padY = cy;
        float big = Math.min(w * 0.13f, area * 0.27f);
        float small = big * 0.72f;
        setCircle(buttons.get(3), w * 0.77f, cy + area * 0.12f, big);               // Action
        setCircle(buttons.get(4), w * 0.60f, cy - area * 0.17f, small);             // Magic
        setCircle(buttons.get(5), w * 0.88f, cy - area * 0.22f, small);             // Status
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
        c.drawText(status, getWidth() / 2f, getHeight() - getHeight() * 0.008f, text);
        text.setColor(Color.WHITE);
    }

    /** A triangle pointing in `deg` degrees (0 = up) centred on x, y. */
    private void drawArrow(Canvas c, float x, float y, float deg) {
        float s = padR * 0.26f;
        c.save();
        c.rotate(deg, x, y);
        android.graphics.Path p = new android.graphics.Path();
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

    /** Lets go of every key (the app left the foreground). */
    public void releaseAll() {
        for (String k : new ArrayList<>(held)) {
            send(k, false);
        }
        held.clear();
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
            float grow = b.round ? r.width() * 0.12f : 0f;                  // a little slack around a thumb
            if (x >= r.left - grow && x <= r.right + grow && y >= r.top - grow && y <= r.bottom + grow) {
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
