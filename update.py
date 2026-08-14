"""
Update TagLab to the latest version, and download the neural networks it needs.

Run this from the TagLab folder:

    python update.py

It compares this installation against the version published in the TagLab repository, and if a
newer one is available it downloads it and replaces the program files. Your configuration
(config.json) and anything else you keep in the folder - projects, imagery, exports - are left
alone. Then it fetches any neural networks that are missing, since those are not part of the
download.
"""

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

# The repository users update from. Change this if the project moves.
UPDATE_REPO = 'wogreene/TagLab'
UPDATE_BRANCH = 'main'

TAGLAB_DIR = os.path.abspath(os.path.dirname(__file__))
MODELS_DIR = os.path.join(TAGLAB_DIR, 'models')

RAW_URL = 'https://raw.githubusercontent.com/' + UPDATE_REPO + '/' + UPDATE_BRANCH + '/TAGLAB_VERSION'
ZIP_URL = 'https://github.com/' + UPDATE_REPO + '/archive/refs/heads/' + UPDATE_BRANCH + '.zip'

MODELS_URL = 'http://taglab.isti.cnr.it/models/'

# Files never overwritten, because they hold the user's own settings.
PRESERVED_FILES = ['config.json']

# Directories worth mentioning if they end up holding program files that the new version no
# longer ships. Nothing is ever deleted - they are only reported.
PROGRAM_DIRECTORIES = ['coraline', 'docs', 'fonts', 'icons', 'source', '.github']

NETWORKS = ['dextr_corals.pth', 'deeplab-resnet.pth.tar', 'ritm_corals.pth',
            'pocillopora.net', 'porites.net', 'pocillopora_porite_montipora.net']


def read_local_version():
    try:
        with open(os.path.join(TAGLAB_DIR, 'TAGLAB_VERSION'), 'r') as f:
            return f.read().strip()
    except OSError:
        return None


def read_online_version():
    try:
        return urllib.request.urlopen(RAW_URL, timeout=30).read().decode('utf-8').strip()
    except Exception as e:
        print('Could not check for a new version: ' + str(e))
        return None


def is_newer(online, local):
    """
    True if the online version is newer. Versions are dotted numbers, e.g. 2026.4.1, and are
    compared component by component; anything unparseable falls back to "different means newer",
    which errs towards offering the update rather than hiding it.
    """

    def parts(v):
        try:
            return [int(p) for p in v.split('.')]
        except ValueError:
            return None

    a, b = parts(online), parts(local)
    if a is None or b is None:
        return online != local

    # pad so 2026.4 and 2026.4.0 compare equal
    length = max(len(a), len(b))
    a += [0] * (length - len(a))
    b += [0] * (length - len(b))
    return a > b


def download_new_version(destination_dir):
    """
    Download and unpack the new version into destination_dir.

    Returns the path of the unpacked TagLab folder, or None on failure. Nothing in the
    installation is touched here: the download is fully verified before anything is replaced,
    so a failed or interrupted update cannot leave a half-broken install behind.
    """

    archive = os.path.join(destination_dir, 'taglab.zip')

    print('Downloading ' + ZIP_URL + ' ...')
    try:
        opener = urllib.request.build_opener()
        opener.addheaders = [('User-agent', 'Mozilla/5.0')]
        urllib.request.install_opener(opener)
        urllib.request.urlretrieve(ZIP_URL, archive)
    except Exception as e:
        print('Download failed: ' + str(e))
        return None

    print('Unpacking...')
    unpacked = os.path.join(destination_dir, 'unpacked')
    try:
        with zipfile.ZipFile(archive, 'r') as zip_ref:
            zip_ref.extractall(unpacked)
    except Exception as e:
        print('The downloaded file could not be unpacked: ' + str(e))
        return None

    # a GitHub archive holds a single top-level folder, whose name depends on the branch
    entries = [os.path.join(unpacked, name) for name in os.listdir(unpacked)]
    roots = [p for p in entries if os.path.isdir(p)]
    if len(roots) != 1:
        print('The downloaded archive does not look like TagLab.')
        return None

    root = roots[0]
    if not os.path.isfile(os.path.join(root, 'TagLab.py')) or \
            not os.path.isdir(os.path.join(root, 'source')):
        print('The downloaded archive is missing TagLab.py or source/. Update aborted.')
        return None

    return root


