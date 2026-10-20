#!/usr/bin/env python3
"""Record cloud-runner DNS and verified mirror downloads without device writes."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "network-probe-report.json"
GITEE = "https://gitee.com/zaomi/android_device_oneplus_infiniti-AERA/raw/aera-16.0/vendor/aera-plugins/"
GITHUB = "https://raw.githubusercontent.com/cvhhji/android_device_oneplus_infiniti-AERA/aera-16.0/vendor/aera-plugins/"


def region():
    value = subprocess.run(['curl', '--disable', '--fail', '--silent', '--show-error',
        '--max-time', '15', 'https://www.cloudflare.com/cdn-cgi/trace'],
        capture_output=True, text=True, timeout=20)
    fields = dict(line.split('=', 1) for line in value.stdout.splitlines() if '=' in line)
    return {key: fields.get(key) for key in ('loc', 'colo', 'warp', 'http')}


def dns_probe(server):
    name = 'raw.githubusercontent.com'
    ident = secrets.randbelow(65536)
    encoded = b''.join(bytes([len(label)]) + label.encode() for label in name.split('.')) + b'\0'
    packet = struct.pack('!6H', ident, 0x100, 1, 0, 0, 0) + encoded + struct.pack('!2H', 1, 1)
    start = time.monotonic()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
            connection.settimeout(3)
            connection.sendto(packet, (server, 53))
            reply, peer = connection.recvfrom(4096)
        header = struct.unpack('!6H', reply[:12])
        good = header[0] == ident and bool(header[1] & 0x8000) and (header[1] & 15) == 0 and header[3] > 0
        return {'server': server, 'success': good, 'answer_count': header[3],
                'elapsed_seconds': round(time.monotonic() - start, 3)}
    except (OSError, struct.error) as error:
        return {'server': server, 'success': False, 'error': str(error),
                'elapsed_seconds': round(time.monotonic() - start, 3)}


def download(task):
    with tempfile.TemporaryDirectory(prefix='aera-network-') as temporary:
        target = Path(temporary) / 'payload'
        result = subprocess.run(['curl', '--disable', '--fail', '--location', '--ipv4',
            '--silent', '--show-error', '--connect-timeout', '10', '--max-time', '60',
            # Redirect responses can be larger than a 129-byte signature.
            # The final object must still match the exact size and digest.
            '--max-filesize', str(max(65536, task['size'] + 1)), '--output', str(target),
            '--write-out', '%{json}', task['url']], capture_output=True, text=True, timeout=70)
        try:
            detail = json.loads(result.stdout)
        except json.JSONDecodeError:
            detail = {}
        data = target.read_bytes() if target.is_file() else b''
        digest = hashlib.sha256(data).hexdigest()
        verified = result.returncode == 0 and len(data) == task['size'] and digest == task['sha256']
        item = {**task, 'curl_exit_code': result.returncode, 'verified': verified,
                'received_size': len(data), 'received_sha256': digest,
                'error': result.stderr.strip(),
                'transport': {key: detail.get(key) for key in
                    ('http_code', 'time_namelookup', 'time_connect', 'time_appconnect',
                     'time_total', 'speed_download', 'num_redirects', 'ssl_verify_result')}}
        print(json.dumps({'source': task['source'], 'file': task['file'],
            'verified': verified, 'seconds': detail.get('time_total'),
            'http_code': detail.get('http_code')}, ensure_ascii=True), flush=True)
        return item


def main():
    plugins = ROOT / 'vendor/aera-plugins'
    source_files = [plugins / 'catalog.json', plugins / 'catalog.json.sig']
    candidates = sorted(plugins.glob('*.part0'))
    if not candidates:
        raise SystemExit('No mirrored plugin part was checked out')
    source_files.append(candidates[0])
    tasks = []
    for source in source_files:
        data = source.read_bytes()
        for label, base in (('gitee', GITEE), ('github-mirror', GITHUB)):
            tasks.append({'source': label, 'file': source.name, 'url': base + source.name,
                'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    tasks.append({'source': 'github-official', 'file': 'browser-runtime-1.5.4.xz',
        'url': 'https://github.com/AERA-Plugins/browser/releases/download/v1.5.4/runtime.xz',
        'size': 40966036,
        'sha256': '4e3941bd2bcbcc53e4d1bdc7641e7d7c7b16b848b8ba21bb934119118b37f197'})
    location = region()
    print(json.dumps({'cloudflare_network_observation': location}), flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(download, tasks))
    with ThreadPoolExecutor(max_workers=4) as pool:
        dns = list(pool.map(dns_probe, ('223.5.5.5', '119.29.29.29', '1.1.1.1', '8.8.8.8')))
    report = {'epoch': time.time(), 'github_run_id': os.environ.get('GITHUB_RUN_ID'),
        'network_observation': location, 'downloads': results, 'dns': dns,
        'scope': 'GitHub-hosted Linux IPv4 transport and file integrity. Does not prove overseas phone Wi-Fi, Bionic resolver, IPv6-only, or every country.'}
    OUTPUT.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    Path(os.environ['GITHUB_STEP_SUMMARY']).write_text(
        '# AERA network probe\n\n' + json.dumps(location) + '\n\n' +
        '\n'.join(f'- {r["source"]} / {r["file"]}: verified={r["verified"]}, HTTP {r["transport"].get("http_code")}' for r in results) + '\n',
        encoding='utf-8')


if __name__ == '__main__':
    main()
