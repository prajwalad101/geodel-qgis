#!/usr/bin/env bash
set -euo pipefail
repo=prajwalad101/geodel-qgis
gh label create needs-triage --repo "$repo" --color D4C5F9 --description "Needs evaluation" --force
gh label create needs-info --repo "$repo" --color FEF2C0 --description "Waiting on reporter" --force
gh label create ready-for-agent --repo "$repo" --color 0E8A16 --description "Ready for an agent" --force
gh label create ready-for-human --repo "$repo" --color 1D76DB --description "Ready for a human" --force
gh label create wontfix --repo "$repo" --color FFFFFF --description "Will not be actioned" --force
