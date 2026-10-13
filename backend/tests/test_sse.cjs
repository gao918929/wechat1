const assert = require("node:assert/strict");
const { SSEParser } = require("../../miniprogram/utils/sse.js");
const text =
  'id: 12\r\nevent: day\r\ndata: {"name":"番茄🥬"}\r\n\r\nid: 13\nevent: complete\ndata: {"ok":true}\n\n';
const bytes = Buffer.from(text, "utf8");
for (let size = 1; size < bytes.length; size++) {
  const events = [],
    parser = new SSEParser((e) => events.push(e));
  for (let i = 0; i < bytes.length; i += size)
    parser.push(new Uint8Array(bytes.subarray(i, i + size)).buffer);
  assert.equal(events.length, 2);
  assert.equal(events[0].data.name, "番茄🥬");
  assert.equal(events[1].id, 13);
}
console.log("SSE decoder: all UTF-8/CRLF chunk boundaries passed");
