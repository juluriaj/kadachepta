import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAudioPlayer, setAudioModeAsync, type AudioPlayer, type AudioStatus } from 'expo-audio';
import { AppState, Platform } from 'react-native';

import { api, mediaUrl } from '../api';
import { localUri } from '../downloads';
import type { Story } from '../types';
import {
  fadeVolume, listenedDelta, onStoryFinished, resumePosition, sleepRemaining, type SleepMode,
} from './logic';

// The playback engine lives outside React: one audio player for the whole app, driven by native
// status events (which keep arriving while the app is in the background), with React subscribing
// to snapshots through useSyncExternalStore.

export type PlayerSnapshot = {
  story: Story | null;
  queue: Story[];
  playing: boolean;
  buffering: boolean;
  position: number;
  duration: number;
  rate: number;
  sleep: SleepMode;
  sleepSecondsLeft: number | null;
  bedtime: boolean;
  driveMode: boolean;
  dataSaver: boolean;
  goodnight: boolean;
  error: string | null;
};

const PREFS = 'kc.player';
const FLUSH_SECONDS = 15;

function localDay() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

function screenIsOff() {
  if (Platform.OS === 'web') return typeof document !== 'undefined' && document.visibilityState === 'hidden';
  return AppState.currentState !== 'active';
}

export class PlayerEngine {
  private player: AudioPlayer;
  private listeners = new Set<() => void>();
  private snapshot: PlayerSnapshot = {
    story: null, queue: [], playing: false, buffering: false, position: 0, duration: 0, rate: 1, sleep: 'off',
    sleepSecondsLeft: null, bedtime: false, driveMode: false, dataSaver: false, goodnight: false, error: null,
  };
  private autoContinue = false;
  private sleepEndsAt: number | null = null;
  private finishedFor: string | null = null;
  private pending = { storyId: null as string | null, seconds: 0, screenOff: 0, started: false, last: null as number | null };
  private completedListeners = new Set<() => void>();

