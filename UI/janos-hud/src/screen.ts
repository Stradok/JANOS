// Screen sharing: getDisplayMedia -> a JPEG every ~1.5 s -> POST /screen/frame. Frames are never kept here
// (no state, no storage) and the server holds only the latest one, in RAM.
import { sendScreenFrame, clearScreen, AuthError } from './api';

const EVERY_MS = 1500;
const MAX_SIDE = 1280;

declare class ImageCapture { constructor(t: MediaStreamTrack); grabFrame(): Promise<ImageBitmap> }

/** Ask the portal for a screen and start pushing frames. `onStop(reason)` fires once on any end; call the returned stop() to end it. */
export async function startScreenShare(onStop: (reason: 'ended' | 'forbidden' | 'auth' | 'user') => void): Promise<() => void> {
  const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 2, cursor: 'always' } as MediaTrackConstraints, audio: false });
  const track = stream.getVideoTracks()[0];
  const cap = typeof ImageCapture !== 'undefined' ? new ImageCapture(track) : null;
  let video: HTMLVideoElement | null = null;
  if (!cap) {   // fallback: a hidden <video> (only updates while the window is visible)
    video = document.createElement('video');
    video.muted = true; video.srcObject = stream;
    void video.play().catch(() => { /* retried by the next tick's readyState check */ });
  }
  const canvas = document.createElement('canvas');
  let busy = false;
  let done = false;

  const stop = (reason: 'ended' | 'forbidden' | 'auth' | 'user') => {
    if (done) return;
    done = true;
    clearInterval(timer);
    track.removeEventListener('ended', onEnded);
    stream.getTracks().forEach((t) => t.stop());
    if (video) video.srcObject = null;
    void clearScreen();
    onStop(reason);
  };
  const onEnded = () => stop('ended');
  track.addEventListener('ended', onEnded);

  const tick = async () => {
    if (busy || done) return;   // skip while the previous POST is in flight
    busy = true;
    try {
      let src: CanvasImageSource, sw: number, sh: number;
      if (cap) { const b = await cap.grabFrame(); src = b; sw = b.width; sh = b.height; }
      else if (video && video.readyState >= 2) { src = video; sw = video.videoWidth; sh = video.videoHeight; }
      else return;
      if (!sw || !sh) return;
      const k = Math.min(1, MAX_SIDE / Math.max(sw, sh));
      canvas.width = Math.round(sw * k); canvas.height = Math.round(sh * k);
      canvas.getContext('2d')!.drawImage(src, 0, 0, canvas.width, canvas.height);
      if ('close' in src) (src as ImageBitmap).close();
      const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/jpeg', 0.6));
      if (!blob || done) return;
      const s = track.getSettings();   // real screen pixels, so the server can convert coordinates
      const status = await sendScreenFrame(blob, s.width ?? sw, s.height ?? sh);
      if (status === 403) stop('forbidden');
    } catch (e) {
      if (e instanceof AuthError) stop('auth');   // other errors: drop this frame, try the next tick
    } finally { busy = false; }
  };
  const timer = window.setInterval(() => void tick(), EVERY_MS);
  void tick();
  return () => stop('user');
}