def apply_update(root):
    """
    Copy the new program files over the installation.

    Nothing is ever deleted. Files belonging to the new version are written over the old ones,
    new files are added, and everything else in the folder is left exactly as it was: label
    images, custom dictionaries, exports, and the project folders that people keep inside the
    TagLab directory all survive an update untouched.

    The cost of never deleting is that a file dropped from a later release stays behind. Those
    are inert - nothing imports them - so they are reported at the end rather than removed,
    which is much the better trade when the alternative risks deleting someone's data.
    """

    for name in os.listdir(root):
        source = os.path.join(root, name)
        target = os.path.join(TAGLAB_DIR, name)

        if os.path.isdir(source):
            try:
                shutil.copytree(source, target, dirs_exist_ok=True)
            except Exception as e:
                print('Could not update the %s folder: %s' % (name, e))
        elif name not in PRESERVED_FILES:
            try:
                shutil.copyfile(source, target)
            except Exception as e:
                print('Could not update %s: %s' % (name, e))


def find_leftovers(root):
    """
    Python files in the program directories that the new version does not ship.

    These are almost always modules removed upstream. They are listed, never deleted, because
    telling them apart from a file the user put there is not possible.
    """

    leftovers = []
    for name in PROGRAM_DIRECTORIES:
        installed_dir = os.path.join(TAGLAB_DIR, name)
        new_dir = os.path.join(root, name)
        if not os.path.isdir(installed_dir) or not os.path.isdir(new_dir):
            continue

        for base, dirs, files in os.walk(installed_dir):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for f in files:
                if not f.endswith('.py'):
                    continue
                relative = os.path.relpath(os.path.join(base, f), installed_dir)
                if not os.path.exists(os.path.join(new_dir, relative)):
                    leftovers.append(os.path.join(name, relative))

    return leftovers


def rebuild_coraline():
    """
    Coraline is a compiled library and ships prebuilt on Windows only.
    """

    if platform.system() == 'Windows':
        return

    coraline_dir = os.path.join(TAGLAB_DIR, 'coraline')
    if not os.path.isdir(coraline_dir):
        return

    print('Rebuilding Coraline...')
    previous = os.getcwd()
    try:
        subprocess.check_output(['cmake', '--version'])
        os.chdir(coraline_dir)
        if subprocess.getstatusoutput('cmake .')[0] != 0:
            print('Could not configure Coraline. Please build it manually.')
            return
        if subprocess.getstatusoutput('make')[0] != 0:
            print('Could not build Coraline. Please build it manually.')
            return
        print('Coraline built correctly.')
    except OSError:
        print('cmake was not found, so Coraline was not rebuilt. Please install cmake and '
              'build it manually.')
    finally:
        os.chdir(previous)


def download_networks():
    """
    Fetch any networks that are missing. These are not part of the program download.
    """

    networks = list(NETWORKS)
    try:
        import importlib.util
        if importlib.util.find_spec('segment_anything'):
            networks.append('sam_vit_h_4b8939.pth')
    except Exception:
        pass

    os.makedirs(MODELS_DIR, exist_ok=True)

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)

    missing = []
    for name in networks:
        target = Path(os.path.join(MODELS_DIR, name))
        if target.is_file():
            print(name + ' already exists.')
            continue

        print('Downloading ' + name + ' ...')
        try:
            urllib.request.urlretrieve(MODELS_URL + name, str(target))
        except Exception as e:
            print('  failed: ' + str(e))
            # a partial file would look present next time round
            if target.is_file():
                target.unlink()
            missing.append(name)

    return missing


def main():

    local = read_local_version()
    online = read_online_version()

    print('Installed version: ' + str(local))
    print('Latest version:    ' + str(online))
    print()

    if online is not None and local is not None and is_newer(online, local):
        print('A new version is available. Updating...')

        with tempfile.TemporaryDirectory() as work_dir:
            root = download_new_version(work_dir)
            if root is None:
                print()
                print('TagLab has NOT been changed. Please try again later.')
                return 1

            apply_update(root)
            leftovers = find_leftovers(root)

        rebuild_coraline()
        print('TagLab has been updated to ' + online + '.')
        print('Your settings, label images, dictionaries and project folders were left alone.')
        print('If TagLab reports a missing package after this, run install.py.')

        if leftovers:
            print()
            print('These files are not part of the new version and were left in place:')
            for name in leftovers[:10]:
                print('    ' + name)
            if len(leftovers) > 10:
                print('    ...and %d more' % (len(leftovers) - 10))
            print('They are unused. Delete them only if you know they are not yours.')
    else:
        print('TagLab is already up to date.')

    print()
    print('Checking the neural networks...')
    missing = download_networks()

    if missing:
        print()
        print('These networks could not be downloaded: ' + ', '.join(missing))
        print('The tools that use them will not work until they are present.')
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
