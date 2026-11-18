from pathlib import Path
import subprocess
import unittest


class DashboardRunTests(unittest.TestCase):
    def test_counts_render_survive_stats_updates_and_are_submitted(self):
        script = r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const elements = {
    'stats-grid': {innerHTML: ''},
    'run-count-legitimate': {value: '10'},
};
const context = vm.createContext({document: {
    addEventListener() {}, getElementById: id => elements[id],
}});
vm.runInContext(fs.readFileSync('demo_generator/web/static/app.js', 'utf8') + '\nglobalThis.app = App;', context);
const app = context.app;
app.updateRunControls = () => {};
app.esc = String;
let request;
let error;
app.controlRequest = async (url, body) => { request = {url, body}; };
app.showToast = message => { error = message; };
(async () => {
    app.updateStats({categories: {}});
    assert(elements['stats-grid'].innerHTML.includes('id="run-count-legitimate"'));
    await app.runCategory('legitimate');
    assert.equal(request.url, '/api/run/legitimate');
    assert.equal(request.body.run_count, 10);
    app.updateStats({categories: {legitimate: {pass: 9, fail: 1}}});
    assert(elements['stats-grid'].innerHTML.includes('value="10"'));
    request = null;
    elements['run-count-legitimate'].value = '1.5';
    await app.runCategory('legitimate');
    assert.equal(request, null);
    assert(error.includes('whole number'));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
        subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1],
                       check=True, capture_output=True, text=True)
