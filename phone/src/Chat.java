import java.io.*;
import javax.microedition.io.*;
import javax.microedition.lcdui.*;
import javax.microedition.midlet.MIDlet;
import javax.microedition.rms.RecordStore;

public class Chat extends MIDlet implements CommandListener, Runnable {
    private Display display;
    private Form chat = new Form("N95 ChatGPT");
    private StringItem history = new StringItem("", "Ready");
    private TextField message = new TextField("Message", "", 2000, TextField.ANY);
    private Form settings = new Form("Bridge settings");
    private TextField url = new TextField("Bridge URL", "http://192.168.1.100:8095", 200, TextField.URL);
    private TextField token = new TextField("Bridge token", "", 100, TextField.PASSWORD);
    private Command send = new Command("Send", Command.OK, 1);
    private Command config = new Command("Settings", Command.SCREEN, 2);
    private Command fresh = new Command("New conversation", Command.SCREEN, 3);
    private Command exit = new Command("Exit", Command.EXIT, 4);
    private Command save = new Command("Save", Command.OK, 1);
    private String previous = "";
    private String transcript = "";
    private String pending;
    private boolean busy;
    private Voice voice;
    private Speech speech;
    private boolean voiceTurn;
    private Command stopSpeech = new Command("Stop speech", Command.STOP, 1);
    private byte[] pendingAudio;
    private Command talk = new Command("Voice", Command.SCREEN, 1);

    public void showChat() { display.setCurrent(chat); }
    public void onVoiceFinished(final Voice source, final byte[] audio, final String error, final boolean cancelled) {
        display.callSerially(new Runnable() {
            public void run() {
                if (cancelled || display.getCurrent() != source) return;
                display.setCurrent(chat);
                if (error != null) { history.setText(transcript + "\nMicrophone: " + error); return; }
                if (audio == null || audio.length == 0) return;
                pendingAudio = audio; voiceTurn = true; busy = true;
                history.setText(transcript + "\nTranscribing...");
                new Thread(Chat.this).start();
            }
        });
    }

    public void speechReady(final String error) {
        display.callSerially(new Runnable() {
            public void run() {
                history.setText(transcript + (error == null ? "" : "\nSpeech: " + error));
                busy = false;
            }
        });
    }

    public Chat() {
        chat.append(history); chat.append(message);
        chat.addCommand(stopSpeech); chat.addCommand(talk); chat.addCommand(send); chat.addCommand(config); chat.addCommand(fresh); chat.addCommand(exit);
        chat.setCommandListener(this);
        settings.append(url); settings.append(token);
        settings.addCommand(save); settings.setCommandListener(this);
        try {
            RecordStore store = RecordStore.openRecordStore("settings", true);
            try {
                if (store.getNumRecords() > 0) {
                    DataInputStream in = new DataInputStream(new ByteArrayInputStream(store.getRecord(1)));
                    url.setString(in.readUTF()); token.setString(in.readUTF()); in.close();
                }
            } finally { store.closeRecordStore(); }
        } catch (Exception ignored) { }
    }
    public void startApp() {
        if (display == null) {
            display = Display.getDisplay(this);
            display.setCurrent(chat);
        }
    }
    public void pauseApp() { if (voice != null) voice.suspend(); if (speech != null) speech.cancel(); }
    public void destroyApp(boolean unconditional) { if (voice != null) voice.cancel(); if (speech != null) speech.cancel(); }
    public void commandAction(Command command, Displayable screen) {
        if (command == exit) { destroyApp(true); notifyDestroyed(); return; }
        if (command == stopSpeech) { if (speech != null) speech.cancel(); return; }
        if (busy) return;
        if (speech != null) speech.cancel();
        if (command == talk) {
            voice = new Voice(this); display.setCurrent(voice);
        }
        if (command == config) display.setCurrent(settings);
        if (command == fresh) { previous = ""; transcript = ""; history.setText("Ready"); }
        if (command == save) {
            try {
                ByteArrayOutputStream bytes = new ByteArrayOutputStream();
                DataOutputStream out = new DataOutputStream(bytes);
                out.writeUTF(url.getString()); out.writeUTF(token.getString()); out.close();
                byte[] data = bytes.toByteArray();
                RecordStore store = RecordStore.openRecordStore("settings", true);
                try {
                    if (store.getNumRecords() == 0) store.addRecord(data, 0, data.length);
                    else store.setRecord(1, data, 0, data.length);
                } finally { store.closeRecordStore(); }
                previous = ""; transcript = ""; history.setText("Ready");
                display.setCurrent(chat);
            } catch (Exception error) { history.setText("Cannot save settings: " + error.toString()); display.setCurrent(chat); }
        }
        if (command == send && message.getString().trim().length() > 0) {
            pending = message.getString(); voiceTurn = false; busy = true; history.setText(transcript + "\nSending...");
            new Thread(this).start();
        }
    }
    public void run() {
        final boolean transcribing = pendingAudio != null;
        HttpConnection connection = null;
        InputStream input = null;
        OutputStream output = null;
        String answer;
        String responseId = previous;
        boolean success = false;
        try {
            connection = (HttpConnection) Connector.open(url.getString() + (transcribing ? "/transcribe" : "/chat"), Connector.READ_WRITE, true);
            connection.setRequestMethod(HttpConnection.POST);
            connection.setRequestProperty("Content-Type", transcribing ? "application/octet-stream" : "text/plain; charset=utf-8");
            connection.setRequestProperty("X-Bridge-Token", token.getString());
            if (previous.length() > 0) connection.setRequestProperty("X-Response-Id", previous);
            byte[] data = transcribing ? pendingAudio : pending.getBytes("UTF-8");
            connection.setRequestProperty("Content-Length", Integer.toString(data.length));
            output = connection.openOutputStream(); output.write(data); output.close(); output = null;
            int status = connection.getResponseCode();
            input = connection.openInputStream();
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[512]; int count;
            while ((count = input.read(buffer)) != -1) {
                if (bytes.size() + count > 32768) throw new IOException("Reply too large");
                bytes.write(buffer, 0, count);
            }
            answer = new String(bytes.toByteArray(), "UTF-8");
            success = status == 200;
            if (success) {
                responseId = connection.getHeaderField("X-Response-Id");
                if (responseId == null) responseId = "";
            } else answer = "HTTP " + status + ": " + answer;
        } catch (Exception error) { answer = "Connection failed: " + error.toString(); }
        finally {
            try { if (input != null) input.close(); } catch (Exception ignored) { }
            try { if (output != null) output.close(); } catch (Exception ignored) { }
            try { if (connection != null) connection.close(); } catch (Exception ignored) { }
        }
        final String result = answer;
        final String next = responseId;
        final boolean ok = success;
        display.callSerially(new Runnable() {
            public void run() {
                pendingAudio = null;
                if (ok && transcribing) {
                    pending = result;
                    history.setText(transcript + "\nYou: " + result + "\nThinking...");
                    new Thread(Chat.this).start();
                    return;
                } else if (ok) {
                    previous = next;
                    transcript += "\nYou: " + pending + "\nChatGPT: " + result + "\n";
                    if (transcript.length() > 12000) transcript = transcript.substring(transcript.length() - 12000);
                    if (!voiceTurn) message.setString("");
                    history.setText(transcript);
                    if (voiceTurn) {
                        history.setText(transcript + "\nPreparing AI voice...");
                        speech = new Speech(Chat.this, url.getString(), token.getString(), result);
                        new Thread(speech).start();
                        return;
                    }
                } else history.setText(transcript + "\n" + result);
                busy = false;
            }
        });
    }
}
