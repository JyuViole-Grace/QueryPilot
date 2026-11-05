// Unit tests for the browser UI logic, run by tests/test_ui.py with Node (skipped if Node is missing).
const fs = require("fs");
const path = require("path");
const assert = require("assert");

class FakeNode {
  constructor(tag) { this.tag = tag; this.children = []; this.attrs = {}; this.className = ""; this._text = ""; }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent ?? c).join(""); }
  setAttribute(k, v) { this.attrs[k] = v; }
  append(...xs) { for (const x of xs) this.children.push(typeof x === "string" ? { textContent: x, text: true } : x); }
  find(tag, out = []) { if (this.tag === tag) out.push(this); for (const c of this.children) if (c.find) c.find(tag, out); return out; }
}
global.document = { createElement: t => new FakeNode(t), createTextNode: s => ({ textContent: s, text: true }), getElementById: () => null };

const html = fs.readFileSync(path.join(__dirname, "..", "app", "static", "index.html"), "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const ui = new Function(script + ";return {tokenizeSql,formatCell,errorMessage,renderResult,renderTable};")();

const toks = ui.tokenizeSql("SELECT name, COUNT(*) AS n -- c\nFROM t WHERE city = 'O''x' AND price > 10.5");
assert.deepStrictEqual(
  toks.filter(t => t[0] !== "text").map(t => t[0] + ":" + t[1]),
  ["kw:SELECT", "kw:COUNT", "kw:AS", "com:-- c", "kw:FROM", "kw:WHERE", "str:'O''x'", "kw:AND", "num:10.5"],
);
assert.strictEqual(toks.map(t => t[1]).join(""), "SELECT name, COUNT(*) AS n -- c\nFROM t WHERE city = 'O''x' AND price > 10.5");

assert.deepStrictEqual(ui.formatCell(null), { text: "NULL", cls: "null" });
assert.deepStrictEqual(ui.formatCell(4.255), { text: "4.26", cls: "num" });
assert.deepStrictEqual(ui.formatCell(12), { text: "12", cls: "num" });
assert.deepStrictEqual(ui.formatCell("<img src=x onerror=alert(1)>"), { text: "<img src=x onerror=alert(1)>", cls: "" });

assert.strictEqual(ui.errorMessage(422, { detail: [{ msg: "Field required" }, { msg: "Too short" }] }).detail, "Field required; Too short");
assert.strictEqual(ui.errorMessage(400, { detail: "Model not enabled" }).detail, "Model not enabled");
assert.strictEqual(ui.errorMessage(500, null).detail, "Unexpected error.");

const nodes = ui.renderResult({
  sql: "SELECT '<script>alert(1)</script>' AS x", columns: ["name", "n"],
  rows: [["<b>Ann</b>", 3], [null, 4.5]], truncated: true, execution_time_seconds: 0.0123, quality_repair_attempts: 2,
});
assert.strictEqual(nodes.length, 3);
const cells = nodes[2].find("table")[0].find("td");
assert.strictEqual(cells.length, 4);
assert.strictEqual(cells[0].textContent, "<b>Ann</b>");   // data is shown as text, never as markup
assert.strictEqual(cells[2].textContent, "NULL");
assert.strictEqual(cells[3].textContent, "4.5");
assert(cells[1].className.includes("num") && cells[2].className.includes("null"));
const meta = nodes[0].textContent;
assert(meta.includes("Rows 2") && meta.includes("12.3 ms") && meta.includes("Self-corrected 2×") && meta.includes("Truncated"));
assert(ui.renderTable(["a"], []).textContent.includes("The query returned no rows."));
console.log("ok");
