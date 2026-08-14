"""
Download the neural networks TagLab needs, and report whether the upstream project has moved on.

This script used to replace the source code as well: it fetched the latest release of
cnr-isti-vclab/TagLab as a zip, deleted coraline/, docs/, fonts/, icons/, source/ and .github/,
and overwrote every file in the main directory except config.json. On a customised build that
silently destroys the customisations, and there is no way to review or undo it.

That half has been removed. This is a git repository, and git already brings in upstream changes
properly - it merges rather than overwrites, it shows what changed, and it can be undone. What
git deliberately does *not* carry is the model weights, since models/*.pth, *.pth.tar and *.net
are all gitignored, so fetching those is what this script is still for.

To bring in changes from upstream instead, see the instructions printed at the end.
"""

import importlib.util
import os
import urllib.request
from pathlib import Path

TAGLAB_DIR = os.path.abspath(os.path.dirname(__file__))
MODELS_DIR = os.path.join(TAGLAB_DIR, 'models')

UPSTREAM_REPO = 'cnr-isti-vclab/TagLab'
UPSTREAM_VERSION_URL = 'https://raw.githubusercontent.com/' + UPSTREAM_REPO + '/main/TAGLAB_VERSION'
MODELS_URL = 'http://taglab.isti.cnr.it/models/'

NETWORKS = ['dextr_corals.pth', 'deeplab-resnet.pth.tar', 'ritm_corals.pth',
            'pocillopora.net', 'porites.net', 'pocillopora_porite_montipora.net']

# the SAM checkpoint is only worth its 2.4 GB download if segment_anything is installed
if importlib.util.find_spec('segment_anything'):
    NETWORKS.append('sam_vit_h_4b8939.pth')


def local_version():
    try:
        with open(os.path.join(TAGLAB_DIR, 'TAGLAB_VERSION'), 'r') as f:
            return f.read().strip()
    except OSError:
        return None


def upstream_version():
    try:
        return urllib.request.urlopen(UPSTREAM_VERSION_URL, timeout=10).read().decode('utf-8').strip()
    except Exception:
        return None


def download_networks():
    """
    Fetch any network weights that are not already present.

    A failure is reported and skipped rather than aborting: one unreachable file should not stop
    the others from being downloaded.
    """

    os.makedirs(MODELS_DIR, exist_ok=True)

    opener = urllib.request.build_opener()
    opener.addheaders = [('User-agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)

    missing = []
    for name in NETWORKS:
        target = Path(os.path.join(MODELS_DIR, name))
        if target.is_file():
            print(name + ' already exists.')
            continue

        url = MODELS_URL + name
        print('Downloading ' + url + ' ...')
        try:
            urllib.request.urlretrieve(url, str(target))
        except Exception as e:
            print('  FAILED: ' + str(e))
            # a partial file would look present next time round
            if target.is_file():
                target.unlink()
            missing.append(name)

    return missing


def main():
    print('TagLab networks')
    print('---------------')
    missing = download_networks()

    print()
    mine = local_version()
    theirs = upstream_version()
    if mine and theirs and mine != theirs:
        print('This build is ' + mine + '; upstream ' + UPSTREAM_REPO + ' is at ' + theirs + '.')
        print('This script no longer replaces the source, because doing so would discard the')
        print('changes in this fork. To review and merge the upstream changes instead:')
        print()
        print('    git fetch upstream')
        print('    git log --oneline HEAD..upstream/main    # see what changed')
        print('    git merge upstream/main                  # bring it in, resolving conflicts')
        print()
        print('(add the remote first if needed:')
        print('    git remote add upstream https://github.com/' + UPSTREAM_REPO + '.git)')
    elif mine and theirs:
        print('This build is ' + mine + ', the same version as upstream ' + UPSTREAM_REPO + '.')
    else:
        print('Could not compare against upstream (offline, or TAGLAB_VERSION is missing).')

    if missing:
        print()
        print('These networks could not be downloaded: ' + ', '.join(missing))
        print('The tools that use them will not work until they are present.')
        return 1

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