  constructor() {
    this.player = createAudioPlayer(null, { updateInterval: 500 });
    this.player.addListener('playbackStatusUpdate', (status) => this.onStatus(status));
    void setAudioModeAsync({ playsInSilentMode: true, shouldPlayInBackground: true, interruptionMode: 'doNotMix' });
    setInterval(() => this.tickSleep(), 1000);
    AppState.addEventListener('change', (state) => {
      if (state !== 'active') this.flush();
    });
    if (Platform.OS === 'web' && typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') this.flush();
      });
    }
    AsyncStorage.getItem(PREFS).then((raw) => {
      const prefs = raw ? JSON.parse(raw) : {};
      this.set({
        rate: typeof prefs.rate === 'number' ? prefs.rate : 1,
        dataSaver: typeof prefs.dataSaver === 'boolean' ? prefs.dataSaver : false,
      });
    }).catch(() => {});
  }

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = () => this.snapshot;

  onStoryCompleted = (listener: () => void) => {
    this.completedListeners.add(listener);
    return () => {
      this.completedListeners.delete(listener);
    };
  };

  private set(patch: Partial<PlayerSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch };
    this.listeners.forEach((listener) => listener());
  }

  private savePrefs(patch: Record<string, unknown>) {
    AsyncStorage.getItem(PREFS)
      .then((raw) => AsyncStorage.setItem(PREFS, JSON.stringify({ ...(raw ? JSON.parse(raw) : {}), ...patch })))
      .catch(() => {});
  }

  private onStatus(status: AudioStatus) {
    // Count real listening time from playback progress, robust to timers being throttled in the background.
    if (status.playing) {
      const delta = listenedDelta(this.pending.last, status.currentTime, this.snapshot.rate);
      this.pending.last = status.currentTime;
      if (delta > 0) {
        this.pending.seconds += delta;
        if (screenIsOff()) this.pending.screenOff += delta;
        if (this.pending.seconds >= FLUSH_SECONDS) this.flush();
      }
    } else {
      if (this.snapshot.playing) this.flush();
      this.pending.last = null;
    }
    this.set({
      playing: status.playing, buffering: status.isBuffering, position: status.currentTime || 0,
      duration: status.duration || this.snapshot.story?.duration || 0,
    });
    if (status.didJustFinish) this.onFinished();
    this.tickSleep();
  }

  private flush(completed = false) {
    const pending = this.pending;
    if (!pending.storyId || (!pending.seconds && !pending.started && !completed)) return;
    const body = {
      assetId: pending.storyId, seconds: Math.round(pending.seconds * 10) / 10,
      screenOffSeconds: Math.round(pending.screenOff * 10) / 10, position: this.player.currentTime || 0,
      started: pending.started, completed, day: localDay(),
    };
    pending.seconds = 0;
    pending.screenOff = 0;
    pending.started = false;
    api('/api/me/listening', { method: 'POST', body }).then(() => {
      if (completed) this.completedListeners.forEach((listener) => listener());
    }).catch(() => {
      // Offline: keep the time so it goes out with the next report for the same story.
      if (this.pending.storyId === body.assetId) {
        this.pending.seconds += body.seconds;
        this.pending.screenOff += body.screenOffSeconds;
      }
    });
  }

  private async load(story: Story, startAt: number) {
    this.flush();
    this.finishedFor = null;
    this.set({ error: null, goodnight: false });
    const offline = await localUri(story.id);
    const { dataSaver, rate } = this.snapshot;
    const source = offline ?? mediaUrl(dataSaver ? story.audioUrlDataSaver ?? story.audioUrl : story.audioUrl);
    if (!source) {
      this.set({ error: 'This story has no audio yet.' });
      return;
    }
    this.player.replace({ uri: source });
    this.player.volume = 1;
    this.player.setPlaybackRate(rate);
    if (startAt > 0) await this.player.seekTo(startAt);
    this.player.play();
    this.pending = { storyId: story.id, seconds: 0, screenOff: 0, started: true, last: null };
    this.set({ story, position: startAt, duration: story.duration });
    if (Platform.OS !== 'web') {
      this.player.setActiveForLockScreen(true, {
        title: story.title, artist: story.narrator, albumTitle: story.album ?? 'KathaChepta',
        artworkUrl: mediaUrl(story.artworkUrl) ?? undefined,
      }, { showSeekBackward: true, showSeekForward: true });
    }
  }

  private onFinished() {
    const { story, bedtime, sleep, queue, driveMode } = this.snapshot;
    if (!story || this.finishedFor === story.id) return;
    this.finishedFor = story.id;
    this.flush(true);
    const action = onStoryFinished({ bedtime, sleep, hasNext: queue.length > 0, autoContinue: this.autoContinue || driveMode });
    if (action === 'next') this.next();
    else if (action === 'goodnight') {
      this.sleepEndsAt = null;
      this.set({ goodnight: true, sleep: 'off', sleepSecondsLeft: null });
    }
  }

  private tickSleep() {
    if (this.sleepEndsAt == null) return;
    const remaining = sleepRemaining(this.sleepEndsAt, Date.now());
    this.player.volume = fadeVolume(remaining);
    if (remaining !== null && remaining <= 0) {
      this.player.pause();
      this.player.volume = 1;
      this.sleepEndsAt = null;
      this.set({ sleep: 'off', sleepSecondsLeft: null, goodnight: true });
    } else {
      this.set({ sleepSecondsLeft: remaining });
    }
  }

  play = async (story: Story, options?: { queue?: Story[]; autoContinue?: boolean }) => {
    this.autoContinue = options?.autoContinue ?? Boolean(options?.queue?.length);
    this.set({ queue: options?.queue ?? [] });
    await this.load(story, resumePosition(story.progress, story.duration));
  };

  toggle = () => {
    if (!this.snapshot.story) return;
    if (this.player.playing) this.player.pause();
    else {
      this.set({ goodnight: false });
      this.player.play();
    }
  };

  seekBy = (seconds: number) => void this.player.seekTo(Math.max(0, (this.player.currentTime || 0) + seconds));
  seekTo = (seconds: number) => void this.player.seekTo(Math.max(0, seconds));

  setRate = (rate: number) => {
    this.player.setPlaybackRate(rate);
    this.set({ rate });
    this.savePrefs({ rate });
  };

  setSleep = (mode: SleepMode) => {
    this.sleepEndsAt = typeof mode === 'number' ? Date.now() + mode * 60_000 : null;
    if (typeof mode !== 'number') this.player.volume = 1;
    this.set({ sleep: mode, sleepSecondsLeft: typeof mode === 'number' ? mode * 60 : null });
  };

  setBedtime = (on: boolean) => {
    this.set({ bedtime: on });
    // Bedtime starts a 20-minute timer unless one is already running.
    if (on && this.snapshot.sleep === 'off') this.setSleep(20);
  };

  setDriveMode = (on: boolean) => this.set({ driveMode: on });

  setDataSaver = (on: boolean) => {
    this.set({ dataSaver: on });
    this.savePrefs({ dataSaver: on });
  };

  next = () => {
    const [nextStory, ...rest] = this.snapshot.queue;
    if (!nextStory) return;
    this.set({ queue: rest });
    void this.load(nextStory, resumePosition(nextStory.progress, nextStory.duration));
  };

  previous = () => void this.player.seekTo(0);

  stop = () => {
    this.flush();
    this.player.pause();
    if (Platform.OS !== 'web') this.player.clearLockScreenControls();
    this.set({ story: null, queue: [] });
  };

  dismissGoodnight = () => this.set({ goodnight: false });
}

let engine: PlayerEngine | null = null;
export function getEngine() {
  engine ??= new PlayerEngine();
  return engine;
}
