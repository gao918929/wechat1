const fs = require("node:fs"),
  path = require("node:path"),
  vm = require("node:vm"),
  assert = require("node:assert/strict");
const root = path.join(__dirname, "..", "miniprogram");
const config = JSON.parse(fs.readFileSync(path.join(root, "app.json"), "utf8"));
for (const route of config.pages) {
  for (const ext of ["js", "json", "wxml"])
    assert.ok(
      fs.existsSync(path.join(root, route + "." + ext)),
      route + "." + ext + " missing",
    );
  const source = fs.readFileSync(path.join(root, route + ".js"), "utf8");
  new vm.Script(source);
  JSON.parse(fs.readFileSync(path.join(root, route + ".json"), "utf8"));
  let page;
  const api = new Proxy(
    {},
    {
      get: (_, key) =>
        key === "guard"
          ? (f) => f
          : () => (key === "base" ? "http://localhost:8000" : ""),
    },
  );
  vm.runInNewContext(source, {
    Page: (p) => (page = p),
    require: (p) => (p.includes("sse") ? { SSEParser: class {} } : api),
    Date,
    Math,
    JSON,
    Number,
    Set,
    console,
  });
  const wxml = fs.readFileSync(path.join(root, route + ".wxml"), "utf8");
  for (const m of wxml.matchAll(
    /(?:bind|catch)(?:tap|input|change|submit)="([A-Za-z0-9_]+)"/g,
  ))
    assert.equal(
      typeof page[m[1]],
      "function",
      route + ": missing handler " + m[1],
    );
  assert.ok(!/<br\s*\//.test(wxml), route + ": unsupported HTML br component");
}
console.log(
  `Mini-program: ${config.pages.length} pages, JSON, JS syntax and event handlers passed (not a WeChat compiler/device test)`,
);
