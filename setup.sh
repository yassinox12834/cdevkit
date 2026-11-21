#!/usr/bin/env bash
source "$(dirname "$0")/_common.sh" || exit 1
exec .venv/bin/python setup_app.py "$@"
