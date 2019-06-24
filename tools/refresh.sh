#! /bin/bash
if [ "$1" = "-f" ]; then
   echo "removing old generated files"
   rm -rf data/*/parsed
   rm -rf data/*/distilled
   rm -rf data/*/annotations
   rm -rf data/*/generated
   rm -rf data/*/toc
   rm -rf data/*/feed
   rm -rf data/*/deps
   set -e  # fail immediately on error
   echo "resetting fulltextindex"
   ./ferenda-build.py devel destroyindex
   echo "resetting triplestore"
   ./ferenda-build.py devel clearstore
fi
set -e
echo "updating git sources"
git pull -q
echo "building everything"
# ./ferenda-build.py all all --processes=7
./ferenda-build.py all all --buildserver
echo "creating statusreport"
./ferenda-build.py devel statusreport
cd ..
echo "running smoketests"
FERENDA_TESTURL=http://nate/ tools/test.sh integrationLagen
echo "deploying to remote"
# This MUST be run on the ES host (nate).
# ssh nate "cd wds/ferenda && fab -H colo.tomtebo.org -f tools/fabfile.py deploy"
# fab -H colo.tomtebo.org -f tools/fabfile.py deploy
fab -H staffan@banan.kodapan.se:20722 -f tools/fabfile.py deploy
