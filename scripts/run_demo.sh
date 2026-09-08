#!/bin/sh
set -u

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
python="$repository_root/.venv/bin/python"
video="$repository_root/demo/generated/releaseseal-demo.mp4"
title=$(tr -d '\r\n' < "$repository_root/demo/title.txt")

if [ ! -x "$python" ]; then
  echo "Run the backend installation steps in README.md first." >&2
  exit 2
fi

"$python" "$repository_root/scripts/generate_demo_fixture.py" --output "$video" || exit $?

PYTHONPATH="$repository_root/backend/src${PYTHONPATH:+:$PYTHONPATH}" \
  "$python" -m releaseseal.cli scan "$video" \
  --title "$title" \
  --description-file "$repository_root/demo/description.txt" \
  --captions "$repository_root/demo/captions.srt" \
  --config "$repository_root/config/releaseseal.default.yml"
scan_status=$?

if [ "$scan_status" -eq 1 ]; then
  echo
  echo "Demo completed successfully. Exit 1 means the scan found review items."
  exit 0
fi
exit "$scan_status"
