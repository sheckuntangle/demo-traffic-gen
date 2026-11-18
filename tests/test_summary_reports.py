from pathlib import Path
import subprocess
import unittest


class SummaryReportTests(unittest.TestCase):
    def test_report_escapes_content_and_copy_includes_collapsed_details(self):
        script = r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const panel = {children: []};
const context = vm.createContext({
    navigator: {},
    document: {addEventListener() {}, getElementById: () => panel,
        createElement: () => ({textContent: '', get innerHTML() {
            return this.textContent.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
        }}),
    },
});
vm.runInContext(fs.readFileSync('demo_generator/web/static/app.js', 'utf8') + '\nglobalThis.app = App;', context);
const app = context.app;
const entry = {category: 'SCHEDULE SUMMARY', timestamp: '2026-11-18T20:00:00Z',
    message: 'FULL REPORT\nApp Control 3 9 0\nHidden client details',
    report: {outcome: '<img src=x>', note: 'Pass/fail uses policy expectations.',
        totals: {clients: 1, executions: 3, passed: 9, failed: 0, cancelled: 1, errors: 0},
        clients: [{name: '<script>evil</script>', source_ip: '192.168.77.50', sections: [
            {label: 'App Control', executions: 3, passed: 9, failed: 0, cancelled: 1, errors: 0, seconds: 119.9},
        ]}],
    },
};
const html = app.renderRunReport(entry);
assert(html.includes('Schedule summary'));
assert(html.includes('<details'));
assert(html.includes('App Control'));
assert(html.includes('192.168.77.50'));
assert(html.includes('2m 0s'));
assert(html.includes('&lt;script&gt;evil&lt;/script&gt;'));
assert(!html.includes('<img'));
assert(!html.includes('<script>'));
panel.children = [{innerText: 'Normal log'}, {dataset: {copyText: entry.message}, innerText: 'Collapsed report'}];
let copied;
app._fallbackCopy = value => { copied = value; };
app.copyLog();
assert(copied.includes('Normal log'));
assert(copied.includes('Hidden client details'));
assert(copied.includes('App Control 3 9 0'));
assert(!copied.includes('Collapsed report'));
'''
        subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1],
                       check=True, capture_output=True, text=True)
