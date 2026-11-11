import { StatusBar } from 'expo-status-bar';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Image,
  Linking,
  PermissionsAndroid,
  Platform,
  Pressable,
  StatusBar as RNStatusBar,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
} from 'react-native';

import CubeGlasses from './modules/cube-glasses';

const DEFAULT_URL = 'ws://192.168.1.10:8000/ws/device?session=default';

type Coach = { phase: string; title: string; alg: string; say: string; detail: string };

/** Returns whether Bluetooth (needed for the glasses) was granted. */
async function requestAndroidPermissions(): Promise<'granted' | 'denied' | 'blocked'> {
  if (Platform.OS !== 'android') return 'granted';
  const P = PermissionsAndroid.PERMISSIONS;
  const r = await PermissionsAndroid.requestMultiple([P.BLUETOOTH_CONNECT, P.RECORD_AUDIO, P.CAMERA]);
  const bt = r[P.BLUETOOTH_CONNECT];
  if (bt === PermissionsAndroid.RESULTS.GRANTED) return 'granted';
  return bt === PermissionsAndroid.RESULTS.NEVER_ASK_AGAIN ? 'blocked' : 'denied';
}

export default function App() {
  const [serverUrl, setServerUrl] = useState(() => CubeGlasses.getPref('serverUrl') ?? DEFAULT_URL);
  const [server, setServer] = useState({ connected: false, status: 'Not connected' });
  const [registration, setRegistration] = useState('UNAVAILABLE');
  const [devices, setDevices] = useState(0);
  const [stream, setStream] = useState('STOPPED');
  const [status, setStatus] = useState('Starting…');
  const [preview, setPreview] = useState<string | null>(null);
  const [coach, setCoach] = useState<Coach>({ phase: '', title: '', alg: '', say: '', detail: '' });
  const [level, setLevel] = useState<'full' | '2look'>('full');
  const [speakOnPhone, setSpeakOnPhone] = useState(true);
  const [mic, setMic] = useState(false);
  const [mock, setMock] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [sdkReady, setSdkReady] = useState(false);
  const [btBlocked, setBtBlocked] = useState(false);
  const started = useRef(false);

  const addLog = useCallback((line: string) => setLog((l) => [line, ...l].slice(0, 40)), []);

  useEffect(() => {
    const subs = [
      CubeGlasses.addListener('onRegistration', (e) => setRegistration(e.state)),
      CubeGlasses.addListener('onDevices', (e) => setDevices(e.count)),
      CubeGlasses.addListener('onStatus', (e) => setStatus(e.status)),
      CubeGlasses.addListener('onStream', (e) => {
        setStream(e.state);
        if (e.state === 'STOPPED') setPreview(null);
      }),
      CubeGlasses.addListener('onPreview', (e) => setPreview(`data:image/jpeg;base64,${e.jpeg}`)),
      CubeGlasses.addListener('onServer', (e) => setServer(e)),
      CubeGlasses.addListener('onServerEvent', (e) => {
        let ev: any;
        try {
          ev = JSON.parse(e.json);
        } catch {
          return;
        }
        if (ev.say) addLog(`${ev.type}: ${ev.say}`);
        setCoach((c) => {
          const next = { ...c };
          if (ev.say) next.say = ev.say;
          if (ev.step) {
            next.title = ev.step.title ?? '';
            next.alg = ev.step.alg ?? '';
            next.detail = ev.step.explanation ?? '';
          }
          if (['solution', 'step', 'progress', 'step_done', 'off_track'].includes(ev.type)) next.phase = 'solving';
          if (['scan_progress', 'scan_error', 'reset', 'lost', 'welcome'].includes(ev.type)) {
            next.phase = 'scanning';
            next.title = '';
            next.alg = '';
            next.detail = '';
          }
          if (ev.type === 'solved') {
            next.phase = 'solved';
            next.title = 'Solved!';
            next.alg = '';
          }
          return next;
        });
      }),
    ];

    if (!started.current) {
      started.current = true;
      CubeGlasses.connect(serverUrl);
      setupGlasses();
    }
    return () => subs.forEach((s) => s.remove());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function setupGlasses() {
    const bt = await requestAndroidPermissions();
    if (bt !== 'granted') {
      setBtBlocked(bt === 'blocked');
      setStatus('Bluetooth permission is needed to talk to the glasses.');
      return;
    }
    const init = await CubeGlasses.initialize();
    setSdkReady(init === 'ok');
    setStatus(init === 'ok' ? 'Glasses SDK ready' : init);
  }

  const streaming = stream !== 'STOPPED' && stream !== 'CLOSED';
  const registered = registration === 'REGISTERED';

  async function toggleCamera() {
    if (streaming) {
      await CubeGlasses.stopStreaming();
      await CubeGlasses.setKeepScreenOn(false);
      return;
    }
    const perm = await CubeGlasses.requestCameraPermission();
    if (perm !== 'granted') {
      setStatus('Glasses camera permission denied in the Meta AI app');
      return;
    }
    const r = await CubeGlasses.startStreaming(5);
    if (r !== 'ok') setStatus(r);
    await CubeGlasses.setKeepScreenOn(true);
  }

  function connectServer() {
    CubeGlasses.setPref('serverUrl', serverUrl.trim());
    CubeGlasses.connect(serverUrl.trim());
  }

  function send(obj: object) {
    CubeGlasses.send(JSON.stringify(obj));
  }

  return (
    <View style={styles.root}>
      <StatusBar style="light" />
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.h1}>CubeVision</Text>
        <View style={styles.pills}>
          <Pill ok={server.connected} label={server.connected ? 'Server' : 'Server offline'} />
          <Pill ok={registered} label={registered ? 'Glasses linked' : 'Glasses not linked'} />
          <Pill ok={stream === 'STREAMING'} label={`Camera ${stream.toLowerCase()}`} />
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>{coach.phase ? coach.phase.toUpperCase() : 'COACH'}</Text>
          {!!coach.title && <Text style={styles.title}>{coach.title}</Text>}
          {!!coach.alg && <Text style={styles.alg}>{coach.alg}</Text>}
          <Text style={styles.say}>{coach.say || 'Connect to the server and start the camera, then look at your cube.'}</Text>
          {!!coach.detail && <Text style={styles.detail}>{coach.detail}</Text>}
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>GLASSES</Text>
          {preview ? (
            <Image source={{ uri: preview }} style={styles.preview} resizeMode="contain" />
          ) : (
            <View style={[styles.preview, styles.previewEmpty]}>
              <Text style={styles.muted}>No camera feed</Text>
            </View>
          )}
          <Text style={styles.muted}>{status}</Text>
          <Text style={styles.muted}>
            Meta AI: {registration.toLowerCase()} · glasses found: {devices}
          </Text>
          {!sdkReady && (
            <Button
              primary
              label={btBlocked ? 'Open settings to allow Bluetooth' : 'Allow Bluetooth'}
              onPress={() => (btBlocked ? Linking.openSettings() : setupGlasses())}
            />
          )}
          {sdkReady && !registered && (
            <Button label="Link glasses (opens Meta AI app)" onPress={() => CubeGlasses.startRegistration()} />
          )}
          <Button
            primary
            label={streaming ? 'Stop camera' : 'Start camera'}
            onPress={toggleCamera}
            disabled={!sdkReady || (!registered && !mock)}
          />
          <Row label="Mock glasses (use phone camera)">
            <Switch
              value={mock}
              disabled={!sdkReady}
              onValueChange={async (v) => {
                const r = await CubeGlasses.setMockGlasses(v);
                if (r === 'ok') setMock(v);
                else setStatus(r);
              }}
            />
          </Row>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>WEB APP</Text>
          <TextInput
            style={styles.input}
            value={serverUrl}
            onChangeText={setServerUrl}
            autoCapitalize="none"
            autoCorrect={false}
            placeholder="ws://<computer-ip>:8000/ws/device?session=default"
            placeholderTextColor="#777"
          />
          <Text style={styles.muted}>{server.status}</Text>
          <View style={styles.rowButtons}>
            <Button label={server.connected ? 'Reconnect' : 'Connect'} onPress={connectServer} />
            <Button label="Start over" onPress={() => send({ type: 'reset' })} />
          </View>
          <Row label="Beginner mode (2-look OLL/PLL)">
            <Switch
              value={level === '2look'}
              onValueChange={(v) => {
                const l = v ? '2look' : 'full';
                setLevel(l);
                send({ type: 'config', level: l });
              }}
            />
          </Row>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>AUDIO</Text>
          <Row label="Speak instructions on phone if server sends no audio">
            <Switch
              value={speakOnPhone}
              onValueChange={(v) => {
                setSpeakOnPhone(v);
                CubeGlasses.setSpeakFallback(v);
              }}
            />
          </Row>
          <Row label="Send glasses mic to server">
            <Switch
              value={mic}
              onValueChange={async (v) => {
                const r = await CubeGlasses.setMicForwarding(v);
                setMic(r === 'on');
                if (r !== 'on' && r !== 'off') setStatus(`Mic: ${r}`);
              }}
            />
          </Row>
        </View>

        <View style={styles.card}>
          <Text style={styles.label}>LOG</Text>
          {log.length === 0 ? <Text style={styles.muted}>Nothing yet</Text> : null}
          {log.map((l, i) => (
            <Text key={i} style={styles.logLine}>
              {l}
            </Text>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

function Pill({ ok, label }: { ok: boolean; label: string }) {
  return (
    <View style={[styles.pill, ok ? styles.pillOk : styles.pillOff]}>
      <Text style={styles.pillText}>{label}</Text>
    </View>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <View style={styles.row}>
      <Text style={styles.rowLabel}>{label}</Text>
      {children}
    </View>
  );
}

function Button(props: { label: string; onPress: () => void; primary?: boolean; disabled?: boolean }) {
  return (
    <Pressable
      onPress={props.onPress}
      disabled={props.disabled}
      style={({ pressed }) => [
        styles.button,
        props.primary && styles.buttonPrimary,
        (pressed || props.disabled) && { opacity: props.disabled ? 0.4 : 0.7 },
      ]}
    >
      <Text style={[styles.buttonText, props.primary && { color: '#fff' }]}>{props.label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#111214' },
  scroll: { padding: 16, paddingTop: (RNStatusBar.currentHeight ?? 24) + 12, gap: 14 },
  h1: { color: '#fff', fontSize: 26, fontWeight: '700' },
  pills: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  pill: { paddingHorizontal: 10, paddingVertical: 4, borderRadius: 99 },
  pillOk: { backgroundColor: '#1f6f43' },
  pillOff: { backgroundColor: '#3a3b40' },
  pillText: { color: '#fff', fontSize: 12 },
  card: { backgroundColor: '#1c1d21', borderRadius: 14, padding: 14, gap: 8 },
  label: { color: '#8b8d95', fontSize: 12, letterSpacing: 1, fontWeight: '600' },
  title: { color: '#fff', fontSize: 20, fontWeight: '700' },
  alg: { color: '#ffd400', fontSize: 22, fontFamily: 'monospace' },
  say: { color: '#e8e8ea', fontSize: 17 },
  detail: { color: '#a5a7ae', fontSize: 14 },
  muted: { color: '#9a9ca3', fontSize: 13 },
  preview: { width: '100%', aspectRatio: 9 / 16, maxHeight: 360, borderRadius: 10, backgroundColor: '#000' },
  previewEmpty: { alignItems: 'center', justifyContent: 'center' },
  input: {
    color: '#fff',
    backgroundColor: '#111214',
    borderRadius: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    fontFamily: 'monospace',
    fontSize: 13,
  },
  row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 12 },
  rowLabel: { color: '#e8e8ea', flex: 1, fontSize: 14 },
  rowButtons: { flexDirection: 'row', gap: 8 },
  button: { backgroundColor: '#2c2d33', borderRadius: 10, paddingVertical: 11, paddingHorizontal: 14, alignItems: 'center' },
  buttonPrimary: { backgroundColor: '#2f6fde' },
  buttonText: { color: '#e8e8ea', fontSize: 15, fontWeight: '600' },
  logLine: { color: '#c9cbd1', fontSize: 12, fontFamily: 'monospace' },
});
