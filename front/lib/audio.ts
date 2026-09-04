export type AudioFrameHandler = (frame: ArrayBuffer, sequence: number) => void;

type AudioContextConstructor = new (options?: AudioContextOptions) => AudioContext;

export class MicrophoneCaptureError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = 'MicrophoneCaptureError';
    this.code = code;
  }
}

export class Pcm16Capture {
  private stream: MediaStream | null = null;
  private context: AudioContext | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private pending = new Float32Array(0);
  private sequence = 0;

  get hasPcmPipeline() {
    return Boolean(this.processor);
  }

  async start(onFrame: AudioFrameHandler) {
    if (this.processor) return;
    if (typeof window === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      throw new MicrophoneCaptureError('unsupported', '이 브라우저에서는 마이크 녹음을 사용할 수 없습니다. Chrome 또는 Edge에서 다시 시도해 주세요.');
    }

    // Keep the constraints permissive. Some browsers reject exact audio constraints
    // even after the user has already granted microphone permission.
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: { ideal: 1 },
        echoCancellation: { ideal: true },
        noiseSuppression: { ideal: true },
        autoGainControl: { ideal: true },
      },
      video: false,
    });

    // Capturing the stream is the primary action. PCM processing is best effort so
    // WebView/browser AudioContext differences do not turn a granted permission
    // into a failed recording toggle.
    try {
      const contextConstructor = (window.AudioContext ?? (window as Window & { webkitAudioContext?: AudioContextConstructor }).webkitAudioContext) as AudioContextConstructor | undefined;
      if (!contextConstructor) return;

      try {
        this.context = new contextConstructor({ sampleRate: 16000 });
      } catch {
        // A few devices do not accept 16 kHz at construction time. The browser can
        // still expose the microphone through its native sample rate.
        this.context = new contextConstructor();
      }

      this.source = this.context.createMediaStreamSource(this.stream);
      this.processor = this.context.createScriptProcessor(3200, 1, 1);
      this.processor.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        const merged = new Float32Array(this.pending.length + input.length);
        merged.set(this.pending);
        merged.set(input, this.pending.length);
        let offset = 0;
        // The wire contract is 100 ms at 16 kHz: 1,600 mono samples = 3,200 bytes.
        while (merged.length - offset >= 1600) {
          const frame = merged.subarray(offset, offset + 1600);
          const payload = new ArrayBuffer(3204);
          const view = new DataView(payload);
          view.setUint32(0, this.sequence, false);
          for (let index = 0; index < frame.length; index += 1) {
            const sample = Math.max(-1, Math.min(1, frame[index]));
            view.setInt16(4 + index * 2, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
          }
          onFrame(payload, this.sequence);
          this.sequence += 1;
          offset += 1600;
        }
        this.pending = merged.slice(offset);
      };
      this.source.connect(this.processor);
      this.processor.connect(this.context.destination);
      await this.context.resume();
    } catch (error) {
      // Do not discard a successfully granted MediaStream just because the optional
      // PCM pipeline is unavailable in this browser.
      console.warn('PCM audio pipeline unavailable; keeping microphone stream active.', error);
      this.processor?.disconnect();
      this.source?.disconnect();
      if (this.context && this.context.state !== 'closed') void this.context.close();
      this.processor = null;
      this.source = null;
      this.context = null;
    }
  }

  stop() {
    this.processor?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.context && this.context.state !== 'closed') void this.context.close();
    this.processor = null;
    this.source = null;
    this.stream = null;
    this.context = null;
    this.pending = new Float32Array(0);
  }
}
