import java.io.*;
import javax.microedition.lcdui.*;
import javax.microedition.media.*;
import javax.microedition.media.control.RecordControl;

/** Recording is owned by one worker, including cleanup and commit. */
public class Voice extends Canvas implements CommandListener, Runnable {
    private Chat app;
    private Command back = new Command("Back", Command.BACK, 2);
    private Command toggle = new Command("Record / Stop", Command.SCREEN, 1);
    private volatile boolean stop;
    private volatile boolean cancelled;
    private boolean active;
    private volatile long captureStarted;
    private volatile long firstWrite;
    private volatile boolean recording;
    private volatile boolean holdToTalk;
    private volatile String status = "Hold centre or 5 to talk";

    public Voice(Chat app) {
        this.app = app;
        addCommand(back); addCommand(toggle); setCommandListener(this);
    }
    protected void paint(Graphics g) {
        g.setColor(0x102A30); g.fillRect(0, 0, getWidth(), getHeight());
        g.setColor(0xFFFFFF);
        g.drawString("Push to talk", getWidth()/2, 24, Graphics.TOP | Graphics.HCENTER);
        g.drawString(status, getWidth()/2, 70, Graphics.TOP | Graphics.HCENTER);
        g.drawString("Release or use Record / Stop", getWidth()/2, 100, Graphics.TOP | Graphics.HCENTER);
        g.drawString("Maximum 30 seconds", getWidth()/2, 130, Graphics.TOP | Graphics.HCENTER);
    }
    private boolean talkKey(int key) {
        return key == KEY_NUM5 || getGameAction(key) == FIRE;
    }
    protected void keyPressed(int key) {
        if (talkKey(key)) {
            holdToTalk = true;
            begin();
        }
    }
    protected void keyReleased(int key) {
        if (talkKey(key)) {
            holdToTalk = false;
            // Permission dialogs can consume the initial press/release pair.
            // Only a release during actual recording finishes the clip.
            if (recording) stop = true;
        }
    }
    public synchronized void cancel() { cancelled = true; stop = true; }
    public void suspend() { if (recording) cancel(); }
    protected void hideNotify() {
        holdToTalk = false;
        suspend();
    }
    public void commandAction(Command command, Displayable screen) {
        if (command == back) { cancel(); app.showChat(); }
        if (command == toggle) {
            synchronized (this) {
                if (active) stop = true;
                else { holdToTalk = false; begin(); }
            }
        }
    }
    private synchronized void begin() {
        if (active) return;
        active = true; stop = false; cancelled = false;
        status = "Opening microphone..."; repaint();
        new Thread(this).start();
    }
    public void run() {
        Player player = null;
        byte[] audio = null;
        String error = null;
        try {
            player = Manager.createPlayer("capture://audio");
            player.realize();
            RecordControl recorder = (RecordControl) player.getControl("RecordControl");
            if (recorder == null) throw new IOException("Recording unavailable");
            firstWrite = 0; captureStarted = System.currentTimeMillis();
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            // Bound memory even on phones that do not support setRecordSizeLimit.
            final ByteArrayOutputStream captured = bytes;
            recorder.setRecordStream(new OutputStream() {
                public void write(int value) throws IOException {
                    if (captured.size() >= 2097152) throw new IOException("Recording too large");
                    if (firstWrite == 0) firstWrite = System.currentTimeMillis();
                    captured.write(value);
                }
                public void write(byte[] data, int offset, int length) throws IOException {
                    if (captured.size() + length > 2097152) throw new IOException("Recording too large");
                    if (length > 0 && firstWrite == 0) firstWrite = System.currentTimeMillis();
                    captured.write(data, offset, length);
                }
            });
            if (!stop) {
                status = "Starting audio..."; repaint();
                recorder.startRecord(); player.start();
                recording = true;
                status = holdToTalk ? "Recording..." : "Recording - use Stop";
                repaint();
                long recordingStarted = System.currentTimeMillis();
                long deadline = recordingStarted + 30000;
                long nextSample = recordingStarted + 1000;
                while (!stop && System.currentTimeMillis() < deadline) {
                    Thread.sleep(50);
                    if (System.currentTimeMillis() >= nextSample) {
                        app.timing("Capture at " + (System.currentTimeMillis() - recordingStarted) + " ms: " + bytes.size() + " bytes");
                        nextSample += 1000;
                    }
                }
                app.released();
                int beforeCommit = bytes.size();
                recording = false;
                long commitStarted = System.currentTimeMillis();
                recorder.stopRecord(); recorder.commit();
                app.timing("Capture bytes before commit: " + beforeCommit + "/" + bytes.size());
                app.timing("First capture write: " + (firstWrite == 0 ? -1 : firstWrite - captureStarted) + " ms after opening");
                app.timing("Commit: " + (System.currentTimeMillis() - commitStarted) + " ms");
                audio = bytes.toByteArray();
            }
        } catch (Exception exception) { error = exception.toString(); }
        finally {
            recording = false;
            if (player != null) player.close();
        }
        final byte[] result = audio;
        final String problem = error;
        app.onVoiceFinished(this, result, problem, cancelled);
        synchronized (this) { active = false; }
        status = "Hold centre or 5 to talk";
        repaint();
    }
}
