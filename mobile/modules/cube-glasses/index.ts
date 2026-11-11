import { NativeModule, requireNativeModule } from 'expo';

/** Events the native side emits. */
export type CubeGlassesEvents = {
  /** Meta AI registration: UNAVAILABLE | AVAILABLE | REGISTERING | REGISTERED | UNREGISTERING */
  onRegistration(e: { state: string }): void;
  onDevices(e: { count: number }): void;
  onStatus(e: { status: string }): void;
  /** Camera stream state from the SDK (STARTING, STREAMING, PAUSED, STOPPED, ...) */
  onStream(e: { state: string }): void;
  /** ~1.4 fps preview of what the glasses see (base64 JPEG). */
  onPreview(e: { jpeg: string; width: number; height: number }): void;
  onServer(e: { connected: boolean; status: string }): void;
  /** A coaching event from the web app, as a JSON string. */
  onServerEvent(e: { json: string }): void;
};

declare class CubeGlassesModule extends NativeModule<CubeGlassesEvents> {
  initialize(): Promise<string>;
  startRegistration(): Promise<void>;
  startUnregistration(): Promise<void>;
  requestCameraPermission(): Promise<'granted' | 'denied'>;
  setMockGlasses(enabled: boolean): Promise<string>;
  startStreaming(fps: number): Promise<string>;
  stopStreaming(): Promise<void>;
  connect(url: string): Promise<void>;
  disconnect(): Promise<void>;
  send(json: string): Promise<boolean>;
  setSpeakFallback(on: boolean): Promise<void>;
  setMicForwarding(on: boolean): Promise<string>;
  setKeepScreenOn(on: boolean): Promise<void>;
  getPref(key: string): string | null;
  setPref(key: string, value: string): void;
}

export default requireNativeModule<CubeGlassesModule>('CubeGlasses');
