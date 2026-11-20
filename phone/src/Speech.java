import java.io.*;
import javax.microedition.io.*;
import javax.microedition.media.*;

/** Keeps a streaming HTTP response open until the media player finishes. */
public class Speech implements Runnable, PlayerListener {
    private Chat app;
    private String url;
    private String token;
    private String text;
    private boolean streaming;
    private volatile boolean cancelled;
    private volatile boolean ended;
    private volatile String playbackError;
    private Player player;
    private HttpConnection connection;
    private InputStream input;

    public Speech(Chat app, String url, String token, String text, boolean streaming) {
        this.app = app; this.url = url; this.token = token; this.text = text;
        this.streaming = streaming;
    }
    public void cancel() {
        cancelled = true;
        closeResources();
    }
    private void closeResources() {
        Player current;
        InputStream stream;
        HttpConnection http;
        synchronized (this) {
            current = player; player = null;
            stream = input; input = null;
            http = connection; connection = null;
        }
        if (current != null) current.close();
        try { if (stream != null) stream.close(); } catch (IOException ignored) { }
        try { if (http != null) http.close(); } catch (IOException ignored) { }
    }
    public void playerUpdate(Player source, String event, Object data) {
        if (event.equals(PlayerListener.ERROR)) playbackError = String.valueOf(data);
        if (event.equals(PlayerListener.END_OF_MEDIA) || event.equals(PlayerListener.ERROR)) ended = true;
    }
    public void run() {
        long started = System.currentTimeMillis();
        OutputStream output = null;
        boolean announced = false;
        String error = null;
        try {
            HttpConnection http = (HttpConnection) Connector.open(url + (streaming ? "/speak-stream" : "/speak"), Connector.READ_WRITE, true);
            synchronized (this) {
                if (cancelled) { http.close(); return; }
                connection = http;
            }
            http.setRequestMethod(HttpConnection.POST);
            http.setRequestProperty("Content-Type", "text/plain; charset=utf-8");
            http.setRequestProperty("X-Bridge-Token", token);
            byte[] request = text.getBytes("UTF-8");
            http.setRequestProperty("Content-Length", Integer.toString(request.length));
            output = http.openOutputStream(); output.write(request); output.close(); output = null;
            int status = http.getResponseCode();
            InputStream body = http.openInputStream();
            synchronized (this) {
                if (cancelled) { body.close(); return; }
                input = body;
            }
            app.timing("Speech HTTP headers: " + (System.currentTimeMillis() - started) + " ms");
            if (status != 200) throw new IOException("Speech HTTP " + status);
            InputStream media = new LimitedInput(body);
            if (!streaming) {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                byte[] buffer = new byte[2048]; int count;
                while ((count = media.read(buffer)) != -1) {
                    if (cancelled) return;
                    bytes.write(buffer, 0, count);
                }
                media = new ByteArrayInputStream(bytes.toByteArray());
                app.timing("Speech download: " + (System.currentTimeMillis() - started) + " ms");
            }
            Player current = Manager.createPlayer(media, "audio/mpeg");
            synchronized (this) {
                if (cancelled) { current.close(); return; }
                player = current;
            }
            current.addPlayerListener(this);
            current.realize(); current.prefetch();
            if (cancelled) return;
            current.start();
            app.timing((streaming ? "Streaming" : "Buffered") + " player start: " + (System.currentTimeMillis() - started) + " ms");
            app.playbackStarted();
            app.speechReady(this, null); announced = true;
            long deadline = System.currentTimeMillis() + 180000;
            while (!ended && !cancelled && System.currentTimeMillis() < deadline) Thread.sleep(50);
            if (!cancelled) {
                error = playbackError;
                if (!ended) error = "Playback timed out";
            }
        } catch (Exception exception) {
            if (!cancelled) error = exception.toString();
        } finally {
            try { if (output != null) output.close(); } catch (Exception ignored) { }
            closeResources();
            if (!announced || error != null) app.speechReady(this, error);
        }
    }
    private static class LimitedInput extends InputStream {
        private InputStream source;
        private int total;
        LimitedInput(InputStream source) { this.source = source; }
        public int read() throws IOException {
            int value = source.read();
            if (value >= 0) check(1);
            return value;
        }
        public int read(byte[] bytes, int offset, int length) throws IOException {
            int count = source.read(bytes, offset, length);
            if (count > 0) check(count);
            return count;
        }
        private void check(int count) throws IOException {
            total += count;
            if (total > 2097152) throw new IOException("Speech too large");
        }
        public int available() throws IOException { return source.available(); }
        public void close() throws IOException { source.close(); }
    }
}
