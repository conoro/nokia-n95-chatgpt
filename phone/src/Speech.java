import java.io.*;
import javax.microedition.io.*;
import javax.microedition.media.*;

/** Downloads speech separately so a playback failure cannot lose the chat reply. */
public class Speech implements Runnable, PlayerListener {
    private Chat app;
    private String url;
    private String token;
    private String text;
    private boolean cancelled;
    private Player player;

    public Speech(Chat app, String url, String token, String text) {
        this.app = app; this.url = url; this.token = token; this.text = text;
    }
    public synchronized void cancel() {
        cancelled = true;
        if (player != null) { player.close(); player = null; }
    }
    public void playerUpdate(Player source, String event, Object data) {
        if (event.equals(PlayerListener.END_OF_MEDIA) || event.equals(PlayerListener.ERROR)) {
            cancel();
        }
    }
    public void run() {
        HttpConnection connection = null;
        InputStream input = null;
        OutputStream output = null;
        String error = null;
        try {
            connection = (HttpConnection) Connector.open(url + "/speak", Connector.READ_WRITE, true);
            connection.setRequestMethod(HttpConnection.POST);
            connection.setRequestProperty("Content-Type", "text/plain; charset=utf-8");
            connection.setRequestProperty("X-Bridge-Token", token);
            byte[] request = text.getBytes("UTF-8");
            connection.setRequestProperty("Content-Length", Integer.toString(request.length));
            output = connection.openOutputStream(); output.write(request); output.close(); output = null;
            int status = connection.getResponseCode();
            input = connection.openInputStream();
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[2048]; int count;
            while ((count = input.read(buffer)) != -1) {
                if (bytes.size() + count > 2097152) throw new IOException("Speech too large");
                synchronized (this) { if (cancelled) return; }
                bytes.write(buffer, 0, count);
            }
            if (status != 200) throw new IOException("HTTP " + status + " " + new String(bytes.toByteArray(), "UTF-8"));
            synchronized (this) {
                if (!cancelled) {
                    player = Manager.createPlayer(new ByteArrayInputStream(bytes.toByteArray()), "audio/mpeg");
                    player.addPlayerListener(this);
                    player.realize(); player.prefetch(); player.start();
                }
            }
        } catch (Exception exception) {
            error = exception.toString(); cancel();
        } finally {
            try { if (input != null) input.close(); } catch (Exception ignored) { }
            try { if (output != null) output.close(); } catch (Exception ignored) { }
            try { if (connection != null) connection.close(); } catch (Exception ignored) { }
            app.speechReady(error);
        }
    }
}
