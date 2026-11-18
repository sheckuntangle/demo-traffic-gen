"""Exercise log batching and retention using the browser controller in Node."""

from pathlib import Path
import subprocess
import unittest


class LogRenderingTests(unittest.TestCase):
    def test_history_yields_batches_preserves_order_and_cancels_on_clear(self):
        script = r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let layoutReads = 0;
let nextTimer = 0;
const timers = new Map();
function node(fragment = false) {
    return {
        fragment, children: [], innerHTML: '',
        appendChild(child) {
            if (child.fragment) this.children.push(...child.children);
            else this.children.push(child);
        },
        removeChild(child) { assert.equal(child, this.children.shift()); },
        get firstChild() { return this.children[0]; },
        get scrollHeight() { layoutReads++; return this.children.length; },
    };
}
const panel = node();
Object.defineProperty(panel, 'innerHTML', {set() { this.children = []; }});
const toggle = {checked: true};
const context = vm.createContext({
    document: {
        addEventListener() {}, createElement: () => node(),
        createDocumentFragment: () => node(true),
        getElementById: id => id === 'log-panel' ? panel : toggle,
    },
    setTimeout(fn) { timers.set(++nextTimer, fn); return nextTimer; },
    clearTimeout(id) { timers.delete(id); },
});
vm.runInContext(fs.readFileSync('demo_generator/web/static/app.js', 'utf8') + '\nglobalThis.app = App;', context);
const app = context.app;
app.esc = value => String(value);
const events = [];
app.updateStatus = () => events.push('status');
app.updateStats = () => events.push('stats');
app.receiveScheduler = () => events.push('scheduler');
const logs = Array.from({length: 10000}, (_, i) => ({message: `entry-${i}`}));
app.handleMessage({type: 'snapshot', data: {logs}});
assert.deepEqual(events, ['status', 'stats', 'scheduler']);
assert.equal(panel.children.length, 0); // Snapshot handling never renders synchronously.
function tick() {
    const [id, callback] = timers.entries().next().value;
    timers.delete(id);
    callback();
}
tick();
assert.equal(panel.children.length, 100);
assert.equal(layoutReads, 1);
while (timers.size) tick();
assert.equal(panel.children.length, 10000);
assert.equal(layoutReads, 100); // One layout read per batch, rather than 10,000.
assert(panel.children[0].innerHTML.endsWith('entry-0'));
assert(panel.children[9999].innerHTML.endsWith('entry-9999'));
app.appendLog({message: 'live'});
tick();
assert.equal(panel.children.length, 10000);
assert(panel.children[0].innerHTML.endsWith('entry-1'));
assert(panel.children[9999].innerHTML.endsWith('live'));
toggle.checked = false;
const readsBefore = layoutReads;
app.appendLog({message: 'no autoscroll'});
tick();
assert.equal(layoutReads, readsBefore);
app.appendLogs(logs);
app.clearLog();
assert.equal(timers.size, 0);
assert.equal(app.pendingLogs.length, 0);
assert.equal(panel.children.length, 0);
app.appendLog({message: 'after clear'});
tick();
assert.equal(panel.children.length, 1);
'''
        subprocess.run(
            ["node", "-e", script], cwd=Path(__file__).resolve().parents[1],
            check=True, capture_output=True, text=True,
        )
