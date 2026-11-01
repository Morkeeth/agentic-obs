"""Compile and exercise the production listen block against real loopback sockets.

No OBS launch, auth settings, devices, models, or external hosts are involved.
The full Start() auth/handshake implementation is deliberately not replaced.
"""
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'fork-src/plugins/obs-websocket/src/websocketserver/WebSocketServer.cpp'
UPSTREAM = 'e28f84975984340e84fc4879cfc05741cc0afde1'


def listen_block(text):
    start = text.index('\twebsocketpp::lib::error_code errorCode;')
    end = text.index('\n\tif (errorCode) {', start)
    return text[start:end]


class LoopbackBinding(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        headers = os.environ.get('OBS_WEBSOCKET_HEADERS')
        missing = []
        if not SOURCE.is_file(): missing.append('pinned obs-websocket source checkout')
        if not headers or not all((Path(headers)/name).is_file() for name in ('websocketpp/server.hpp', 'asio.hpp')):
            missing.append('OBS_WEBSOCKET_HEADERS with websocketpp and standalone Asio headers')
        if not shutil.which('clang++'): missing.append('clang++')
        if not missing and subprocess.run(
                ['git', '-C', str(SOURCE.parent), 'cat-file', '-e', UPSTREAM+':src/websocketserver/WebSocketServer.cpp'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            missing.append('pinned obs-websocket baseline Git object')
        if missing:
            reason = 'native prerequisites absent: '+', '.join(missing)+'; see README native OBS checks'
            print('SKIP: '+reason, flush=True)
            raise unittest.SkipTest(reason)
        # Once prerequisites exist, compilation/assertion errors remain real failures.
        cls.tmp = tempfile.TemporaryDirectory(prefix='obs-loopback-fixture-')
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.original = subprocess.check_output(
            ['git', '-C', str(SOURCE.parent), 'show', UPSTREAM + ':src/websocketserver/WebSocketServer.cpp'], text=True)
        cls.current = SOURCE.read_text()
        cls.binaries = {}
        for name, text in [('baseline', cls.original), ('fixed', cls.current)]:
            cpp = Path(cls.tmp.name) / (name + '.cpp')
            cpp.write_text('''#define ASIO_STANDALONE
#include <websocketpp/config/asio_no_tls.hpp>
#include <websocketpp/server.hpp>
#include <atomic>
#include <iostream>
#define LOG_INFO 0
#define blog(...) ((void)0)
using Server = websocketpp::server<websocketpp::config::asio>;
struct Config { bool Ipv4Only; std::atomic<unsigned short> ServerPort{0}; };
websocketpp::lib::error_code bind_production(Server &_server, Config *conf) {
''' + listen_block(text) + '''\nreturn errorCode; }
int main(int argc, char **argv) {
 Config conf; conf.Ipv4Only = argc > 1 && argv[1][0] == '1';
 Server first; first.init_asio(); auto error = bind_production(first, &conf);
 if (error) { std::cerr << error.message(); return 2; }
 auto endpoint = first.get_local_endpoint(error);
 std::cout << endpoint.address().to_string() << ':' << endpoint.port() << std::endl;
 if (endpoint.address().to_string() != "127.0.0.1") return 3;
 // Real TCP connection to the owned, kernel-bound ephemeral listener.
 asio::io_context io; asio::ip::tcp::socket client(io); client.connect(endpoint, error);
 if (error) return 4;
 // Occupied loopback ports must fail; never retry on another interface or port.
 conf.ServerPort = endpoint.port(); Server second; second.init_asio();
 error = bind_production(second, &conf);
 if (!error) return 5;
 client.close(); first.stop_listening();
 return 0;
}
''')
            binary = Path(cls.tmp.name) / name
            subprocess.run(['clang++', '-std=c++17', '-pthread', '-I'+headers, str(cpp), '-o', str(binary)], check=True, capture_output=True, text=True)
            cls.binaries[name] = binary

    def test_original_listener_fails_loopback_contract_both_preferences(self):
        for value in ('0', '1'):
            with self.subTest(ipv4_only=value):
                p = subprocess.run([str(self.binaries['baseline']), value], capture_output=True, text=True)
                print('RED original ipv4_only='+value+': '+p.stdout.strip(), flush=True)
                self.assertEqual(p.returncode, 3, p.stderr)

    def test_fixed_listener_and_owned_tcp_connection_both_preferences(self):
        for value in ('0', '1'):
            with self.subTest(ipv4_only=value):
                p = subprocess.run([str(self.binaries['fixed']), value], capture_output=True, text=True)
                print('GREEN fixed ipv4_only='+value+': '+p.stdout.strip(), flush=True)
                self.assertEqual(p.returncode, 0, p.stderr)

    def test_only_listener_and_address_log_changed_not_authentication(self):
        before = self.original.replace(listen_block(self.original), '<LISTEN>')
        after = self.current.replace(listen_block(self.current), '<LISTEN>')
        after = after.replace('conf->ServerPort.load(), "127.0.0.1");',
                              'conf->ServerPort.load(), Utils::Platform::GetLocalAddress().c_str());')
        self.assertEqual(before, after)

if __name__ == '__main__':
    unittest.main()
