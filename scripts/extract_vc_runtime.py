"""Extract Microsoft's signed/pinned redistributable without installing it.

The caller verifies the official installer SHA256. Read its Burn payload
manifest, preserve the licence and extract only the x64 minimum runtime CAB.
"""
import argparse
import hashlib
from pathlib import Path
import shutil
import struct
import subprocess
import xml.etree.ElementTree as ET


def unpack(seven, cabinet, output):
    result = subprocess.run([str(seven),'x','-y',str(cabinet),'-o'+str(output)],capture_output=True)
    if result.returncode:
        raise ValueError(f'7-Zip extraction failed: {cabinet}: {result.returncode}: {result.stdout!r} {result.stderr!r}')


def cabinet_bytes(data, offset=0):
    if data[offset:offset+4] != b'MSCF':
        raise ValueError('Invalid CAB signature')
    size = struct.unpack_from('<I',data,offset+8)[0]
    if size < 36 or offset+size > len(data):
        raise ValueError('Invalid/truncated cabinet')
    return data[offset:offset+size]


def extract(installer, output, seven):
    data = installer.read_bytes()
    stage = output/'extraction'
    stage.mkdir(parents=True,exist_ok=False)
    cabinets = []
    offset = 0
    while True:
        offset = data.find(b'MSCF',offset)
        if offset < 0:
            break
        cabinet = stage/(str(offset)+'.cab')
        cabinet.write_bytes(cabinet_bytes(data,offset))
        folder = stage/str(offset)
        unpack(seven,cabinet,folder)
        cabinets.append(folder)
        offset += len(cabinet.read_bytes())
    if len(cabinets) != 2 or not (cabinets[0]/'0').is_file():
        raise ValueError('Unsupported Microsoft Burn layout; expected UX and attached cabinets')
    manifest = ET.parse(cabinets[0]/'0').getroot()
    licence, payload = None, None
    for node in manifest.iter():
        if not node.tag.endswith('Payload'):
            continue
        path = node.attrib.get('FilePath','').replace('\\','/').lower()
        if path == 'license.rtf':
            licence = cabinets[0]/node.attrib['SourcePath']
        if '/vcruntimeminimum_amd64/' in path and path.endswith('.cab'):
            payload = cabinets[1]/node.attrib['SourcePath']
            actual = hashlib.sha1(payload.read_bytes()).hexdigest()
            if actual.lower() != node.attrib['Hash'].lower():
                raise ValueError('Signed Burn manifest payload hash mismatch')
    if not licence or not payload:
        raise ValueError('Required x64 minimum runtime payload/licence missing')
    shutil.copy2(licence,output/'LICENSE.rtf')
    # Signed CABs have an Authenticode trailer after cbCabinet. Extract the
    # checked cabinet bytes, so a genuine trailer warning never masks errors.
    minimum = stage/'minimum.cab'
    minimum.write_bytes(cabinet_bytes(payload.read_bytes()))
    dlls = stage/'minimum'
    unpack(seven,minimum,dlls)
    count = 0
    for file in dlls.iterdir():
        if file.name.lower().endswith('.dll_amd64'):
            name = file.name[:-6]
            binary = file.read_bytes()
            pe = struct.unpack_from('<I',binary,0x3c)[0]
            if binary[:2] != b'MZ' or struct.unpack_from('<H',binary,pe+4)[0] != 0x8664:
                raise ValueError(f'Not a Windows x64 runtime: {file}')
            shutil.copy2(file,output/name)
            count += 1
    if count < 3:
        raise ValueError('Incomplete Microsoft runtime extraction')
    # Keep extraction evidence in the preparation log; output contains only the
    # required redistributable files and their original licence.
    shutil.rmtree(stage)
    print(f'Extracted {count} Microsoft x64 runtime DLLs, licence retained')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--installer',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seven',type=Path,required=True)
    args = parser.parse_args()
    extract(args.installer,args.output,args.seven)
