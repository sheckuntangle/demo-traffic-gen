from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from demo_generator.categories.app_control import AppControl
from demo_generator.categories.ip_reputation import IpReputation
from demo_generator.categories.url_reputation import UrlReputation
from demo_generator.docker_clients import DockerClientPool
from demo_generator.engine import Engine
from demo_generator.stats import Stats


class ClientAssignmentTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_targets_use_selected_clients_and_keep_expected_actions(self):
        for cls, field, destination in ((IpReputation, "ip", "192.0.2.1"),
                                        (UrlReputation, "url", "https://example.com")):
            with self.subTest(category=cls.name):
                seen = []
                clients = []
                for ip in ("192.168.77.50", "192.168.77.51"):
                    async def run(category, config, source=ip):
                        for target in config["categories"][category.name]["targets"]:
                            seen.append((source, target[field], target["expected"]))
                        return []
                    clients.append(SimpleNamespace(profile=SimpleNamespace(name=ip), macvlan_ip=ip, run_category=run))
                targets = [{field: destination, "client_ip": clients[0].macvlan_ip, "expected": "block"},
                           {field: destination, "client_ip": clients[1].macvlan_ip, "expected": "alert"}]
                config = {"categories": {cls.name: {"targets": targets}}}
                engine = Engine(config, Mock(), Stats(), pool=SimpleNamespace(get_clients=lambda: clients))
                await engine._run_categories_on_clients([cls()])
                self.assertCountEqual(seen, [("192.168.77.50", destination, "block"),
                                             ("192.168.77.51", destination, "alert")])
                self.assertEqual(config["categories"][cls.name]["targets"], targets)

    async def test_unavailable_assignment_never_dispatches_to_another_client(self):
        for docker in (False, True):
            with self.subTest(docker=docker):
                client = SimpleNamespace(profile=SimpleNamespace(name="client"), run_category=AsyncMock())
                if docker:
                    client.macvlan_ip = "192.168.77.50"
                engine = Engine({"categories": {"ip_reputation": {"targets": [
                    {"ip": "192.0.2.1", "client_ip": "192.168.77.99"}]}}}, Mock(), Stats(),
                    pool=SimpleNamespace(get_clients=lambda: [client]))
                engine._run_category_on_client = AsyncMock()
                with self.assertRaisesRegex(ValueError, "192.168.77.99.*unavailable"):
                    await engine._run_categories_on_clients([AppControl(), IpReputation()])
                engine._run_category_on_client.assert_not_awaited()
                self.assertEqual(engine._active_tasks, [])

    def test_docker_ip_generation_matches_sequential_ipv4_range(self):
        self.assertEqual(DockerClientPool._generate_ips("192.168.77.254", 3),
                         ["192.168.77.254", "192.168.77.255", "192.168.78.0"])

    def test_dropdowns_are_visible_and_preserve_unavailable_assignments(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const context = vm.createContext({document: {addEventListener() {}, createElement: () => ({
    textContent: '', get innerHTML() {return this.textContent.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');},
})}});
vm.runInContext(fs.readFileSync('demo_generator/web/static/app.js', 'utf8') + '\nglobalThis.app=App; globalThis.schemas=CATEGORY_SCHEMAS;', context);
const app = context.app;
app.config.docker = {enabled: false, start_ip: '192.168.77.50', client_count: 3};
for (const category of ['ip_reputation', 'url_reputation']) {
    const html = app.renderTargetTable(category, 'targets', context.schemas[category][0].fields, [{client_ip:'192.168.77.51'}]);
    assert(html.includes('Client IP'));
    assert(html.includes('data-field="client_ip"'));
    assert(html.includes('value="192.168.77.51" selected'));
}
assert(app._clientIpSelect('192.168.77.51').includes('disabled'));
app.config.docker.enabled = true;
assert(!app._clientIpSelect('192.168.77.51').includes('disabled'));
assert.equal(JSON.stringify(app._getDockerClientIps()), JSON.stringify(['192.168.77.50','192.168.77.51','192.168.77.52']));
assert(app._clientIpSelect('192.168.77.99').includes('Unavailable: 192.168.77.99'));
assert(app._clientIpSelect('192.168.77.99').includes('value="192.168.77.99" selected'));
app.config.docker = {start_ip:'192.168.77.254', client_count:3};
assert.equal(JSON.stringify(app._getDockerClientIps()), JSON.stringify(['192.168.77.254','192.168.77.255','192.168.78.0']));
app.config.docker.start_ip = '192.168.77.999';
assert.equal(app._getDockerClientIps().length, 0);
'''
        subprocess.run(["node", "-e", script], cwd=Path(__file__).resolve().parents[1],
                       check=True, capture_output=True, text=True)
