#!/usr/bin/env python3
"""Re-sign an existing cloud image's installer without rebuilding Android."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7


IMAGE = 'AERA-infiniti-aera-17.0-recovery.img'
PACKAGE = 'AERA-infiniti-aera-17.0-recovery.zip'
ENTRIES = ['META-INF/com/google/android/update-binary',
           'META-INF/com/google/android/aera-installer']
VENDOR = '7b4e41362938ee3498fc0e8a4f3e0528bf320efd'
SIGNER_BLOBS = {'sign_zip.sh': '01a2f90f6ea2d33d4a87c43f42e5abc3a2319de7',
                'zipsigner-3.0.jar': 'eae3d9434bd0a4e35716c09063056c73d34a5a82'}


def api(path):
    return json.loads(subprocess.check_output(['gh', 'api', path]))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch(url, path):
    with urllib.request.urlopen(url, timeout=180) as response, path.open('wb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def verify_whole_file(path, work):
    """Verify CMS content; callers separately pin the trusted signer identity."""
    raw = path.read_bytes()
    start, marker, comment = struct.unpack('<H2sH', raw[-6:])
    if marker != b'\xff\xff' or start < 7 or start > comment:
        raise RuntimeError('Missing recovery whole-file signature')
    if raw[-comment-22:-comment-18] != b'PK\x05\x06':
        raise RuntimeError('Invalid signed ZIP end record')
    signature = raw[-start:-6]
    certificates = pkcs7.load_der_pkcs7_certificates(signature)
    if not certificates:
        raise RuntimeError('Signature has no signer certificate')
    (work / 'signature.der').write_bytes(signature)
    (work / 'signed-content.bin').write_bytes(raw[:-comment-2])
    # Recovery trusts a pinned package key, rather than a web PKI chain.
    # -noverify disables CMS chain building only: content verification remains
    # mandatory, and the exact certificate set is compared with the original.
    subprocess.run(['openssl', 'cms', '-verify', '-binary', '-inform', 'DER',
                    '-in', str(work / 'signature.der'), '-content',
                    str(work / 'signed-content.bin'), '-noverify',
                    '-out', os.devnull], check=True)
    return sorted(cert.fingerprint(hashes.SHA256()).hex() for cert in certificates)


def main():
    repository, source_tag, source_commit, output_tag, destination = sys.argv[1:]
    if not re.fullmatch(r'[0-9a-f]{40}', source_commit):
        raise SystemExit('An exact source commit is required')
    if not re.fullmatch(r'AERA-17\.0-\d+-[0-9a-f]{8}', source_tag):
        raise SystemExit('Invalid source release tag')
    if output_tag != source_tag + '-slotfix1':
        raise SystemExit('Use a separate, explicit installer revision tag')
    if api(f'repos/{repository}/git/ref/tags/{source_tag}')['object']['sha'] != source_commit:
        raise SystemExit('Source release tag does not identify the expected image source')
    metadata = api(f'repos/{repository}/releases/tags/{source_tag}')
    destination = Path(destination)
    destination.mkdir(parents=True)
    assets = {item['name']: item for item in metadata['assets']}
    with tempfile.TemporaryDirectory() as temporary:
        temporary = Path(temporary)
        for name in (IMAGE, PACKAGE, 'SHA256SUMS', 'catalog.json'):
            path = temporary / name
            fetch(assets[name]['browser_download_url'], path)
            if path.stat().st_size != assets[name]['size'] or \
                    'sha256:' + digest(path) != assets[name]['digest']:
                raise RuntimeError('Downloaded release asset mismatch: ' + name)
        for line in (temporary / 'SHA256SUMS').read_text().splitlines():
            expected, name = line.split(maxsplit=1)
            if digest(temporary / name.lstrip('*')) != expected:
                raise RuntimeError('Source SHA256SUMS mismatch')
        original = temporary / PACKAGE
        original_signers = verify_whole_file(original, temporary)
        source_image_hash = digest(temporary / IMAGE)
        if (temporary / IMAGE).stat().st_size != 104857600:
            raise RuntimeError('Source image is not exactly 100 MiB')
        with zipfile.ZipFile(original) as archive:
            if len(archive.namelist()) != len(set(archive.namelist())):
                raise RuntimeError('Duplicate installer entries')
            if hashlib.sha256(archive.read('recovery.img')).hexdigest() != source_image_hash:
                raise RuntimeError('Original ZIP image differs from the release image')
            root = temporary / 'installer'
            for name in ENTRIES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(archive.read(name))
            subprocess.run([sys.executable, str(Path(__file__).with_name('patch_aera_installer.py')),
                            str(root)], check=True)
            policies = []
            for name in ENTRIES:
                text = (root / name).read_text()
                subprocess.run(['bash', '-n', str(root / name)], check=True)
                begin = text.index('# infiniti: update only the recovery slot that actually booted.')
                end = text.index('\n# vendor_boot as recovery - flash both slots and return\n', begin)
                policy = text[begin:end]
                if 'for slot in _a _b' in policy or 'Installing AERA to slot $tmp only...' not in policy:
                    raise RuntimeError('Installer did not become current-slot-only')
                policies.append(policy)
            if policies[0] != policies[1]:
                raise RuntimeError('Native and standard installer policies differ')
            with zipfile.ZipFile(destination / PACKAGE, 'w') as output:
                for item in archive.infolist():
                    content = (root / item.filename).read_bytes() if item.filename in ENTRIES \
                              else archive.read(item)
                    output.writestr(copy.copy(item), content)
        signer = temporary / 'signature'
        signer.mkdir()
        for name, expected in SIGNER_BLOBS.items():
            path = signer / name
            fetch(f'https://raw.githubusercontent.com/AERA-Recovery/android_vendor_recovery/{VENDOR}/signature/{name}', path)
            content = path.read_bytes()
            actual = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            if actual != expected:
                raise RuntimeError('Pinned upstream signer file mismatch')
        subprocess.run(['bash', str(signer / 'sign_zip.sh'), '-z', str(destination / PACKAGE)], check=True)
        new_signers = verify_whole_file(destination / PACKAGE, temporary)
        if new_signers != original_signers:
            raise RuntimeError('The corrected installer uses a different signing certificate')
        with zipfile.ZipFile(destination / PACKAGE) as archive:
            if hashlib.sha256(archive.read('recovery.img')).hexdigest() != source_image_hash:
                raise RuntimeError('Re-signing changed the recovery image')
            for name in ENTRIES:
                if archive.read(name) != (root / name).read_bytes():
                    raise RuntimeError('Signing changed an installer entry')
            props = archive.read('META-INF/debug/default.prop').decode()
            build_time = int(re.search(r'^ro\.build\.date\.utc_aera=(\d+)$', props, re.M)[1])
        (destination / IMAGE).write_bytes((temporary / IMAGE).read_bytes())
        package_hash = digest(destination / PACKAGE)
        catalog = json.loads((temporary / 'catalog.json').read_text())
        entry = catalog['devices']['infiniti']
        for key in ('ota_parts', 'image_parts', 'part_size'):
            entry.pop(key, None)
        entry.update(build_time=build_time, filename=PACKAGE, size=(destination / PACKAGE).stat().st_size,
                     sha256=package_hash,
                     ota_url=f'https://github.com/{repository}/releases/download/{output_tag}/{PACKAGE}',
                     fallback_url=f'https://github.com/{repository}/releases/download/{output_tag}/{PACKAGE}',
                     changelog=['使用第28轮原始镜像，补齐原生安装入口，仅更新当前启动槽位。',
                                '包含浏览器字体、会话恢复、RPC通道与完整DNS属性修复，待实机验证。',
                                '保留分片累计进度与自动校时；不包含第30轮自动节点回退。',
                                '2.4 GHz热点稳定性仍待修复。'])
        for name in ('catalog.json', 'catalog-nightly.json'):
            (destination / name).write_text(json.dumps(catalog, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        (destination / 'SHA256SUMS').write_text(
            f'{source_image_hash}  {IMAGE}\n{package_hash}  {PACKAGE}\n', encoding='utf-8')
        report = dict(source_tag=source_tag, source_commit=source_commit, output_tag=output_tag,
                      packaging_commit=os.environ.get('GITHUB_SHA'), android_rebuilt=False,
                      image_sha256=source_image_hash, image_unchanged=True,
                      original_zip_sha256=digest(original), corrected_zip_sha256=package_hash,
                      original_signer_sha256=original_signers, corrected_signer_sha256=new_signers,
                      both_signatures_verified=True, both_installer_entries_current_slot_only=True,
                      build_time=build_time, device_runtime_verified=False)
        (destination / 'installer-repack-report.json').write_text(json.dumps(report, indent=2)+'\n')
        (destination / 'RELEASE_NOTES.md').write_text(
            '# AERA Recovery 第28轮 · 当前槽位安装包\n\n'
            '镜像与第28轮原始云构建完全相同。本次仅在 GitHub Actions 中补齐两个安装入口并重新签名，签名证书保持一致。\n\n'
            '- 仅向当前启动槽位写入 recovery；未知槽位时停止安装。\n'
            '- 包含第28轮浏览器字体、会话恢复、RPC 通道和 DNS 属性修复。\n'
            '- 保留分片累计进度、自动校时、北京时间及24小时制。\n'
            '- 不包含第30轮自动节点回退；2.4 GHz 稳定性仍待修复。\n\n'
            '新安装包的真实槽位安装结果及浏览器字体效果待设备验证。\n', encoding='utf-8')
        print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
