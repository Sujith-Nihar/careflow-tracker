// Installed as a Playwright init script, so it runs before any page code.
//
// Replaces the microphone with an AudioContext destination stream. Vogent's Web
// SDK calls getUserMedia like normal and receives a live MediaStream; we decide
// what goes into it. This is what makes a scripted caller a real voice call
// rather than a transcript injection.
(() => {
  const context = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
  const destination = context.createMediaStreamDestination();

  // Near-silence keeps the track alive between lines. A completely idle track can
  // be treated as a dead device and torn down by the browser.
  const floor = context.createGain();
  floor.gain.value = 0.0005;
  const noise = context.createOscillator();
  noise.frequency.value = 50;
  noise.connect(floor).connect(destination);
  noise.start();

  window.__fakeMic = {
    context,
    stream: destination.stream,
    /** Fetch, decode and play a clip; resolves when playback ends. */
    async play(url) {
      if (context.state === "suspended") await context.resume();
      const buffer = await fetch(url).then((r) => r.arrayBuffer());
      const audio = await context.decodeAudioData(buffer);
      const source = context.createBufferSource();
      source.buffer = audio;
      source.connect(destination);
      return new Promise((resolve) => {
        source.onended = () => resolve(audio.duration);
        source.start();
      });
    },
  };

  const fake = async () => destination.stream;
  if (!navigator.mediaDevices) navigator.mediaDevices = {};
  navigator.mediaDevices.getUserMedia = fake;
  navigator.getUserMedia = (_c, ok) => ok(destination.stream);
})();
