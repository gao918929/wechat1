// UTF-8 decoder and SSE parser work without a browser TextDecoder (WeChat JSCore).
class SSEParser {
  constructor(onEvent) {
    this.onEvent = onEvent;
    this.bytes = [];
    this.text = "";
  }
  push(buffer) {
    this.bytes.push(...new Uint8Array(buffer));
    let out = "",
      i = 0;
    while (i < this.bytes.length) {
      const b = this.bytes[i];
      const n =
        b < 128
          ? 1
          : b >= 194 && b < 224
            ? 2
            : b >= 224 && b < 240
              ? 3
              : b >= 240 && b < 245
                ? 4
                : 0;
      if (!n) {
        out += "\uFFFD";
        i++;
        continue;
      }
      if (i + n > this.bytes.length) break;
      let code = b & (n === 1 ? 127 : (1 << (7 - n)) - 1),
        valid = true;
      for (let j = 1; j < n; j++) {
        const next = this.bytes[i + j];
        if ((next & 192) !== 128) valid = false;
        code = (code << 6) | (next & 63);
      }
      if (
        !valid ||
        (n === 2 && code < 128) ||
        (n === 3 && code < 2048) ||
        (n === 4 && code < 65536) ||
        code > 0x10ffff ||
        (code >= 0xd800 && code <= 0xdfff)
      ) {
        out += "\uFFFD";
        i++;
        continue;
      }
      out += String.fromCodePoint(code);
      i += n;
    }
    this.bytes = this.bytes.slice(i);
    this.text += out;
    let match;
    while ((match = /\r?\n\r?\n/.exec(this.text))) {
      const block = this.text.slice(0, match.index);
      this.text = this.text.slice(match.index + match[0].length);
      const event = { type: "message", id: 0, data: "" },
        data = [];
      block.split(/\r?\n/).forEach((line) => {
        if (line.startsWith("event:")) event.type = line.slice(6).trim();
        if (line.startsWith("id:")) event.id = Number(line.slice(3).trim());
        if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
      });
      if (data.length) {
        try {
          event.data = JSON.parse(data.join("\n"));
          this.onEvent(event);
        } catch (_) {}
      }
    }
  }
}
module.exports = { SSEParser };
