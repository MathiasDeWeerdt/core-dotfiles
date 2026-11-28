#!/usr/bin/env bash
# --noconfirm alone answers "No" to conflicting-package removal. Invert only
# ALPM_QUESTION_CONFLICT_PKG (4); replacements already default to "Yes".
# Keep signature checks and dependency checks enabled.
PACMAN_FLAGS=(--noconfirm --ask=4)
YAY_FLAGS=(--noconfirm --useask --ask=4 --answerclean All --answerdiff None
           --answeredit None --answerupgrade None --removemake --sudoloop)
