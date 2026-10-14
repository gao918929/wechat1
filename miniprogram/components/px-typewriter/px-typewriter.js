// RPG-style typewriter text: reveals `text` a few characters at a time, then blinks ▼.
//   <px-typewriter text="{{summary}}" speed="30" />
Component({
  properties: {
    text: { type: String, value: '' },
    speed: { type: Number, value: 30 },     // ms per step
    step: { type: Number, value: 2 },       // characters per step
    cursor: { type: Boolean, value: true },
    instant: { type: Boolean, value: false }
  },
  data: { shown: '', done: false },
  observers: {
    text(t) { this.start(t); }
  },
  lifetimes: {
    detached() { this.stop(); }
  },
  methods: {
    start(t) {
      this.stop();
      const chars = Array.from(t || '');
      if (this.data.instant || !chars.length) {
        this.setData({ shown: chars.join(''), done: true });
        return;
      }
      let i = 0;
      this.setData({ shown: '', done: false });
      this.timer = setInterval(() => {
        i = Math.min(chars.length, i + Math.max(1, this.data.step));
        this.setData({ shown: chars.slice(0, i).join(''), done: i >= chars.length });
        if (i >= chars.length) this.stop();
      }, Math.max(10, this.data.speed));
    },
    stop() {
      if (this.timer) clearInterval(this.timer);
      this.timer = null;
    },
    finish() {
      this.stop();
      this.setData({ shown: this.data.text, done: true });
    }
  }
});
