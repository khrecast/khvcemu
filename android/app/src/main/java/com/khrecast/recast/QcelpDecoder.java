package com.khrecast.recast;

import android.media.MediaCodec;
import android.media.MediaFormat;

import java.io.BufferedOutputStream;
import java.io.DataInputStream;
import java.io.EOFException;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.nio.ByteBuffer;

/**
 * Decodes the QCELP packets of the game's sound effects (".pmd" files; the desktop uses ffmpeg) with the phone's own decoder, when it
 * has one (Samsung phones do: c2.sec.qcelp.decoder). Called by the Python core through `pmd.QCELP_DECODER`.
 */
public final class QcelpDecoder {
    private QcelpDecoder() {
    }

    /** Whether this phone can decode QCELP. */
    public static boolean available() {
        try {
            MediaCodec c = MediaCodec.createDecoderByType("audio/qcelp");
            c.release();
            return true;
        } catch (IOException | RuntimeException e) {
            return false;
        }
    }

    /**
     * Reads `in` (each packet as one length byte and then its bytes), decodes them and writes the samples (16-bit little-endian, mono)
     * to `out`. Returns the sample rate of what was written.
     */
    public static int decode(String in, String out) throws IOException {
        MediaCodec codec = MediaCodec.createDecoderByType("audio/qcelp");
        File tmp = new File(out + ".part");
        int rate = 8000;
        int channels = 1;
        try (DataInputStream packets = new DataInputStream(new java.io.BufferedInputStream(new FileInputStream(in)));
             OutputStream os = new BufferedOutputStream(new FileOutputStream(tmp))) {
            MediaFormat format = MediaFormat.createAudioFormat("audio/qcelp", 8000, 1);
            codec.configure(format, null, null, 0);
            codec.start();
            MediaCodec.BufferInfo info = new MediaCodec.BufferInfo();
            boolean inputDone = false, outputDone = false;
            long time = 0;
            int idle = 0;
            while (!outputDone) {
                if (!inputDone) {
                    int index = codec.dequeueInputBuffer(10_000);
                    if (index >= 0) {
                        int len;
                        try {
                            len = packets.readUnsignedByte();
                        } catch (EOFException end) {
                            len = -1;
                        }
                        if (len < 0) {
                            codec.queueInputBuffer(index, 0, 0, time, MediaCodec.BUFFER_FLAG_END_OF_STREAM);
                            inputDone = true;
                        } else {
                            byte[] packet = new byte[len];
                            packets.readFully(packet);
                            ByteBuffer buf = codec.getInputBuffer(index);
                            buf.clear();
                            buf.put(packet);
                            codec.queueInputBuffer(index, 0, len, time, 0);
                            time += 20_000;                         // each packet is 20 ms
                        }
                    }
                }
                int outIndex = codec.dequeueOutputBuffer(info, 10_000);
                if (outIndex == MediaCodec.INFO_TRY_AGAIN_LATER) {
                    if (inputDone && ++idle > 300) {
                        throw new IOException("the QCELP decoder stopped answering");
                    }
                } else {
                    idle = 0;
                }
                if (outIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED) {
                    MediaFormat of = codec.getOutputFormat();
                    if (of.containsKey(MediaFormat.KEY_SAMPLE_RATE)) {
                        rate = of.getInteger(MediaFormat.KEY_SAMPLE_RATE);
                    }
                    if (of.containsKey(MediaFormat.KEY_CHANNEL_COUNT)) {
                        channels = of.getInteger(MediaFormat.KEY_CHANNEL_COUNT);
                    }
                } else if (outIndex >= 0) {
                    ByteBuffer pcm = codec.getOutputBuffer(outIndex);
                    if (pcm != null && info.size > 0) {
                        byte[] bytes = new byte[info.size];
                        pcm.position(info.offset);
                        pcm.get(bytes);
                        if (channels == 2) {                         // (not expected) keep the left channel
                            byte[] mono = new byte[bytes.length / 2];
                            for (int i = 0; i + 3 < bytes.length; i += 4) {
                                mono[i / 2] = bytes[i];
                                mono[i / 2 + 1] = bytes[i + 1];
                            }
                            bytes = mono;
                        }
                        os.write(bytes);
                    }
                    codec.releaseOutputBuffer(outIndex, false);
                    if ((info.flags & MediaCodec.BUFFER_FLAG_END_OF_STREAM) != 0) {
                        outputDone = true;
                    }
                }
            }
        } catch (IllegalStateException | IllegalArgumentException e) {
            throw new IOException("the QCELP decoder failed (" + e.getMessage() + ")");
        } finally {
            tmp.delete();                                           // (gone after a rename; left only after a failure)
            try {
                codec.stop();
            } catch (IllegalStateException ignored) {
            }
            codec.release();
        }
        File dest = new File(out);
        if (dest.exists() && !dest.delete() || !tmp.renameTo(dest)) {
            throw new IOException("could not write " + out);
        }
        return rate;
    }
}
